"""R4 — Duplicate / overlapping licenses on the same user.

Some SKUs subsume others (e.g. M365 E5 includes everything in E3). A user holding
both wastes the cost of the redundant one. The overlap table is data-driven
(config/sku_overlaps.yaml), so it grows without code changes.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R4"
title = "Duplicate / overlapping licenses"
experimental = False


def evaluate(ctx: RuleContext) -> list[Finding]:
    skus_by_id = ctx.sku_by_id()
    findings: list[Finding] = []

    # key = redundant part number -> {reason, affected users, savings}
    groups: dict[str, dict] = {}

    for user in ctx.data.users:
        parts = {
            skus_by_id[sid].sku_part_number
            for sid in user.assigned_license_sku_ids
            if sid in skus_by_id
        }
        for overlap in ctx.pricing.find_overlaps(parts):
            price = ctx.pricing.price(overlap.redundant)
            g = groups.setdefault(
                overlap.redundant,
                {"reason": overlap.reason, "users": [], "savings": 0.0, "price_known": True},
            )
            detail = (
                f"has {ctx.pricing.display_name(overlap.sku_a)} + "
                f"{ctx.pricing.display_name(overlap.sku_b)} — "
                f"{ctx.pricing.display_name(overlap.redundant)} is redundant"
            )
            g["users"].append(
                AffectedUser(
                    user_principal_name=user.user_principal_name,
                    display_name=user.display_name,
                    detail=detail,
                    monthly_cost_usd=price,
                )
            )
            if price is None:
                g["price_known"] = False
            else:
                g["savings"] += price

    for redundant, g in groups.items():
        notes = []
        if not g["price_known"]:
            notes.append(
                f"No price for {ctx.pricing.display_name(redundant)} ({redundant}) in "
                f"sku_prices.yaml; savings is a lower bound."
            )
        findings.append(
            Finding(
                rule_id=rule_id,
                severity=Severity.medium,
                title=f"Redundant {ctx.pricing.display_name(redundant)} alongside a superset license",
                description=f"{len(g['users'])} user(s): {g['reason']}",
                recommendation=(
                    f"Remove {ctx.pricing.display_name(redundant)} from these users — the "
                    "overlapping license already provides its features."
                ),
                affected_users=g["users"],
                estimated_monthly_savings_usd=round(g["savings"], 2),
                notes=notes,
            )
        )
    return findings
