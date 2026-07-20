"""Tests for the selectable-audit catalog + scope-aware selection."""

from __future__ import annotations

from m365_review.core import audits
from m365_review.core.engine import build_result


def test_catalog_ids_unique_and_categorized():
    ids = [a.id for a in audits.all_audits()]
    assert len(ids) == len(set(ids))                 # unique ids
    grouped = audits.by_category()
    assert "Licensing & cost" in grouped
    assert "Identity & access" in grouped


def test_resolve_defaults_to_all():
    assert len(audits.resolve()) == len(audits.all_audits())
    assert len(audits.resolve(ids=[])) == len(audits.all_audits())


def test_resolve_by_id_and_category():
    one = audits.resolve(ids=["lic-unassigned"])
    assert [a.id for a in one] == ["lic-unassigned"]
    ident = audits.resolve(categories=["Identity & access"])
    assert {a.category for a in ident} == {"Identity & access"}


def test_required_data_and_scopes_are_minimal():
    # Unassigned-licenses needs only SKUs → no user/MFA scopes.
    only_unassigned = audits.resolve(ids=["lic-unassigned"])
    data = audits.required_data(only_unassigned)
    assert data == {"skus"}
    scopes = audits.required_scopes(only_unassigned)
    assert "User.Read.All" not in scopes             # not needed for a SKU-only audit
    assert "Directory.Read.All" in scopes
    assert "Organization.Read.All" in scopes         # base scope always present


def test_selected_run_only_chosen_audit(tenant_data, pricing, now):
    # Running only R3 (unassigned) should produce only R3 findings.
    selected = audits.resolve(ids=["lic-unassigned"])
    result = build_result(tenant_data, pricing=pricing, now=now, selected=selected)
    assert result.findings
    assert {f.rule_id for f in result.findings} == {"R3"}


def test_selecting_identity_excludes_licensing_findings(tenant_data, pricing, now):
    selected = audits.resolve(categories=["Identity & access"])
    result = build_result(tenant_data, pricing=pricing, now=now, selected=selected)
    rule_ids = {f.rule_id for f in result.findings}
    assert rule_ids and rule_ids.issubset({"R7", "R9", "R10"})
    assert "R1" not in rule_ids and "R3" not in rule_ids
