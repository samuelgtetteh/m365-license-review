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
)
from m365_review.core.rules.base import Rule, RuleContext

logger = logging.getLogger(__name__)

# Ordered list of registered rule modules. Each satisfies the Rule protocol.
REGISTERED: list[Rule] = [
    r1_disabled_licensed,   # type: ignore[list-item]
    r2_inactive_licensed,   # type: ignore[list-item]
    r3_unassigned_licenses,  # type: ignore[list-item]
    # R4-R7 appended here as they are built.
]


def applicable_rules(experimental_enabled: bool) -> list[Rule]:
    """Rules that should run given the experimental toggle."""
    return [r for r in REGISTERED if experimental_enabled or not getattr(r, "experimental", False)]


def run_all(ctx: RuleContext) -> list[Finding]:
    """Evaluate all applicable rules; return findings sorted by severity (high first)."""
    findings: list[Finding] = []
    for rule in applicable_rules(ctx.experimental_enabled):
        try:
            produced = rule.evaluate(ctx)
            logger.info("Rule %s produced %d finding(s).", rule.rule_id, len(produced))
            findings.extend(produced)
        except Exception:  # noqa: BLE001 — one bad rule must not sink the whole audit
            logger.exception("Rule %s failed; skipping.", getattr(rule, "rule_id", "?"))
    findings.sort(key=lambda f: (-f.severity.rank, f.rule_id))
    return findings
