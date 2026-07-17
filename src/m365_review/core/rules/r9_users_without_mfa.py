"""R9 — Users without MFA registered.

A security-hygiene finding (not a cost saving): member accounts that have not
registered any MFA method are a common attack surface. Admins are covered by R10.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R9"
title = "Users without MFA registered"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    reg = ctx.data.user_registration
    if not reg:
        return []  # data unavailable / not returned

    affected = [
        AffectedUser(
            user_principal_name=u.user_principal_name,
            display_name=u.display_name,
            detail="no MFA method registered",
        )
        for u in reg
        if not u.is_mfa_registered and not u.is_admin and (u.user_type or "member") == "member"
    ]
    if not affected:
        return []

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.high,
            title=title,
            description=(
                f"{len(affected)} member account(s) have no registered MFA method — a significant "
                "account-takeover risk."
            ),
            recommendation=(
                "Require MFA registration (e.g. via a Conditional Access registration campaign or "
                "security defaults) and follow up with these users."
            ),
            affected_users=affected,
            estimated_monthly_savings_usd=0.0,
            notes=["Security finding — no direct cost saving."],
        )
    ]
