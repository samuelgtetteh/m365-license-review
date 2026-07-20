"""Rule registry.

Rules are registered here in evaluation order. v1 ships R1-R3; R4-R7 are added
as they are implemented and gated by their ``experimental`` flag when needed.

``run_all(ctx)`` evaluates every applicable rule and returns the combined,
severity-sorted findings.
"""

from __future__ import annotations

import logging

from m365_review.core.models import Finding
from m365_review.core.rules import (
    r1_disabled_licensed,
    r2_inactive_licensed,
    r3_unassigned_licenses,
    r4_duplicate_skus,
    r7_licensed_guests,
    r8_expiring_subscriptions,
    r9_users_without_mfa,
    r10_admin_audit,
)
from m365_review.core.rules.base import Rule, RuleContext

logger = logging.getLogger(__name__)

# Ordered list of registered rule modules. Each satisfies the Rule protocol.
REGISTERED: list[Rule] = [
    r1_disabled_licensed,       # type: ignore[list-item]
    r2_inactive_licensed,       # type: ignore[list-item]
    r3_unassigned_licenses,     # type: ignore[list-item]
    r4_duplicate_skus,          # type: ignore[list-item]
    r7_licensed_guests,         # type: ignore[list-item]
    r8_expiring_subscriptions,  # type: ignore[list-item]
    r9_users_without_mfa,       # type: ignore[list-item]
    r10_admin_audit,            # type: ignore[list-item]
    # R5/R6 (E5 under-use, shared-mailbox size) appended here when built.
]


def applicable_rules(experimental_enabled: bool) -> list[Rule]:
    """Rules that should run given the experimental toggle."""
    return [r for r in REGISTERED if experimental_enabled or not getattr(r, "experimental", False)]


def run_rules(ctx: RuleContext, rules: list[Rule]) -> list[Finding]:
    """Evaluate a specific set of rules; return findings sorted by severity."""
    findings: list[Finding] = []
    for rule in rules:
        try:
            produced = rule.evaluate(ctx)
            logger.info("Rule %s produced %d finding(s).", rule.rule_id, len(produced))
            findings.extend(produced)
        except Exception:  # noqa: BLE001 — one bad rule must not sink the whole audit
            logger.exception("Rule %s failed; skipping.", getattr(rule, "rule_id", "?"))
    findings.sort(key=lambda f: (-f.severity.rank, f.rule_id))
    return findings


def run_all(ctx: RuleContext) -> list[Finding]:
    """Evaluate all applicable rules; return findings sorted by severity (high first)."""
    return run_rules(ctx, applicable_rules(ctx.experimental_enabled))
