"""Shared pytest fixtures.

Loads the synthetic Graph fixtures once and exposes them as normalized models,
plus a fixed ``now`` so all date-based rules are deterministic. These same
fixtures drive the reproducibility notebooks.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from m365_review.core.models import Organization, SubscribedSku, TenantData, User
from m365_review.core.pricing import load_pricing

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Matches the fixture timestamps (see tests/fixtures/users.json).
FIXED_NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def pricing():
    return load_pricing()


@pytest.fixture
def tenant_data() -> TenantData:
    org = Organization.from_graph(_load("organization.json")["value"][0])
    skus = [SubscribedSku.from_graph(s) for s in _load("subscribedSkus.json")["value"]]
    users = [User.from_graph(u) for u in _load("users.json")["value"]]
    return TenantData(
        organization=org,
        tenant_id=org.id,
        skus=skus,
        users=users,
        sign_in_activity_available=True,
    )
