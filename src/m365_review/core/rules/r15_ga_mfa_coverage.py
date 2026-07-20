"""R15 — Global-admin MFA coverage (Conditional Access).

Passes when Global Administrators are covered by an enabled CA MFA policy — either
one targeting all users, or one targeting the Global Administrator role directly.
"""

from __future__ import annotations

from m365_review.core.models import GLOBAL_ADMIN_ROLE_TEMPLATE_ID, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R15"
title = "Global-admin MFA coverage"
experimental = False


def _covers_global_admins(p) -> bool:
    if not (p.is_enabled and "mfa" in p.grant_controls):
        return False
    return p.targets_all_users or p.targets_role(GLOBAL_ADMIN_ROLE_TEMPLATE_ID)


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.ca_available:
        return []

    if any(_covers_global_admins(p) for p in ctx.data.ca_policies):
        return []

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.high,
            title=title + " — not enforced",
            description=(
                "No enabled Conditional Access policy requires MFA for the Global Administrator "
                "role (or all users). Privileged accounts may sign in without MFA."
            ),
            recommendation=(
                "Enable a Conditional Access policy requiring MFA for the Global Administrator "
                "role (keep one break-glass account excluded)."
            ),
            affected_users=[],
            estimated_monthly_savings_usd=0.0,
            notes=["Security baseline — no direct cost saving."],
        )
    ]
