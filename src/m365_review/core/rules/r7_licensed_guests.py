"""R7 — Licensed guest users.

Guests normally consume their home tenant's licenses; a license assigned to a
guest in this tenant is usually unnecessary spend.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R7"
title = "Licensed guest users"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    affected: list[AffectedUser] = []
    total = 0.0
    any_missing = False
    for user in ctx.data.users:
        if (user.user_type or "").lower() != "guest" or not user.is_licensed:
            continue
        cost, all_known = ctx.user_license_monthly_cost(user.assigned_license_sku_ids)
        if not all_known:
            any_missing = True
        affected.append(
            AffectedUser(
                user_principal_name=user.user_principal_name,
                display_name=user.display_name,
                detail="; ".join(ctx.license_names_for(user.assigned_license_sku_ids)),
                monthly_cost_usd=cost,
            )
        )
        total += cost

    if not affected:
        return []

    notes = ["Some SKUs missing from the price map; savings is a lower bound."] if any_missing else []
    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.medium,
            title=title,
            description=f"{len(affected)} guest account(s) hold licenses in this tenant.",
            recommendation=(
                "Confirm the guest genuinely needs a license here; guests normally use their "
                "home tenant's licenses. Remove if not required."
            ),
            affected_users=affected,
            estimated_monthly_savings_usd=round(total, 2),
            notes=notes,
        )
    ]
