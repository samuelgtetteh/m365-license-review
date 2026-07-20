"""R16 — Legacy per-user MFA state.

Reports accounts whose legacy per-user MFA state is not "enforced". This is
informational: if the tenant relies on Conditional Access for MFA, a "disabled"
per-user state is expected — the value is visibility + catching mixed setups.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R16"
title = "Legacy per-user MFA state"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.per_user_mfa_available or not ctx.data.per_user_mfa:
        return []

    not_enforced = [r for r in ctx.data.per_user_mfa if r.state != "enforced"]
    if not not_enforced:
        return []

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.info,
            title=title,
            description=(
                f"{len(not_enforced)} of {len(ctx.data.per_user_mfa)} account(s) are not in the "
                "'enforced' per-user MFA state. This is expected if you enforce MFA via Conditional "
                "Access instead of per-user MFA."
            ),
            recommendation=(
                "Confirm MFA is enforced via Conditional Access (preferred). If you rely on per-user "
                "MFA, move these accounts to 'enforced'."
            ),
            affected_users=[
                AffectedUser(
                    user_principal_name=r.user_principal_name,
                    display_name=r.display_name,
                    detail=f"per-user MFA: {r.state}",
                )
                for r in not_enforced
            ],
            estimated_monthly_savings_usd=0.0,
            notes=["Informational — cross-check with the Conditional Access MFA policy."],
        )
    ]
