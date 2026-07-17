"""Audit orchestration — the seam between data, rules, and reports.

Two layers:

* :func:`fetch_tenant_data` — live Graph I/O (needs a ``TenantSession``).
* :func:`build_result` — **pure**: ``TenantData`` -> ``AuditResult``. No I/O, no
  clock read (``now`` is injected), so notebooks and tests call it directly on
  fixtures for fully reproducible output.

:func:`run_audit` wires them together and writes the report files.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from m365_review.core.auth import TenantSession
from m365_review.core.fetchers.organization import fetch_organization
from m365_review.core.fetchers.skus import fetch_subscribed_skus
from m365_review.core.fetchers.subscriptions import fetch_subscriptions
from m365_review.core.fetchers.users import fetch_users
from m365_review.core.graph_client import GraphClient
from m365_review.core.models import AuditResult, SkuInventoryRow, TenantData
from m365_review.core.pricing import PricingCatalog, load_pricing
from m365_review.core.rules import run_all
from m365_review.core.rules.base import RuleContext

logger = logging.getLogger(__name__)

# Progress callback: (step_label, fraction 0..1) -> awaitable/None
ProgressFn = Callable[[str, float], Awaitable[None] | None]


async def _emit(progress: ProgressFn | None, label: str, fraction: float) -> None:
    if progress is None:
        return
    result = progress(label, fraction)
    if hasattr(result, "__await__"):
        await result  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Live fetch
# --------------------------------------------------------------------------- #

async def fetch_tenant_data(
    session: TenantSession,
    *,
    experimental: bool = False,
    progress: ProgressFn | None = None,
) -> TenantData:
    """Fetch everything the rules need from the tenant (read-only)."""
    async with GraphClient(session) as gc:
        await _emit(progress, "Reading tenant identity", 0.1)
        org = await fetch_organization(gc)

        await _emit(progress, "Reading subscribed licenses", 0.3)
        skus = await fetch_subscribed_skus(gc)

        await _emit(progress, "Reading subscription expiration dates", 0.45)
        subscriptions, subs_available = await fetch_subscriptions(gc)

        await _emit(progress, "Reading users and license assignments", 0.6)
        users_result = await fetch_users(gc)

        # Usage-report fetchers (for experimental rules) land with R5/R6/R7.
        await _emit(progress, "Compiling tenant data", 0.8)

    if session.tenant_display_name is None:
        session.tenant_display_name = org.display_name

    return TenantData(
        organization=org,
        tenant_id=session.tenant_id,
        skus=skus,
        subscriptions=subscriptions,
        users=users_result.users,
        sign_in_activity_available=users_result.sign_in_activity_available,
        subscriptions_available=subs_available,
    )


# --------------------------------------------------------------------------- #
# Pure result builder (reproducible)
# --------------------------------------------------------------------------- #

def build_result(
    data: TenantData,
    *,
    pricing: PricingCatalog | None = None,
    experimental: bool = False,
    now: datetime | None = None,
) -> AuditResult:
    """Run the rules and assemble the AuditResult. Pure — safe for tests/notebooks."""
    pricing = pricing or load_pricing()
    now = now or datetime.now(timezone.utc)

    active_skus = [s for s in data.skus if s.is_active]
    inactive_skus = [s for s in data.skus if not s.is_active]
    active_data = data.model_copy(update={"skus": active_skus})

    # Rules run against the FULL SKU set so that license NAMES resolve for every
    # user — a disabled user may hold a license from an inactive/expired
    # subscription, and it must still show a friendly name, not a raw GUID.
    # Scope-limiting (excluding inactive/free SKUs from counts) is handled inside
    # the individual rules and in the totals/inventory below.
    ctx = RuleContext(data=data, pricing=pricing, now=now, experimental_enabled=experimental)
    findings = run_all(ctx)
    # Inventory and totals still reflect active subscriptions only.
    inventory = _build_inventory(active_data, pricing)
    caveats = _build_caveats(active_data, pricing, inactive_skus=inactive_skus)

    # Free/self-service SKUs (10,000+ default quota) are excluded from the
    # purchased/assigned headline so they don't drown out real paid licensing.
    paid_skus = [s for s in active_skus if not s.is_unlimited]

    # GUID -> friendly name, so raw license references render human-readably
    # (built from ALL skus so even inactive-license GUIDs resolve in raw data).
    sku_id_to_name = {
        s.sku_id: pricing.display_name(s.sku_part_number) for s in data.skus
    }

    # Fill friendly names on subscriptions (sorted by soonest expiry first).
    for sub in data.subscriptions:
        sub.display_name = pricing.display_name(sub.sku_part_number)
    subscriptions = sorted(
        data.subscriptions,
        key=lambda s: (s.next_lifecycle_datetime is None, s.next_lifecycle_datetime or now),
    )

    return AuditResult(
        tenant_display_name=data.organization.display_name or data.tenant_id,
        tenant_id=data.tenant_id,
        generated_at=now,
        findings=findings,
        inventory=inventory,
        # "Purchased" = usable seats (active + in-grace), not raw enabled.
        total_purchased=sum(s.usable for s in paid_skus),
        total_assigned=sum(s.consumed_units for s in paid_skus),
        caveats=caveats,
        subscriptions=subscriptions,
        subscriptions_available=data.subscriptions_available,
        sku_id_to_name=sku_id_to_name,
        tenant_data=data,
    )


def _build_inventory(data: TenantData, pricing: PricingCatalog) -> list[SkuInventoryRow]:
    rows: list[SkuInventoryRow] = []
    for sku in sorted(data.skus, key=lambda s: s.sku_part_number):
        price = pricing.price(sku.sku_part_number)
        rows.append(
            SkuInventoryRow(
                sku_part_number=sku.sku_part_number,
                display_name=pricing.display_name(sku.sku_part_number),
                purchased=sku.usable,
                assigned=sku.consumed_units,
                slack=sku.slack,
                unit_price_usd=price,
                price_known=price is not None,
                is_unlimited=sku.is_unlimited,
            )
        )
    return rows


def _build_caveats(
    data: TenantData,
    pricing: PricingCatalog,
    *,
    inactive_skus: list | None = None,
) -> list[str]:
    caveats: list[str] = []
    if inactive_skus:
        caveats.append(
            "Inactive / disabled subscriptions were excluded from this report: "
            + ", ".join(
                f"{pricing.display_name(s.sku_part_number)} ({(s.capability_status or 'inactive')})"
                for s in inactive_skus
            )
            + "."
        )
    free = [s.sku_part_number for s in data.skus if s.is_unlimited]
    if free:
        caveats.append(
            "Free / self-service SKUs (with a 10,000+ default quota) are excluded from the "
            "purchased/assigned totals and the unused-license check: "
            + ", ".join(pricing.display_name(s) for s in free)
            + "."
        )
    if not data.subscriptions_available:
        caveats.append(
            "Subscription expiration data was unavailable (the /directory/subscriptions "
            "endpoint did not return data for this tenant), so the expirations section is empty."
        )
    if not data.sign_in_activity_available:
        caveats.append(
            "Sign-in activity was unavailable (tenant lacks Azure AD P1), so inactivity-based "
            "findings could not be computed and are shown for manual review only."
        )
    # Only flag PAID SKUs missing a price (free ones are excluded by design).
    missing = pricing.missing_prices(
        [s.sku_part_number for s in data.skus if not s.is_unlimited]
    )
    if missing:
        pretty = ", ".join(f"{pricing.display_name(s)} ({s})" for s in missing)
        caveats.append(
            "These paid products are not in the price map, so their savings are not estimated: "
            + pretty
            + ". Add them to config/sku_prices.yaml (keyed by the part number in parentheses)."
        )
    if data.report_names_concealed:
        caveats.append(
            "Usage-report user names are anonymized in this tenant ('concealed names' is on). "
            "Per-user usage findings cannot map back to individuals until it is turned off."
        )
    caveats.append(
        "Usage report data (where used) can lag 24-72 hours behind real activity."
    )
    caveats.append(f"License prices sourced from: {pricing.source}.")
    return caveats


# --------------------------------------------------------------------------- #
# End-to-end
# --------------------------------------------------------------------------- #

async def run_audit(
    session: TenantSession,
    *,
    formats: list[str],
    output_dir: Path,
    experimental: bool = False,
    progress: ProgressFn | None = None,
) -> tuple[AuditResult, dict[str, Path]]:
    """Fetch -> rules -> AuditResult -> report files. Returns (result, {fmt: path})."""
    from m365_review.core.report import write_reports  # local import avoids cycle

    pricing = load_pricing()
    data = await fetch_tenant_data(session, experimental=experimental, progress=progress)

    await _emit(progress, "Analyzing license optimization", 0.85)
    result = build_result(data, pricing=pricing, experimental=experimental)

    await _emit(progress, "Writing report(s)", 0.95)
    paths = write_reports(result, output_dir=output_dir, formats=formats)

    await _emit(progress, "Done", 1.0)
    return result, paths
