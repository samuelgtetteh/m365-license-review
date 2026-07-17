"""R10 — Privileged role / admin audit.

Two security findings:
* Admins without MFA registered (high — privileged accounts are the top target).
* Too many Global Administrators (Microsoft recommends a small number, 2-4).
"""

from __future__ import annotations

from m365_review.core.models import AffectedUser, Finding, Severity
from m365_review.core.rules.base import RuleContext

rule_id = "R10"
title = "Privileged role / admin audit"
experimental = False

MAX_GLOBAL_ADMINS = 4


def evaluate(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    # 1. Admins without MFA (from the registration report).
    admins_no_mfa = [
        AffectedUser(
            user_principal_name=u.user_principal_name,
            display_name=u.display_name,
            detail="admin without MFA registered",
        )
        for u in ctx.data.user_registration
        if u.is_admin and not u.is_mfa_registered
    ]
    if admins_no_mfa:
        findings.append(
            Finding(
                rule_id=rule_id,
                severity=Severity.high,
                title="Administrators without MFA",
                description=(
                    f"{len(admins_no_mfa)} privileged account(s) have no registered MFA method. "
                    "Admin accounts are the highest-value target."
                ),
                recommendation="Enforce MFA for all admins immediately.",
                affected_users=admins_no_mfa,
                estimated_monthly_savings_usd=0.0,
                notes=["Security finding — no direct cost saving."],
            )
        )

    # 2. Too many Global Administrators.
    for role in ctx.data.directory_roles:
        if (role.display_name or "").lower() != "global administrator":
            continue
        members = role.members
        if len(members) > MAX_GLOBAL_ADMINS:
            findings.append(
                Finding(
                    rule_id=rule_id,
                    severity=Severity.medium,
                    title=f"Many Global Administrators ({len(members)})",
                    description=(
                        f"{len(members)} accounts hold Global Administrator. Microsoft recommends "
                        f"keeping this to {MAX_GLOBAL_ADMINS} or fewer, using least-privilege roles otherwise."
                    ),
                    recommendation=(
                        "Reduce Global Admins to a small break-glass set; assign narrower roles for "
                        "day-to-day tasks."
                    ),
                    affected_users=[
                        AffectedUser(
                            user_principal_name=m.user_principal_name,
                            display_name=m.display_name,
                            detail="Global Administrator",
                        )
                        for m in members
                    ],
                    estimated_monthly_savings_usd=0.0,
                    notes=["Security finding — no direct cost saving."],
                )
            )

    return findings
