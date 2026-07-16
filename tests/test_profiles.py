"""Tests for the SQLite profile store."""

from __future__ import annotations

import pytest

from m365_review.core.profiles import ProfileStore


@pytest.fixture
def store(tmp_path):
    return ProfileStore(tmp_path / "test.db")


def test_upsert_and_get(store):
    store.upsert("Contoso", "client-abc", tenant_domain="contoso.com", notes="pilot")
    p = store.get("Contoso")
    assert p is not None
    assert p.client_id == "client-abc"
    assert p.tenant_domain == "contoso.com"
    assert p.notes == "pilot"
    assert p.created_at is not None
    assert p.last_used_at is None


def test_get_missing_returns_none(store):
    assert store.get("nope") is None


def test_upsert_updates_and_preserves_created_at(store):
    first = store.upsert("Acme", "client-1")
    updated = store.upsert("Acme", "client-2", notes="changed")
    assert updated.client_id == "client-2"
    assert updated.notes == "changed"
    assert updated.created_at == first.created_at   # created_at preserved on update


def test_list_orders_recent_first(store):
    store.upsert("A", "1")
    store.upsert("B", "2")
    store.touch("B", tenant_id="tid-b", tenant_name="B Corp")
    names = [p.name for p in store.list()]
    assert names[0] == "B"                          # touched -> most recent first


def test_touch_records_last_tenant(store):
    store.upsert("Client", "cid")
    store.touch("Client", tenant_id="tid-123", tenant_name="Client Ltd")
    p = store.get("Client")
    assert p.last_tenant_id == "tid-123"
    assert p.last_tenant_name == "Client Ltd"
    assert p.last_used_at is not None


def test_delete(store):
    store.upsert("Temp", "x")
    assert store.delete("Temp") is True
    assert store.get("Temp") is None
    assert store.delete("Temp") is False            # already gone


def test_upsert_validates_inputs(store):
    with pytest.raises(ValueError):
        store.upsert("", "cid")
    with pytest.raises(ValueError):
        store.upsert("Name", "   ")


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "persist.db"
    ProfileStore(db).upsert("Persisted", "cid-persist")
    # New instance, same file -> data survives (simulates a container restart).
    assert ProfileStore(db).get("Persisted").client_id == "cid-persist"
