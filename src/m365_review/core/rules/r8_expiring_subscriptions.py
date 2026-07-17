"""R8 — Subscriptions expiring soon (or already expired).

Surfaces renewal/cancellation decisions in the optimization summary. The full
expiration list is also exported as its own report section; this rule just flags
the time-sensitive ones so they aren't missed.
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R8"
title = "Subscriptions expiring soon"
experimental = False

SOON_DAYS = 30


def evaluate(ctx: RuleContext) -> list[Finding]:
    subs = ctx.data.subscriptions
    if not subs:
        return []

    flagged = []  # (subscription, label)
    for s in subs:
        if s.is_expired(ctx.now):
            flagged.append((s, "expired"))
        elif s.is_expiring_within(ctx.now, SOON_DAYS):
            days = s.days_until_expiry(ctx.now)
            flagged.append((s, f"expires in {days} day(s)"))

    if not flagged:
        return []

    any_expired = any(label == "expired" for _, label in flagged)
    affected = [
        AffectedUser(
            display_name=s.display_name or s.sku_part_number,
            user_principal_name=None,
            detail=(
                f"{label}"
                + (f" on {s.next_lifecycle_datetime.date().isoformat()}" if s.next_lifecycle_datetime else "")
                + f"; {s.total_licenses} license(s)"
                + (" [trial]" if s.is_trial else "")
            ),
        )
        for s, label in flagged
    ]

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.high if any_expired else Severity.medium,
            title=title,
            description=(
                f"{len(flagged)} subscription(s) are expired or expiring within {SOON_DAYS} days. "
                "Review each for renewal, right-sizing, or cancellation before the renewal date."
            ),
            recommendation=(
                "Confirm whether each subscription should renew, be resized, or be cancelled. "
                "Acting before the renewal date avoids surprise charges or unexpected loss of service."
            ),
            affected_users=affected,
            estimated_monthly_savings_usd=0.0,  # decision-driven, not a direct saving
            notes=["See the 'Subscription expirations' section for the full list and dates."],
        )
    ]
