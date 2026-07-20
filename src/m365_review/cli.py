"""Typer CLI entrypoint.

Second entry point over the same ``m365_review.core`` engine as the web app.
Step 1 scaffold: wires up the command surface and prints a banner. The `run`
and `sku-check` commands are fleshed out in later steps.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import typer

from m365_review import __version__
from m365_review.settings import get_settings

app = typer.Typer(
    name="m365-review",
    help="Read-only Microsoft 365 license review & optimization (MSP tool).",
    no_args_is_help=True,
    add_completion=False,
)


class OutputFormat(str, Enum):
    xlsx = "xlsx"
    docx = "docx"
    json = "json"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"m365-review {__version__}")
        raise typer.Exit()


def _resolve_device_code(flag: bool | None) -> bool:
    """Decide whether to use device-code sign-in.

    Explicit --device-code/--interactive wins. Otherwise auto-enable when running
    headless inside a container (no browser available).
    """
    import os

    if flag is not None:
        return flag
    return os.path.exists("/.dockerenv") or os.environ.get("M365_DEVICE_CODE") == "1"


def _pick_profile_interactively(store):
    """Prompt the operator to choose which saved profile to connect with.

    Returns (client_id, profile_name) for the chosen/created profile, or None to
    let the caller fall back to the AZURE_APP_CLIENT_ID environment default.
    Non-interactive shells (no TTY) skip the prompt and return None.
    """
    import sys

    if not sys.stdin.isatty():
        return None

    profiles = store.list()
    typer.echo("")
    typer.secho("Which client do you want to audit?", fg=typer.colors.CYAN, bold=True)
    for i, p in enumerate(profiles, start=1):
        last = f"  (last: {p.last_tenant_name})" if p.last_tenant_name else ""
        typer.echo(f"  {i}. {p.name}{last}")
    new_idx = len(profiles) + 1
    typer.echo(f"  {new_idx}. Enter a new client ID")
    if not profiles:
        typer.echo("  (no saved profiles yet)")

    choice = typer.prompt("Select a number", default="1" if profiles else str(new_idx))
    try:
        n = int(choice)
    except ValueError:
        typer.secho("Not a number; using environment default.", fg=typer.colors.YELLOW)
        return None

    if 1 <= n <= len(profiles):
        p = profiles[n - 1]
        typer.echo(f"Using profile '{p.name}'.")
        return p.client_id, p.name, p.tenant_domain

    if n == new_idx:
        cid = typer.prompt("Azure app client ID").strip()
        if not cid:
            return None
        domain = typer.prompt(
            "Client tenant domain or ID (e.g. contoso.com) — leave blank if unsure",
            default="", show_default=False,
        ).strip() or None
        if typer.confirm("Save this as a named profile for next time?", default=True):
            name = typer.prompt("Profile name (e.g. the client/company)").strip()
            if name:
                store.upsert(name, cid, tenant_domain=domain)
                typer.secho(f"Saved profile '{name}'.", fg=typer.colors.GREEN)
                return cid, name, domain
        return cid, None, domain

    typer.secho("Out of range; using environment default.", fg=typer.colors.YELLOW)
    return None


@app.callback()
def main(
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """M365 License Review CLI."""


@app.command()
def run(
    profile: str = typer.Option(
        None, "--profile", "-p",
        help="Use a saved profile by name. If omitted, you'll be asked to pick one.",
    ),
    client_id: str = typer.Option(
        None, "--client-id", "-c",
        help="Use this Azure app client ID directly (bypasses profiles).",
    ),
    tenant: str = typer.Option(
        None, "--tenant", "-t",
        help="Client tenant domain (e.g. contoso.com) or tenant ID. Required for "
             "device-code sign-in; taken from the profile if saved.",
    ),
    output: Path = typer.Option(
        None, "--output", "-o", help="Directory to write reports into. Defaults to OUTPUT_DIR."
    ),
    formats: list[OutputFormat] = typer.Option(
        [OutputFormat.xlsx, OutputFormat.docx, OutputFormat.json],
        "--format", "-f", help="Output format(s). Repeatable.",
    ),
    audit: list[str] = typer.Option(
        None, "--audit", "-a",
        help="Audit id(s) to run (repeatable). Default: all. See `m365-review audits`.",
    ),
    category: list[str] = typer.Option(
        None, "--category", help="Run all audits in a category (repeatable)."
    ),
    enable_experimental_rules: bool = typer.Option(
        False, "--enable-experimental-rules", help="Include rules R5-R7 (higher false-positive rate)."
    ),
    device_code: bool = typer.Option(
        None, "--device-code/--interactive",
        help="Use device-code sign-in (headless/container). Auto-enabled inside Docker.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging."),
) -> None:
    """Authenticate to a client tenant and produce an optimization report."""
    import asyncio
    import logging

    from m365_review.core import audits as audit_catalog
    from m365_review.core.auth import AuthError, cli_interactive_auth
    from m365_review.core.engine import run_audit
    from m365_review.core.profiles import get_store

    prefer_device_code = _resolve_device_code(device_code)

    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    settings = get_settings()
    out = output or settings.output_dir
    fmt_values = [f.value for f in formats]

    # Resolve selected audits → drives both what runs and the scopes requested.
    selected_audits = audit_catalog.resolve(
        ids=audit or None, categories=category or None, include_experimental=enable_experimental_rules
    )
    if not selected_audits:
        typer.secho("No matching audits for that selection. See `m365-review audits`.", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    audit_ids = [a.id for a in selected_audits]
    settings = settings.model_copy(
        update={"graph_scopes": tuple(audit_catalog.required_scopes(selected_audits))}
    )
    typer.echo(f"Audits: {', '.join(audit_ids)}")

    # Decide which client ID / profile to connect with, in priority order:
    #   --profile NAME  ->  --client-id ID  ->  interactive picker  ->  env default
    import sys

    store = get_store(settings)
    active_profile = None
    chosen_client_id = None
    chosen_tenant = tenant

    if profile:
        saved = store.get(profile)
        if saved is None:
            typer.secho(
                f"Profile '{profile}' not found. See `m365-review profiles list`.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        chosen_client_id, active_profile = saved.client_id, saved.name
        chosen_tenant = chosen_tenant or saved.tenant_domain
        typer.echo(f"Using profile '{saved.name}'.")
    elif client_id:
        chosen_client_id = client_id.strip()
        typer.echo("Using the client ID provided on the command line.")
    else:
        picked = _pick_profile_interactively(store)
        if picked is not None:
            chosen_client_id, active_profile, picked_tenant = picked
            chosen_tenant = chosen_tenant or picked_tenant
        # else: fall back to the AZURE_APP_CLIENT_ID env default (if configured)

    if chosen_client_id:
        settings = settings.model_copy(update={"azure_app_client_id": chosen_client_id})

    # Device-code sign-in needs a tenant-specific authority (otherwise Microsoft
    # returns AADSTS50059: no tenant-identifying information). Interactive/browser
    # sign-in can use /organizations, so a tenant is only required for device code.
    if prefer_device_code and not chosen_tenant:
        if sys.stdin.isatty():
            chosen_tenant = typer.prompt(
                "Client tenant domain (e.g. contoso.com) or tenant ID"
            ).strip()
        if not chosen_tenant:
            typer.secho(
                "Device-code sign-in requires a tenant. Re-run with "
                "--tenant <domain-or-id> (or save it on the profile).",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)

    if chosen_tenant:
        authority = f"https://login.microsoftonline.com/{chosen_tenant.strip()}"
        settings = settings.model_copy(update={"azure_authority": authority})
        # Persist the tenant back onto the profile for next time.
        if active_profile:
            try:
                existing = store.get(active_profile)
                if existing and not existing.tenant_domain:
                    store.upsert(active_profile, chosen_client_id, tenant_domain=chosen_tenant.strip())
            except Exception:  # noqa: BLE001
                pass

    async def _progress(label: str, fraction: float) -> None:
        typer.echo(f"  [{int(fraction * 100):3d}%] {label}")

    async def _run() -> None:
        if prefer_device_code:
            typer.echo("Starting device-code sign-in…")
        else:
            typer.echo("Starting sign-in (a browser window will open)…")
        session = cli_interactive_auth(settings=settings, prefer_device_code=prefer_device_code)

        # Resolve + confirm tenant before auditing (mirrors the web confirm step).
        from m365_review.core.fetchers.organization import fetch_organization
        from m365_review.core.graph_client import GraphClient

        async with GraphClient(session) as gc:
            org = await fetch_organization(gc)
        session.tenant_display_name = org.display_name

        typer.secho(
            f"Signed in to tenant: {org.display_name} ({session.tenant_id})", fg=typer.colors.GREEN
        )
        if not typer.confirm("Proceed with audit?", default=False):
            typer.echo("Aborted.")
            raise typer.Exit()

        result, paths = await run_audit(
            session,
            formats=fmt_values,
            output_dir=out,
            experimental=enable_experimental_rules,
            audit_ids=audit_ids,
            progress=_progress,
        )

        typer.echo("")
        typer.secho(
            f"Optimization: ${result.total_monthly_savings_usd:,.2f}/mo "
            f"(${result.total_annual_savings_usd:,.2f}/yr) across {len(result.findings)} finding(s).",
            fg=typer.colors.CYAN,
        )
        for f in result.findings:
            typer.echo(f"  [{f.severity.value:6}] {f.rule_id} {f.title} — ${f.estimated_monthly_savings_usd:,.2f}/mo")
        typer.echo("")
        for fmt, p in paths.items():
            typer.secho(f"  wrote {fmt}: {p}", fg=typer.colors.GREEN)

        # Record profile usage (last-audited tenant) if a profile was used.
        if active_profile:
            get_store(settings).touch(
                active_profile,
                tenant_id=result.tenant_id,
                tenant_name=result.tenant_display_name,
            )

    try:
        asyncio.run(_run())
    except AuthError as exc:
        typer.secho(f"Authentication failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command(name="audits")
def list_audits() -> None:
    """List the available audits (ids + categories) for use with `run --audit`."""
    from m365_review.core import audits as audit_catalog

    for category, items in audit_catalog.by_category().items():
        typer.secho(category, fg=typer.colors.CYAN, bold=True)
        for a in items:
            extra = "  [needs extra scope]" if a.scopes else ""
            typer.echo(f"  {a.id:<22} {a.title}{extra}")
        typer.echo("")


@app.command(name="sku-check")
def sku_check(
    device_code: bool = typer.Option(
        None, "--device-code/--interactive",
        help="Use device-code sign-in (headless/container). Auto-enabled inside Docker.",
    ),
) -> None:
    """List SKUs in the tenant and flag any missing from sku_prices.yaml.

    Authenticates read-only, fetches /subscribedSkus, and prints an inventory
    with prices — useful when onboarding a new client tenant.
    """
    import asyncio

    from m365_review.core.auth import AuthError, cli_interactive_auth
    from m365_review.core.fetchers.skus import fetch_subscribed_skus
    from m365_review.core.graph_client import GraphClient
    from m365_review.core.pricing import load_pricing

    prefer_device_code = _resolve_device_code(device_code)

    async def _run() -> None:
        catalog = load_pricing()
        typer.echo("Starting device-code sign-in…" if prefer_device_code
                   else "Starting sign-in (a browser window will open)...")
        session = cli_interactive_auth(prefer_device_code=prefer_device_code)
        typer.secho(
            f"Signed in to tenant {session.tenant_id} as {session.username}", fg=typer.colors.GREEN
        )
        async with GraphClient(session) as gc:
            skus = await fetch_subscribed_skus(gc)

        typer.echo("")
        header = f"{'SKU part number':<32} {'Product':<38} {'Own':>4} {'Used':>4} {'Price':>9}"
        typer.echo(header)
        typer.echo("-" * len(header))
        missing: list[str] = []
        for s in sorted(skus, key=lambda x: x.sku_part_number):
            price = catalog.price(s.sku_part_number)
            price_str = f"${price:,.2f}" if price is not None else "?"
            if price is None:
                missing.append(s.sku_part_number)
            typer.echo(
                f"{s.sku_part_number:<32} {catalog.display_name(s.sku_part_number):<38} "
                f"{s.prepaid_enabled:>4} {s.consumed_units:>4} {price_str:>9}"
            )

        typer.echo("")
        if missing:
            typer.secho(
                f"{len(missing)} SKU(s) missing from sku_prices.yaml: {', '.join(missing)}",
                fg=typer.colors.YELLOW,
            )
            typer.echo("Add them to config/sku_prices.yaml for accurate savings figures.")
        else:
            typer.secho("All tenant SKUs are present in the price map.", fg=typer.colors.GREEN)

    try:
        asyncio.run(_run())
    except AuthError as exc:
        typer.secho(f"Authentication failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# profiles command group
# --------------------------------------------------------------------------- #

profiles_app = typer.Typer(help="Manage saved client profiles (name -> Azure client ID).")
app.add_typer(profiles_app, name="profiles")


@profiles_app.command("list")
def profiles_list() -> None:
    """List saved profiles."""
    from m365_review.core.profiles import get_store

    rows = get_store().list()
    if not rows:
        typer.echo("No saved profiles yet. Add one with `m365-review profiles add`.")
        return
    header = f"{'Name':<24} {'Client ID':<38} {'Last audited':<26} {'Last used':<20}"
    typer.echo(header)
    typer.echo("-" * len(header))
    for p in rows:
        typer.echo(
            f"{p.name:<24} {p.client_id:<38} "
            f"{(p.last_tenant_name or '—'):<26} {(p.last_used_at or '—'):<20}"
        )


@profiles_app.command("add")
def profiles_add(
    name: str = typer.Argument(..., help="Friendly name, e.g. the client/company."),
    client_id: str = typer.Option(..., "--client-id", "-c", help="Azure application (client) ID."),
    domain: str = typer.Option(None, "--domain", help="Optional tenant domain hint."),
    notes: str = typer.Option(None, "--notes", help="Optional notes."),
) -> None:
    """Add or update a saved profile."""
    from m365_review.core.profiles import get_store

    try:
        p = get_store().upsert(name, client_id, tenant_domain=domain, notes=notes)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(f"Saved profile '{p.name}' -> {p.client_id}", fg=typer.colors.GREEN)


@profiles_app.command("remove")
def profiles_remove(
    name: str = typer.Argument(..., help="Profile name to remove."),
) -> None:
    """Remove a saved profile."""
    from m365_review.core.profiles import get_store

    if get_store().delete(name):
        typer.secho(f"Removed profile '{name}'.", fg=typer.colors.GREEN)
    else:
        typer.secho(f"Profile '{name}' not found.", fg=typer.colors.YELLOW)


@profiles_app.command("show")
def profiles_show(
    name: str = typer.Argument(..., help="Profile name to show."),
) -> None:
    """Show one profile's details."""
    from m365_review.core.profiles import get_store

    p = get_store().get(name)
    if p is None:
        typer.secho(f"Profile '{name}' not found.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)
    typer.echo(f"name             : {p.name}")
    typer.echo(f"client_id        : {p.client_id}")
    typer.echo(f"tenant_domain    : {p.tenant_domain or '—'}")
    typer.echo(f"notes            : {p.notes or '—'}")
    typer.echo(f"created_at       : {p.created_at}")
    typer.echo(f"last_used_at     : {p.last_used_at or '—'}")
    typer.echo(f"last_tenant      : {p.last_tenant_name or '—'} ({p.last_tenant_id or '—'})")


if __name__ == "__main__":
    app()
