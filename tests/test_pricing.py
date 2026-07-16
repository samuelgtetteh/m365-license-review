"""Tests for pricing catalog loading and lookups."""

from __future__ import annotations


def test_prices_loaded(pricing):
    assert pricing.price("SPE_E3") == 36.0
    assert pricing.price("SPE_E5") == 57.0
    assert pricing.has_price("SPB")


def test_missing_price_returns_none(pricing):
    assert pricing.price("SOME_NEW_ADDON") is None
    assert not pricing.has_price("SOME_NEW_ADDON")


def test_display_name_uses_official_name(pricing):
    assert pricing.display_name("SPE_E3") == "Microsoft 365 E3"
    assert pricing.display_name("FLOW_FREE") == "Microsoft Power Automate Free"


def test_display_name_prettifies_unknown(pricing):
    # Unknown SKUs are prettified rather than shown as raw ALL_CAPS_UNDERSCORE.
    assert not pricing.has_display_name("TOTALLY_UNKNOWN_THING")
    assert pricing.display_name("TOTALLY_UNKNOWN_THING") == "Totally Unknown Thing"


def test_prettify_keeps_plan_acronyms():
    from m365_review.core.pricing import prettify_part_number

    assert prettify_part_number("SOME_NEW_ADDON") == "Some New Addon"
    assert prettify_part_number("WIDGET_E5_US") == "Widget E5 US"


def test_missing_prices_helper(pricing):
    missing = pricing.missing_prices(["SPE_E3", "SOME_NEW_ADDON", "SPE_E5"])
    assert missing == ["SOME_NEW_ADDON"]


def test_overlap_table_loaded(pricing):
    overlaps = pricing.find_overlaps({"SPE_E5", "SPE_E3"})
    assert any(o.redundant == "SPE_E3" for o in overlaps)
