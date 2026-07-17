"""Tests for the subscription-expiration feature (R8, model, export)."""

from __future__ import annotations

from m365_review.core.engine import build_result
from m365_review.core.rules import r8_expiring_subscriptions
from m365_review.core.rules.base import RuleContext
from m365_review.core.report.json_writer import build_json_payload


def _ctx(tenant_data, pricing, now):
    return RuleContext(data=tenant_data, pricing=pricing, now=now)


def test_subscription_model_days(tenant_data, now):
    e5 = next(s for s in tenant_data.subscriptions if s.sku_part_number == "SPE_E5")
    assert e5.days_until_expiry(now) == 14        # 2026-07-30 vs 2026-07-16
    assert not e5.is_expired(now)
    assert e5.is_expiring_within(now, 30)

    exo = next(s for s in tenant_data.subscriptions if s.sku_part_number == "EXCHANGESTANDARD")
    assert exo.is_expired(now)                    # 2026-06-01 is in the past


def test_r8_flags_expired_and_soon(tenant_data, pricing, now):
    findings = r8_expiring_subscriptions.evaluate(_ctx(tenant_data, pricing, now))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity.value == "high"             # something is already expired
    # E5 (14d), EXCHANGESTANDARD (expired), FLOW_FREE trial (16d) -> 3 flagged;
    # SPE_E3 (far future) is not flagged.
    assert f.affected_count == 3


def test_expiration_summary_and_json(tenant_data, pricing, now):
    result = build_result(tenant_data, pricing=pricing, now=now)
    summ = result.expiration_summary()
    assert summ["expired"] == 1
    assert summ["within_30"] == 2                 # E5 + trial
    assert summ["total"] == 4

    payload = build_json_payload(result)
    block = payload["subscription_expirations"]
    assert block["available"] is True
    assert len(block["items"]) == 4
    # sorted soonest-first: first item should be the expired one (earliest date)
    assert block["items"][0]["sku_part_number"] == "EXCHANGESTANDARD"


def test_expirations_unavailable_is_graceful(tenant_data, pricing, now):
    data = tenant_data.model_copy(deep=True)
    data.subscriptions = []
    data.subscriptions_available = False
    result = build_result(data, pricing=pricing, now=now)
    assert result.subscriptions_available is False
    assert any("expiration data was unavailable" in c.lower() for c in result.caveats)
