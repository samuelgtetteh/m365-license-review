"""FastAPI application factory and routes.

Serves the index, drives the auth-code+PKCE sign-in, and shows the tenant
confirmation step. The audit run + download routes land in step 7. All heavy
lifting lives in ``m365_review.core``; this module stays thin.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from m365_review import __version__
from m365_review.core import auth as core_auth
from m365_review.core.engine import run_audit
from m365_review.core.profiles import get_store
from m365_review.settings import get_settings
from m365_review.web.sessions import COOKIE_NAME, store

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

app = FastAPI(
    title="M365 License Review",
    version=__version__,
    description="Read-only Microsoft 365 license optimization tool (MSP).",
)

app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")


def _set_session_cookie(response, sid: str) -> None:
    """Attach the signed, httponly, samesite session cookie."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=store.sign_sid(sid),
        httponly=True,
        samesite="lax",
        secure=False,  # localhost/http; set True behind TLS
        max_age=60 * 60,  # 1 hour
    )


# --------------------------------------------------------------------------- #
# Basic pages
# --------------------------------------------------------------------------- #

@app.get("/healthz", response_class=JSONResponse)
async def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    """Operator help: what the tool does, how to sign in, formats, rules, privacy."""
    settings = get_settings()
    return TEMPLATES.TemplateResponse(
        request,
        "help.html",
        {
            "version": __version__,
            "redirect_uri": settings.azure_redirect_uri,
            "scopes": settings.graph_scopes,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    settings = get_settings()
    client_id_configured = bool(settings.azure_app_client_id) and not (
        settings.azure_app_client_id.startswith("00000000")
    )
    profiles = get_store(settings).list()
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {
            "version": __version__,
            "client_id_configured": client_id_configured,
            "default_client_id": settings.azure_app_client_id if client_id_configured else "",
            "redirect_uri": settings.azure_redirect_uri,
            "scopes": settings.graph_scopes,
            "profiles": profiles,
        },
    )


# --------------------------------------------------------------------------- #
# Auth (authorization code + PKCE)
# --------------------------------------------------------------------------- #

@app.get("/auth/login")
async def auth_login(request: Request) -> RedirectResponse:
    """Create a session, resolve the client ID (saved profile or new), redirect."""
    settings = get_settings()
    params = request.query_params
    profiles = get_store(settings)

    # Resolve the client ID from either a saved profile or the add-new fields.
    profile_name = params.get("profile", "").strip()
    client_id = params.get("client_id", "").strip()
    new_profile_name = params.get("new_profile_name", "").strip()

    if profile_name and profile_name != "__new__":
        saved = profiles.get(profile_name)
        if saved is None:
            return _error_redirect(f"Profile '{profile_name}' not found.")
        client_id = saved.client_id
        active_profile = saved.name
    else:
        if not client_id:
            client_id = settings.azure_app_client_id
        active_profile = None
        # Save as a new named profile if a name was given.
        if new_profile_name and client_id:
            try:
                profiles.upsert(new_profile_name, client_id)
                active_profile = new_profile_name
            except ValueError as exc:
                return _error_redirect(str(exc))

    updates = {}
    if client_id:
        updates["azure_app_client_id"] = client_id

    # Build the OAuth redirect URI from the port the browser actually used, so the
    # tool works on any host port (e.g. when 8000 is busy and it fell back to 8080).
    # An explicit AZURE_REDIRECT_URI env var still wins (for proxy/HTTPS setups).
    if not os.environ.get("AZURE_REDIRECT_URI"):
        updates["azure_redirect_uri"] = str(request.base_url).rstrip("/") + "/auth/callback"

    if updates:
        settings = settings.model_copy(update=updates)

    session = store.create()
    session.options = {
        "formats": params.getlist("formats") or ["xlsx", "docx", "json"],
        "experimental": params.get("experimental") == "1",
        "client_id": client_id or settings.azure_app_client_id,
        "profile": active_profile,
        "redirect_uri": settings.azure_redirect_uri,
    }

    try:
        flow = core_auth.begin_web_auth(settings=settings)
    except core_auth.AuthError as exc:
        store.destroy(session.sid)
        return _error_redirect(str(exc))

    session.auth_flow = flow
    response = RedirectResponse(flow["auth_uri"], status_code=302)
    _set_session_cookie(response, session.sid)
    return response


@app.get("/auth/callback")
async def auth_callback(request: Request) -> RedirectResponse:
    """Handle Microsoft's redirect: exchange the code for a token."""
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    if session is None or session.auth_flow is None:
        return _error_redirect("Session expired or missing. Please start again.")

    settings = get_settings()
    client_id = session.options.get("client_id")
    if client_id:
        settings = settings.model_copy(update={"azure_app_client_id": client_id})

    auth_response = dict(request.query_params)
    if "error" in auth_response:
        return _error_redirect(
            f"Sign-in was cancelled or denied: {auth_response.get('error_description', auth_response['error'])}"
        )

    try:
        tenant = core_auth.complete_web_auth(session.auth_flow, auth_response, settings=settings)
    except core_auth.AuthError as exc:
        return _error_redirect(str(exc))

    session.tenant = tenant
    session.auth_flow = None  # single-use; drop it

    # Resolve the friendly tenant name so the confirm page is meaningful.
    # Best-effort: never block sign-in on it.
    try:
        from m365_review.core.fetchers.organization import fetch_organization
        from m365_review.core.graph_client import GraphClient

        async with GraphClient(tenant) as gc:
            org = await fetch_organization(gc)
        tenant.tenant_display_name = org.display_name
    except Exception as exc:  # noqa: BLE001 — confirm page degrades gracefully
        logger.info("Could not resolve tenant display name yet: %s", type(exc).__name__)

    return RedirectResponse("/confirm", status_code=302)


@app.get("/confirm", response_class=HTMLResponse)
async def confirm(request: Request) -> HTMLResponse:
    """Belt-and-suspenders: operator visually verifies the correct tenant."""
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    if session is None or session.tenant is None:
        return _error_html("Not signed in. Please start again.")

    t = session.tenant
    return TEMPLATES.TemplateResponse(
        request,
        "confirm.html",
        {
            "tenant_display_name": t.tenant_display_name or "(resolved during audit)",
            "tenant_id": t.tenant_id,
            "username": t.username,
            "options": session.options,
        },
    )


# --------------------------------------------------------------------------- #
# Run the audit (SSE progress) + download
# --------------------------------------------------------------------------- #

@app.post("/run", response_class=HTMLResponse)
async def run_start(request: Request) -> HTMLResponse:
    """Show the progress page, which opens an SSE stream to /run/stream."""
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    if session is None or session.tenant is None:
        return _error_html("Not signed in. Please start again.")
    return TEMPLATES.TemplateResponse(
        request,
        "running.html",
        {"tenant_display_name": session.tenant.tenant_display_name or session.tenant.tenant_id},
    )


@app.get("/run/stream")
async def run_stream(request: Request) -> EventSourceResponse:
    """Run the audit, streaming progress events, then a final 'done' event."""
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    settings = get_settings()

    async def event_gen():
        if session is None or session.tenant is None:
            yield {"event": "error", "data": json.dumps({"message": "Session expired."})}
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def progress(label: str, fraction: float) -> None:
            await queue.put({"type": "progress", "label": label, "fraction": fraction})

        async def do_audit() -> None:
            try:
                result, paths = await run_audit(
                    session.tenant,
                    formats=session.options.get("formats", ["xlsx", "docx", "json"]),
                    output_dir=settings.output_dir,
                    experimental=session.options.get("experimental", False),
                    progress=progress,
                )
                session.reports = paths
                # Record profile usage (last-audited tenant) for the audit trail.
                active_profile = session.options.get("profile")
                if active_profile:
                    try:
                        get_store(settings).touch(
                            active_profile,
                            tenant_id=result.tenant_id,
                            tenant_name=result.tenant_display_name,
                        )
                    except Exception:  # noqa: BLE001 — never fail the run over bookkeeping
                        logger.warning("Could not update profile '%s' usage.", active_profile)
                # Stash a lightweight summary for the results page, then drop the token.
                session.options["result_summary"] = {
                    "tenant": result.tenant_display_name,
                    "tenant_id": result.tenant_id,
                    "monthly": result.total_monthly_savings_usd,
                    "annual": result.total_annual_savings_usd,
                    "findings": len(result.findings),
                    "severity": result.severity_counts(),
                    "formats": list(paths.keys()),
                }
                session.clear_sensitive()  # security: token no longer needed
                await queue.put({"type": "done"})
            except Exception as exc:  # noqa: BLE001
                logger.exception("Audit failed")
                await queue.put({"type": "error", "message": str(exc)})

        task = asyncio.create_task(do_audit())
        while True:
            item = await queue.get()
            if item["type"] == "progress":
                yield {"event": "progress", "data": json.dumps(item)}
            elif item["type"] == "done":
                yield {"event": "done", "data": json.dumps({"redirect": "/results"})}
                break
            elif item["type"] == "error":
                yield {"event": "error", "data": json.dumps({"message": item["message"]})}
                break
        await task

    return EventSourceResponse(event_gen())


@app.get("/results", response_class=HTMLResponse)
async def results(request: Request) -> HTMLResponse:
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    summary = (session.options.get("result_summary") if session else None)
    if session is None or not summary:
        return _error_html("No completed audit in this session.")
    return TEMPLATES.TemplateResponse(
        request, "results.html", {"s": summary, "formats": list(session.reports.keys())}
    )


@app.get("/download/{fmt}")
async def download(request: Request, fmt: str) -> FileResponse:
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    if session is None or not session.reports:
        return _error_html("No report available to download.")

    if fmt == "all":
        base = next(iter(session.reports.values())).stem
        tmp_zip = Path(tempfile.gettempdir()) / f"{base}.zip"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in session.reports.values():
                zf.write(path, arcname=path.name)
        return FileResponse(tmp_zip, filename=tmp_zip.name, media_type="application/zip")

    path = session.reports.get(fmt)
    if path is None or not path.exists():
        return _error_html(f"No {fmt} report available.")
    return FileResponse(path, filename=path.name)


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    session = store.get_by_cookie(request.cookies.get(COOKIE_NAME))
    if session:
        store.destroy(session.sid)
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _error_redirect(message: str) -> RedirectResponse:
    from urllib.parse import quote

    return RedirectResponse(f"/error?msg={quote(message)}", status_code=302)


@app.get("/error", response_class=HTMLResponse)
async def error_page(request: Request, msg: str = "Something went wrong.") -> HTMLResponse:
    return _error_html(msg)


def _error_html(message: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><meta charset="utf-8">
        <link rel="stylesheet" href="/static/style.css"><title>Error</title></head>
        <body><main class="wrap"><div class="banner warn"><strong>Error.</strong> {message}</div>
        <p><a href="/">&larr; Start again</a></p></main></body></html>""",
        status_code=400,
    )
