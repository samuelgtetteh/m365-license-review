"""Tests for the rules engine against the synthetic fixtures.

The fixtures are designed so each v1 rule has a known, checkable outcome
(see tests/fixtures/*.json). All dates are evaluated against FIXED_NOW.
"""

from __future__ import annotations

import dataclasses

from m365_review.core.models import Severity
from m365_review.core.rules import run_all
from m365_review.core.rules.base import RuleContext
from m365_review.core.rules import (
    r1_disabled_licensed,
    r2_inactive_licensed,
    r3_unassigned_licenses,
)


def _ctx(tenant_data, pricing, now, experimental=False):
    return RuleContext(data=tenant_data, pricing=pricing, now=now, experimental_enabled=experimental)


# --- R1 ---------------------------------------------------------------------

def test_r1_flags_only_disabled_licensed_user(tenant_data, pricing, now):
    findings = r1_disabled_licensed.evaluate(_ctx(tenant_data, pricing, now))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.high
    upns = {u.user_principal_name for u in f.affected_users}
    assert upns == {"bob@contoso.com"}          # Bob is disabled + E5
    assert f.estimated_monthly_savings_usd == 57.0  # E5 list price


# --- R2 ---------------------------------------------------------------------

def test_r2_flags_inactive_excludes_new_and_active(tenant_data, pricing, now):
    findings = r2_inactive_licensed.evaluate(_ctx(tenant_data, pricing, now))
    assert len(findings) == 1
    upns = {u.user_principal_name for u in findings[0].affected_users}
    assert upns == {"carol@contoso.com", "dave@contoso.com"}
    assert "alice@contoso.com" not in upns       # active
    assert "eve@contoso.com" not in upns          # created < 30 days ago (grace)
    assert findings[0].estimated_monthly_savings_usd == 36.0 + 57.0


def test_r2_degrades_when_sign_in_unavailable(tenant_data, pricing, now):
    degraded = dataclasses.replace  # noqa: F841 (readability)
    data = tenant_data.model_copy(update={"sign_in_activity_available": False})
    findings = r2_inactive_licensed.evaluate(_ctx(data, pricing, now))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.info               # cannot verify -> info, no savings
    assert f.estimated_monthly_savings_usd == 0.0


# --- R3 ---------------------------------------------------------------------

def test_r3_slack_and_severity(tenant_data, pricing, now):
    findings = r3_unassigned_licenses.evaluate(_ctx(tenant_data, pricing, now))
    by_title = {f.title: f for f in findings}
    # E5: 10 purchased, 3 used -> 7 slack, ratio 0.7 -> high, $57*7
    e5 = next(f for f in findings if "E5" in f.title)
    assert e5.severity == Severity.high
    assert e5.estimated_monthly_savings_usd == 57.0 * 7
    # E3: 25 purchased, 20 used -> 5 slack, ratio 0.2 -> medium
    e3 = next(f for f in findings if "E3" in f.title)
    assert e3.severity == Severity.medium
    # EXCHANGESTANDARD has no slack -> not present
    assert not any("Exchange" in t for t in by_title)


def test_r3_missing_price_reports_zero_savings(tenant_data, pricing, now):
    findings = r3_unassigned_licenses.evaluate(_ctx(tenant_data, pricing, now))
    # Titles/descriptions use the friendly name; the raw part number lives only in
    # the operator-facing "add to price map" note.
    unknown = next(f for f in findings if any("SOME_NEW_ADDON" in n for n in f.notes))
    assert unknown.estimated_monthly_savings_usd == 0.0
    assert "Some New Addon" in unknown.title


# --- registry ---------------------------------------------------------------

def test_run_all_sorts_by_severity_and_totals(tenant_data, pricing, now):
    findings = run_all(_ctx(tenant_data, pricing, now))
    ranks = [f.severity.rank for f in findings]
    assert ranks == sorted(ranks, reverse=True)   # high first
    total = round(sum(f.estimated_monthly_savings_usd for f in findings), 2)
    # R1 57 + R2 93 + R3 (399+180) + R7 guest (Frank E3 36) = 765; R8/R9/R10 add $0.
    assert total == 765.0


