"""Tests for the identity-security audits: R9 (MFA) and R10 (admin audit)."""

from __future__ import annotations

from m365_review.core.engine import build_result
from m365_review.core.rules import r9_users_without_mfa, r10_admin_audit
from m365_review.core.rules.base import RuleContext
from m365_review.core.report.json_writer import build_json_payload


def _ctx(tenant_data, pricing, now):
    return RuleContext(data=tenant_data, pricing=pricing, now=now)


def test_r9_flags_members_without_mfa(tenant_data, pricing, now):
    findings = r9_users_without_mfa.evaluate(_ctx(tenant_data, pricing, now))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity.value == "high"
    upns = {u.user_principal_name for u in f.affected_users}
    # carol + dave are members without MFA; the admin is handled by R10, alice has MFA.
    assert upns == {"carol@contoso.com", "dave@contoso.com"}


def test_r9_skipped_when_data_unavailable(tenant_data, pricing, now):
    data = tenant_data.model_copy(deep=True)
    data.user_registration = []
    assert r9_users_without_mfa.evaluate(_ctx(data, pricing, now)) == []


def test_r10_admins_without_mfa_and_too_many_ga(tenant_data, pricing, now):
    findings = r10_admin_audit.evaluate(_ctx(tenant_data, pricing, now))
    titles = [f.title for f in findings]
    assert any("Administrators without MFA" in t for t in titles)     # admin@ has no MFA
    assert any("Many Global Administrators" in t for t in titles)     # 5 GAs > 4
    admins_no_mfa = next(f for f in findings if "without MFA" in f.title)
    assert admins_no_mfa.severity.value == "high"


def test_identity_block_in_json(tenant_data, pricing, now):
    result = build_result(tenant_data, pricing=pricing, now=now)
    block = build_json_payload(result)["identity_security"]
    assert block["mfa"]["available"] is True
    assert block["mfa"]["without_mfa"] == 3            # carol, dave, admin
    assert block["mfa"]["admins_without_mfa"] == 1
    roles = {r["role"]: r["member_count"] for r in block["privileged_roles"]["roles"]}
    assert roles["Global Administrator"] == 5
