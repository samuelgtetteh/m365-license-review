"""R14 — Trusted / named locations review.

Lists named locations marked trusted so the operator can confirm none quietly
bypass security controls. Advisory (a review item, not a pass/fail baseline).
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R14"
title = "Trusted locations review"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.named_locations_available:
        return []

    trusted = [loc for loc in ctx.data.named_locations if loc.is_trusted]
    if not trusted:
        return []

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.medium,
            title=f"{len(trusted)} trusted location(s) configured",
            description=(
                "These named locations are marked trusted, which can exempt them from MFA or "
                "other controls. Confirm each is intended."
            ),
            recommendation=(
                "Review each trusted location with the client. Remove or un-trust any IP range "
                "that shouldn't bypass security controls."
            ),
            affected_users=[
                AffectedUser(display_name=loc.display_name, detail=f"{loc.location_type} · trusted")
                for loc in trusted
            ],
            estimated_monthly_savings_usd=0.0,
            notes=["Review item — no direct cost saving."],
        )
    ]