def test_free_unlimited_skus_excluded_from_totals_and_r3(tenant_data, pricing, now):
    from m365_review.core.engine import build_result
    from m365_review.core.models import SubscribedSku

    # Add a free/self-service SKU with a 50,000 default quota.
    data = tenant_data.model_copy(deep=True)
    data.skus.append(
        SubscribedSku(
            sku_id="sku-free", sku_part_number="RIGHTSMANAGEMENT_ADHOC",
            prepaid_enabled=50000, consumed_units=0,
        )
    )
    paid_purchased = sum(s.prepaid_enabled for s in data.skus if not s.is_unlimited)
    result = build_result(data, pricing=pricing, now=now)

    # The 50,000 free seats must NOT inflate the purchased total.
    assert result.total_purchased == paid_purchased
    assert result.total_purchased < 1000
    # R3 must not raise an "unused seats" finding for the free SKU.
    assert not any(
        f.rule_id == "R3" and "RIGHTSMANAGEMENT_ADHOC" in "".join(f.notes)
        for f in result.findings
    )
    # It is still present in the inventory, flagged as unlimited.
    free_rows = [r for r in result.inventory if r.is_unlimited]
    assert any(r.sku_part_number == "RIGHTSMANAGEMENT_ADHOC" for r in free_rows)


def test_inactive_skus_excluded_and_grace_counted(tenant_data, pricing, now):
    from m365_review.core.engine import build_result
    from m365_review.core.models import SubscribedSku

    data = tenant_data.model_copy(deep=True)
    # A suspended (disabled) subscription with lingering assignments -> excluded.
    data.skus.append(
        SubscribedSku(
            sku_id="sku-dead", sku_part_number="ENTERPRISEPACK",
            prepaid_enabled=0, consumed_units=4, capability_status="Suspended",
        )
    )
    # An expired-but-in-grace subscription -> counted via `warning` (usable).
    data.skus.append(
        SubscribedSku(
            sku_id="sku-grace", sku_part_number="EXCHANGEENTERPRISE",
            prepaid_enabled=0, prepaid_warning=5, consumed_units=5, capability_status="Warning",
        )
    )
    result = build_result(data, pricing=pricing, now=now)

    parts = {r.sku_part_number for r in result.inventory}
    assert "ENTERPRISEPACK" not in parts          # suspended -> excluded from the list
    assert "EXCHANGEENTERPRISE" in parts          # grace -> kept
    grace = next(r for r in result.inventory if r.sku_part_number == "EXCHANGEENTERPRISE")
    assert grace.purchased == 5                    # counted via warning/grace seats
    assert grace.slack == 0                        # 5 usable - 5 assigned
    assert any("Inactive" in c for c in result.caveats)


def test_r4_flags_overlapping_licenses(tenant_data, pricing, now):
    from m365_review.core.rules import r4_duplicate_skus

    # Give a user BOTH E5 and E3 (E5 supersedes E3 per sku_overlaps.yaml).
    data = tenant_data.model_copy(deep=True)
    e3_id = "sku-e3-0000-0000-0000-000000000001"
    e5_id = "sku-e5-0000-0000-0000-000000000002"
    data.users[0].assigned_license_sku_ids = [e5_id, e3_id]

    findings = r4_duplicate_skus.evaluate(_ctx(data, pricing, now))
    assert len(findings) == 1
    f = findings[0]
    assert "Microsoft 365 E3" in f.title           # E3 is the redundant one
    assert f.estimated_monthly_savings_usd == 36.0  # E3 list price recovered


def test_r7_flags_licensed_guest(tenant_data, pricing, now):
    from m365_review.core.rules import r7_licensed_guests

    findings = r7_licensed_guests.evaluate(_ctx(tenant_data, pricing, now))
    assert len(findings) == 1
    upns = {u.user_principal_name for u in findings[0].affected_users}
    assert any("frank" in (u or "") for u in upns)   # Frank is a licensed guest
    assert findings[0].estimated_monthly_savings_usd == 36.0   # E3 list price


def test_unlicensed_user_never_flagged(tenant_data, pricing, now):
    findings = run_all(_ctx(tenant_data, pricing, now))
    all_upns = {u.user_principal_name for f in findings for u in f.affected_users}
    assert "grace@contoso.com" not in all_upns       # unlicensed, active
