"""R11 — Conditional Access requires MFA for all users.

Passes when at least one enabled CA policy targets all users + all apps and grants
MFA. Fails otherwise (a core security baseline).
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R11"
title = "Conditional Access: require MFA for all users"
experimental = False


def _grants_mfa_all(p) -> bool:
    return (
        p.is_enabled
        and p.targets_all_users
        and ("All" in p.include_applications)
        and ("mfa" in p.grant_controls)
    )


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.ca_available:
        return []  # scope/endpoint unavailable — skipped (noted in caveats)

    matching = [p for p in ctx.data.ca_policies if _grants_mfa_all(p)]
    if matching:
        return []  # baseline satisfied

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.high,
            title=title + " — not enforced",
            description=(
                "No enabled Conditional Access policy requires MFA for all users and all apps. "
                "Users can sign in without MFA."
            ),
            recommendation=(
                "Create/enable a Conditional Access policy that requires MFA for all users "
                "(with a break-glass admin exclusion)."
            ),
            affected_users=[],
            estimated_monthly_savings_usd=0.0,
            notes=["Security baseline — no direct cost saving."],
        )
    ]
