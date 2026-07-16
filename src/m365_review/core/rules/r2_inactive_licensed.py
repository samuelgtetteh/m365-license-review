"""R2 — Licenses assigned to users with no sign-in in 90 days.

Enabled, licensed users who have not signed in for 90+ days are strong
candidates for license reclamation. Users created in the last 30 days are
excluded (they may legitimately not have signed in yet).

Degradation: ``signInActivity`` needs Azure AD P1+. When it is unavailable we
cannot measure activity, so the rule emits an INFO finding listing long-lived
licensed accounts as "unable to verify" and flags the limitation, rather than
guessing.
"""

from __future__ import annotations

from datetime import timedelta

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R2"
title = "Licenses assigned to users inactive for 90+ days"
experimental = False

INACTIVE_DAYS = 90
GRACE_DAYS = 30


def evaluate(ctx: RuleContext) -> list[Finding]:
    cutoff = ctx.now - timedelta(days=INACTIVE_DAYS)
    grace_cutoff = ctx.now - timedelta(days=GRACE_DAYS)

    if not ctx.data.sign_in_activity_available:
        return _degraded(ctx, grace_cutoff)

    affected: list[AffectedUser] = []
    total_savings = 0.0
    any_price_missing = False

    for user in ctx.data.users:
        if not user.account_enabled or not user.is_licensed:
            continue
        # Skip recently created accounts.
        if user.created_datetime and user.created_datetime > grace_cutoff:
            continue

        last = user.effective_last_sign_in
        is_inactive = last is None or last < cutoff
        if not is_inactive:
            continue

        cost, all_known = ctx.user_license_monthly_cost(user.assigned_license_sku_ids)
        if not all_known:
            any_price_missing = True
        detail = "never signed in" if last is None else f"last sign-in {last.date().isoformat()}"
        affected.append(
            AffectedUser(
                user_principal_name=user.user_principal_name,
                display_name=user.display_name,
                detail=detail,
                monthly_cost_usd=cost,
            )
        )
        total_savings += cost

    if not affected:
        return []

    notes = []
    if any_price_missing:
        notes.append("Some assigned SKUs are missing from the price map; savings is a lower bound.")

    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.medium,
            title=title,
            description=(
                f"{len(affected)} enabled, licensed user(s) have not signed in for "
                f"{INACTIVE_DAYS}+ days (accounts created in the last {GRACE_DAYS} days excluded)."
            ),
            recommendation=(
                "Confirm each user is still active. If not, remove the license or disable the "
                "account. Verify before acting — some roles sign in rarely (e.g. break-glass)."
            ),
            affected_users=affected,
            estimated_monthly_savings_usd=round(total_savings, 2),
            notes=notes,
        )
    ]


def _degraded(ctx: RuleContext, grace_cutoff) -> list[Finding]:
    """No sign-in data: list long-lived licensed accounts as unverifiable."""
    candidates: list[AffectedUser] = []
    for user in ctx.data.users:
        if not user.account_enabled or not user.is_licensed:
            continue
        if user.created_datetime and user.created_datetime > grace_cutoff:
            continue
        cost, _ = ctx.user_license_monthly_cost(user.assigned_license_sku_ids)
        candidates.append(
            AffectedUser(
                user_principal_name=user.user_principal_name,
                display_name=user.display_name,
                detail="sign-in activity unavailable (tenant lacks Azure AD P1)",
                monthly_cost_usd=cost,
            )
        )
    if not candidates:
        return []
    return [
        Finding(
            rule_id=rule_id,
            severity=Severity.info,
            title=f"{title} — activity data unavailable",
            description=(
                "This tenant does not expose sign-in activity (Azure AD P1+ required), so "
                f"inactivity could not be measured. {len(candidates)} enabled, licensed account(s) "
                "are listed for manual review."
            ),
            recommendation=(
                "Enable Azure AD P1 (or check sign-in logs manually) to identify truly inactive "
                "users, then reclaim their licenses."
            ),
            affected_users=candidates,
            estimated_monthly_savings_usd=0.0,
            notes=["Savings not estimated because activity could not be verified."],
        )
    ]
