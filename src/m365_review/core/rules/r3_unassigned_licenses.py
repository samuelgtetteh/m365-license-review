"""R3 — Unassigned purchased licenses (slack).

For each SKU, purchased minus assigned is slack the tenant pays for but does not
use. A small buffer (1-2 seats) is normal; larger slack is a real saving at
renewal. One finding per SKU that has slack, so each shows its own dollar value.
"""

from __future__ import annotations

from m365_review.core.models import Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R3"
title = "Unassigned purchased licenses"
experimental = False

SMALL_BUFFER = 2          # <= this many spare seats is treated as normal buffer
HIGH_SLACK_RATIO = 0.25   # > 25% of purchased unused -> high
MED_SLACK_RATIO = 0.10    # > 10% -> medium


def _severity(slack: int, purchased: int) -> Severity:
    if slack <= SMALL_BUFFER:
        return Severity.info
    ratio = slack / purchased if purchased else 0
    if ratio > HIGH_SLACK_RATIO:
        return Severity.high
    if ratio > MED_SLACK_RATIO:
        return Severity.medium
    return Severity.low


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for sku in ctx.data.skus:
        # Skip inactive/disabled subscriptions (excluded from the report), and
        # free/self-service SKUs whose huge phantom "slack" isn't reclaimable.
        if not sku.is_active or sku.is_unlimited:
            continue
        slack = sku.slack
        if slack <= 0:
            continue

        price = ctx.pricing.price(sku.sku_part_number)
        name = ctx.pricing.display_name(sku.sku_part_number)
        severity = _severity(slack, sku.prepaid_enabled)

        savings = round(price * slack, 2) if price is not None else 0.0
        notes = []
        if price is None:
            notes.append(
                f"No price for {name} ({sku.sku_part_number}) in sku_prices.yaml; "
                f"savings not estimated."
            )

        findings.append(
            Finding(
                rule_id=rule_id,
                severity=severity,
                title=f"{name}: {slack} unused seat(s)",
                description=(
                    f"{name}: {sku.prepaid_enabled} purchased, "
                    f"{sku.consumed_units} assigned, {slack} unused."
                ),
                recommendation=(
                    "Reduce the license count at the next renewal, or reassign spare seats to "
                    "unlicensed users. A small buffer for onboarding is normal."
                ),
                affected_users=[],
                estimated_monthly_savings_usd=savings,
                notes=notes,
            )
        )
    return findings
