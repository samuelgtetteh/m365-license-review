"""R1 — Licenses assigned to disabled user accounts.

Any user with ``accountEnabled == false`` that still holds licenses is pure
waste: the tenant pays for seats no one can use.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R1"
title = "Licenses assigned to disabled users"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    affected: list[AffectedUser] = []
    total_savings = 0.0
    any_price_missing = False

    for user in ctx.data.users:
        if user.account_enabled or not user.is_licensed:
            continue
        cost, all_known = ctx.user_license_monthly_cost(user.assigned_license_sku_ids)
        if not all_known:
            any_price_missing = True
        names = ctx.license_names_for(user.assigned_license_sku_ids)
        affected.append(
            AffectedUser(
                user_principal_name=user.user_principal_name,
                display_name=user.display_name,
                detail="; ".join(names),
                monthly_cost_usd=cost,
            )
        )
        total_savings += cost

    if not affected:
        return []

    notes = []
    if any_price_missing:
        notes.append("Some assigned SKUs are missing from the price map; savings is a lower bound.")

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.high,
            title=title,
            description=(
                f"{len(affected)} disabled account(s) still hold licenses. Disabled users "
                f"cannot sign in, so these licenses are unused."
            ),
            recommendation=(
                "Remove licenses from the disabled account(s), or delete the accounts if they "
                "are no longer needed."
            ),
            affected_users=affected,
            estimated_monthly_savings_usd=round(total_savings, 2),
            notes=notes,
        )
    ]
