"""Tests for the online price-source provider (parsing + merge + fallback)."""

from __future__ import annotations

import json

from m365_review.core import pricing as pricing_mod
from m365_review.core.pricing import parse_price_payload


def test_parse_json_dict():
    out = parse_price_payload('{"SPE_E3": 30.0, "SPE_E5": 50}')
    assert out == {"SPE_E3": 30.0, "SPE_E5": 50.0}


def test_parse_json_list():
    payload = json.dumps([{"sku": "SPB", "price": 20}, {"skuPartNumber": "SPE_E3", "price": "31.5"}])
    out = parse_price_payload(payload)
    assert out == {"SPB": 20.0, "SPE_E3": 31.5}


def test_parse_csv():
    csv_text = "sku_part_number,price\nSPE_E3,29.99\nSPB,21\n"
    out = parse_price_payload(csv_text)
    assert out == {"SPE_E3": 29.99, "SPB": 21.0}


def test_parse_empty_and_garbage():
    assert parse_price_payload("") == {}
    assert parse_price_payload("not json, not csv either") == {}


def test_online_overrides_yaml(monkeypatch, tmp_path):
    # Point settings at a source URL, and stub the fetch to return an override.
    from m365_review.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("PRICE_SOURCE_URL", "https://example.test/prices.json")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    monkeypatch.setattr(
        pricing_mod,
        "_load_online_prices",
        lambda url, cache: ({"SPE_E3": 99.0, "NEW_SKU_X": 5.0}, f"online rate card ({url})"),
    )

    catalog = pricing_mod.load_pricing()
    assert catalog.price("SPE_E3") == 99.0          # online overrode the yaml (was 36.0)
    assert catalog.price("SPE_E5") == 57.0          # untouched yaml value remains
    assert catalog.price("NEW_SKU_X") == 5.0        # online can add SKUs
    assert "online rate card" in catalog.source
    get_settings.cache_clear()


def test_offline_falls_back_to_cache(tmp_path, monkeypatch):
    # No network: _load_online_prices should read the cache file.
    import httpx

    cache = tmp_path / "prices_cache.json"
    cache.write_text(json.dumps({"SPB": 18.0}), encoding="utf-8")

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", boom)
    prices, source = pricing_mod._load_online_prices("https://example.test/x.json", cache)
    assert prices == {"SPB": 18.0}
    assert "cached" in source
