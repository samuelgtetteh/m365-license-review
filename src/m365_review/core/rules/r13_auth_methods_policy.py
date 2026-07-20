"""R13 — Authentication methods policy alignment.

Advisory check against a simple baseline: strong methods (Microsoft Authenticator,
FIDO2) should be enabled; weak/phishable methods (SMS, Voice) should generally be
disabled or limited. Flags deviations for review.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R13"
title = "Authentication methods policy alignment"
experimental = False

# Method ids (as returned by authenticationMethodConfigurations).
_STRONG_RECOMMENDED = {"MicrosoftAuthenticator", "Fido2"}
_WEAK_DISCOURAGED = {"Sms", "Voice"}


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.auth_methods_available:
        return []

    states = {m.id: m.state for m in ctx.data.auth_methods}
    issues: list[AffectedUser] = []

    for m in _STRONG_RECOMMENDED:
        if states.get(m, "disabled") != "enabled":
            issues.append(AffectedUser(display_name=m, detail="recommended, but not enabled"))
    for m in _WEAK_DISCOURAGED:
        if states.get(m) == "enabled":
            issues.append(AffectedUser(display_name=m, detail="enabled — phishable, consider disabling/limiting"))

    if not issues:
        return []

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.medium,
            title=title,
            description=(
                f"{len(issues)} authentication-method setting(s) deviate from the recommended "
                "baseline (strong methods enabled, weak methods off)."
            ),
            recommendation=(
                "Enable Microsoft Authenticator / FIDO2 and disable or tightly scope SMS and Voice "
                "in the Authentication methods policy."
            ),
            affected_users=issues,
            estimated_monthly_savings_usd=0.0,
            notes=["Advisory; confirm against the client's requirements before changing."],
        )
    ]
