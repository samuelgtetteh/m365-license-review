"""Microsoft authentication via MSAL.

Two delegated flows over ONE multi-tenant public client (no client secret):

* **Web**: authorization code + PKCE (redirect). Used by the FastAPI app.
* **CLI**: interactive loopback (also auth-code + PKCE) with a device-code
  fallback for headless containers.

Design rules (from the handoff, non-negotiable):
* Read-only scopes only — see ``Settings.graph_scopes``. Never request write scopes.
* Tokens live in memory for the run only. Never persisted to disk, never logged.
* Authority is ``/organizations`` so any work/school tenant can sign in; the
  tenant is identified after sign-in from the id-token ``tid`` claim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import msal

from m365_review.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class TenantSession:
    """The authenticated context for a single tenant audit.

    ``access_token`` is sensitive: it is never logged or serialized. ``__repr__``
    is overridden so it cannot leak into tracebacks or log lines.
    """

    access_token: str
    tenant_id: str
    username: str | None = None
    scopes: tuple[str, ...] = ()
    _tenant_display_name: str | None = field(default=None, repr=False)

    @property
    def tenant_display_name(self) -> str | None:
        return self._tenant_display_name

    @tenant_display_name.setter
    def tenant_display_name(self, value: str | None) -> None:
        self._tenant_display_name = value

    def __repr__(self) -> str:  # never expose the token
        return (
            f"TenantSession(tenant_id={self.tenant_id!r}, username={self.username!r}, "
            f"tenant_display_name={self._tenant_display_name!r}, access_token=<redacted>)"
        )


class AuthError(RuntimeError):
    """Raised when a token could not be acquired."""


def build_public_client(settings: Settings | None = None) -> msal.PublicClientApplication:
    """Construct the MSAL public client app (no secret, multi-tenant authority)."""
    settings = settings or get_settings()
    if not settings.azure_app_client_id or settings.azure_app_client_id.startswith("00000000"):
        raise AuthError(
            "AZURE_APP_CLIENT_ID is not configured. Set it in .env or pass it in the web form."
        )
    return msal.PublicClientApplication(
        client_id=settings.azure_app_client_id,
        authority=settings.azure_authority,
        # token_cache omitted on purpose: in-memory, per-process, discarded on exit.
    )


def _session_from_result(result: dict[str, Any], scopes: tuple[str, ...]) -> TenantSession:
    """Turn an MSAL token result into a TenantSession, or raise AuthError."""
    if "access_token" not in result:
        # Do NOT log `result` verbatim — it may echo tokens on success paths.
        err = result.get("error", "unknown_error")
        desc = result.get("error_description", "")
        raise AuthError(f"Token acquisition failed: {err}. {desc.splitlines()[0] if desc else ''}")

    claims = result.get("id_token_claims", {}) or {}
    tenant_id = claims.get("tid")
    if not tenant_id:
        raise AuthError("Signed in but no tenant id (tid) claim was returned.")

    return TenantSession(
        access_token=result["access_token"],
        tenant_id=tenant_id,
        username=claims.get("preferred_username") or claims.get("upn"),
        scopes=scopes,
    )


# --------------------------------------------------------------------------- #
# Web: authorization code + PKCE
# --------------------------------------------------------------------------- #

def begin_web_auth(
    settings: Settings | None = None,
    app: msal.PublicClientApplication | None = None,
) -> dict[str, Any]:
    """Start the auth-code flow. Returns MSAL's flow dict.

    The flow dict contains ``auth_uri`` (send the browser there) plus ``state``
    and the PKCE ``code_verifier``. Store the WHOLE dict server-side (keyed by
    the session cookie) and hand it back to :func:`complete_web_auth`.
    """
    settings = settings or get_settings()
    app = app or build_public_client(settings)
    flow = app.initiate_auth_code_flow(
        scopes=list(settings.graph_scopes),
        redirect_uri=settings.azure_redirect_uri,
    )
    if "auth_uri" not in flow:
        raise AuthError("Failed to initiate authorization code flow.")
    return flow


def complete_web_auth(
    flow: dict[str, Any],
    auth_response: dict[str, Any],
    settings: Settings | None = None,
    app: msal.PublicClientApplication | None = None,
) -> TenantSession:
    """Exchange the redirect response for a token.

    ``auth_response`` is the query-string params dict from the /auth/callback
    request. MSAL validates the ``state`` parameter internally (CSRF protection).
    """
    settings = settings or get_settings()
    app = app or build_public_client(settings)
    result = app.acquire_token_by_auth_code_flow(flow, auth_response)
    return _session_from_result(result, tuple(settings.graph_scopes))


# --------------------------------------------------------------------------- #
# CLI: interactive loopback, with device-code fallback
# --------------------------------------------------------------------------- #

def cli_interactive_auth(
    settings: Settings | None = None,
    device_code_callback: Callable[[str], None] | None = None,
    prefer_device_code: bool = False,
) -> TenantSession:
    """Acquire a token from the CLI.

    By default tries the interactive browser (loopback) flow first, then falls
    back to device code. Set ``prefer_device_code=True`` (headless / container)
    to skip straight to device code — it prints a code + URL to enter in any
    browser. Requires "Allow public client flows: Yes" on the app registration.
    """
    settings = settings or get_settings()
    app = build_public_client(settings)
    scopes = list(settings.graph_scopes)

    if not prefer_device_code:
        try:
            result = app.acquire_token_interactive(scopes=scopes)
            return _session_from_result(result, tuple(scopes))
        except Exception as exc:  # noqa: BLE001 — any browser/loopback failure -> device code
            logger.info(
                "Interactive auth unavailable (%s); falling back to device code.",
                type(exc).__name__,
            )

    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        err = flow.get("error", "")
        desc = (flow.get("error_description", "") or "").splitlines()
        detail = desc[0] if desc else ""
        hint = ""
        if "7000218" in detail or err in ("invalid_client", "unauthorized_client"):
            hint = (
                " This usually means 'Allow public client flows' is not enabled on the "
                "app registration (Azure → App registrations → your app → Authentication → "
                "Settings → Allow public client flows: Yes)."
            )
        raise AuthError(f"Failed to start device code flow: {err} {detail}.{hint}".strip())
    message = flow["message"]  # "To sign in, use a web browser ... enter the code ABC-DEF ..."
    if device_code_callback:
        device_code_callback(message)
    else:
        print(message)
    result = app.acquire_token_by_device_flow(flow)  # blocks until the user completes sign-in
    return _session_from_result(result, tuple(scopes))
