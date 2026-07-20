"""R17 — Verified / accepted domains review.

Lists the tenant's domains for review and flags any that are unverified (they
shouldn't linger) or federated (worth confirming the federation is expected).
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R17"
title = "Verified / accepted domains"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.domains_available or not ctx.data.domains:
        return []

    domains = ctx.data.domains
    unverified = [d for d in domains if not d.is_verified]

    affected = []
    for d in domains:
        tags = []
        if d.is_default:
            tags.append("default")
        if not d.is_verified:
            tags.append("UNVERIFIED")
        if (d.authentication_type or "").lower() == "federated":
            tags.append("federated")
        affected.append(
            AffectedUser(display_name=d.id, detail=", ".join(tags) if tags else "verified")
        )

    severity = Severity.medium if unverified else Severity.info
    desc = f"{len(domains)} domain(s) configured on the tenant."
    if unverified:
        desc += f" {len(unverified)} are unverified."

    return [
        Finding(
            rule_id=rule_id,
            severity=severity,
            title=title,
            description=desc,
            recommendation=(
                "Review each domain with the client. Remove unverified/unused domains, and "
                "confirm any federated domains are expected."
            ),
            affected_users=affected,
            estimated_monthly_savings_usd=0.0,
            notes=["Review item — no direct cost saving."],
        )
    ]
