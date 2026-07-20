"""R12 — Conditional Access blocks legacy authentication.

Passes when an enabled CA policy targets legacy auth clients (exchangeActiveSync /
other) and blocks access. Legacy auth bypasses MFA and is a top attack vector.
"""

from __future__ import annotations

from m365_review.core.models import Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R12"
title = "Conditional Access: block legacy authentication"
experimental = False

_LEGACY = {"exchangeActiveSync", "other"}


def _blocks_legacy(p) -> bool:
    return (
        p.is_enabled
        and "block" in p.grant_controls
        and bool(_LEGACY.intersection(p.client_app_types))
        and (p.targets_all_users or bool(p.include_roles) or bool(p.include_groups))
    )


def evaluate(ctx: RuleContext) -> list[Finding]:
    if not ctx.data.ca_available:
        return []

    if any(_blocks_legacy(p) for p in ctx.data.ca_policies):
        return []

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.high,
            title=title + " — not enforced",
            description=(
                "No enabled Conditional Access policy blocks legacy authentication clients. "
                "Legacy protocols bypass MFA."
            ),
            recommendation=(
                "Create/enable a Conditional Access policy that blocks legacy authentication "
                "(client apps: Exchange ActiveSync + other clients), after confirming no legacy "
                "clients are still in use."
            ),
            affected_users=[],
            estimated_monthly_savings_usd=0.0,
            notes=["Security baseline — no direct cost saving."],
        )
    ]
