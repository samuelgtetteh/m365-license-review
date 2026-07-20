"""Tests for Phase 1 security-posture audits (R11-R16) + scope gating."""

from __future__ import annotations

import datetime

from m365_review.core import audits
from m365_review.core.models import (
    AuthMethodConfig,
    ConditionalAccessPolicy,
    Domain,
    GLOBAL_ADMIN_ROLE_TEMPLATE_ID,
    NamedLocation,
    Organization,
    TenantData,
    UserMfaRequirement,
)
from m365_review.core.pricing import load_pricing
from m365_review.core.rules import (
    r11_ca_require_mfa_all,
    r12_ca_block_legacy,
    r13_auth_methods_policy,
    r14_trusted_locations,
    r15_ga_mfa_coverage,
    r16_peruser_mfa_state,
    r17_allowed_domains,
)
from m365_review.core.rules.base import RuleContext

NOW = datetime.datetime(2026, 7, 17, tzinfo=datetime.timezone.utc)


def _ctx(**kw):
    data = TenantData(organization=Organization(id="t", display_name="T"), tenant_id="t", **kw)
    return RuleContext(data=data, pricing=load_pricing(), now=NOW)


def _mfa_all_policy():
    return ConditionalAccessPolicy(
        id="p1", display_name="Require MFA all", state="enabled",
        include_users=["All"], include_applications=["All"], grant_controls=["mfa"],
    )


# --- R11 require MFA all ---
def test_r11_pass_when_policy_present():
    ctx = _ctx(ca_policies=[_mfa_all_policy()], ca_available=True)
    assert r11_ca_require_mfa_all.evaluate(ctx) == []


def test_r11_fail_when_absent():
    ctx = _ctx(ca_policies=[], ca_available=True)
    f = r11_ca_require_mfa_all.evaluate(ctx)
    assert len(f) == 1 and f[0].severity.value == "high"


def test_r11_skipped_when_unavailable():
    ctx = _ctx(ca_policies=[], ca_available=False)
    assert r11_ca_require_mfa_all.evaluate(ctx) == []


# --- R12 block legacy ---
def test_r12_pass_and_fail():
    blocker = ConditionalAccessPolicy(
        id="p2", display_name="Block legacy", state="enabled",
        include_users=["All"], client_app_types=["exchangeActiveSync", "other"],
        grant_controls=["block"],
    )
    assert r12_ca_block_legacy.evaluate(_ctx(ca_policies=[blocker], ca_available=True)) == []
    assert len(r12_ca_block_legacy.evaluate(_ctx(ca_policies=[], ca_available=True))) == 1


# --- R15 GA coverage ---
def test_r15_pass_via_role_target():
    pol = ConditionalAccessPolicy(
        id="p3", display_name="MFA admins", state="enabled",
        include_roles=[GLOBAL_ADMIN_ROLE_TEMPLATE_ID], grant_controls=["mfa"],
    )
    assert r15_ga_mfa_coverage.evaluate(_ctx(ca_policies=[pol], ca_available=True)) == []
    assert len(r15_ga_mfa_coverage.evaluate(_ctx(ca_policies=[], ca_available=True))) == 1


# --- R13 auth methods policy ---
def test_r13_flags_weak_and_missing_strong():
    weak = [AuthMethodConfig(id="Sms", state="enabled"), AuthMethodConfig(id="MicrosoftAuthenticator", state="disabled")]
    f = r13_auth_methods_policy.evaluate(_ctx(auth_methods=weak, auth_methods_available=True))
    assert len(f) == 1
    aligned = [
        AuthMethodConfig(id="MicrosoftAuthenticator", state="enabled"),
        AuthMethodConfig(id="Fido2", state="enabled"),
        AuthMethodConfig(id="Sms", state="disabled"),
        AuthMethodConfig(id="Voice", state="disabled"),
    ]
    assert r13_auth_methods_policy.evaluate(_ctx(auth_methods=aligned, auth_methods_available=True)) == []


# --- R14 trusted locations ---
def test_r14_lists_trusted():
    locs = [NamedLocation(id="l1", display_name="HQ", location_type="ip", is_trusted=True),
            NamedLocation(id="l2", display_name="US", location_type="country", is_trusted=False)]
    f = r14_trusted_locations.evaluate(_ctx(named_locations=locs, named_locations_available=True))
    assert len(f) == 1 and f[0].affected_count == 1


# --- R16 per-user MFA state ---
def test_r16_flags_not_enforced():
    reqs = [UserMfaRequirement(user_principal_name="a@x", state="enforced"),
            UserMfaRequirement(user_principal_name="b@x", state="disabled")]
    f = r16_peruser_mfa_state.evaluate(_ctx(per_user_mfa=reqs, per_user_mfa_available=True))
    assert len(f) == 1 and f[0].affected_count == 1 and f[0].severity.value == "info"


# --- R17 domains ---
def test_r17_flags_unverified_domains():
    doms = [Domain(id="contoso.com", is_verified=True, is_default=True),
            Domain(id="old.contoso.com", is_verified=False)]
    f = r17_allowed_domains.evaluate(_ctx(domains=doms, domains_available=True))
    assert len(f) == 1 and f[0].severity.value == "medium" and f[0].affected_count == 2


def test_r17_all_verified_is_info():
    doms = [Domain(id="contoso.com", is_verified=True, is_default=True)]
    f = r17_allowed_domains.evaluate(_ctx(domains=doms, domains_available=True))
    assert len(f) == 1 and f[0].severity.value == "info"


# --- scope gating ---
def test_policy_scope_only_when_posture_selected():
    lic = audits.resolve(ids=["lic-unassigned"])
    assert "Policy.Read.All" not in audits.required_scopes(lic)
    sec = audits.resolve(ids=["sec-ca-block-legacy"])
    assert "Policy.Read.All" in audits.required_scopes(sec)
    assert audits.required_data(sec) == {"ca_policies"}


def test_domains_audit_uses_directory_scope_not_policy():
    dom = audits.resolve(ids=["sec-allowed-domains"])
    scopes = audits.required_scopes(dom)
    assert "Directory.Read.All" in scopes and "Policy.Read.All" not in scopes
