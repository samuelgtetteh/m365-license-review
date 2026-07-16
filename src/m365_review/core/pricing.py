"""SKU pricing, display names, and overlap table — loaded from config/*.yaml.

Lookup key everywhere is the ``skuPartNumber`` from /subscribedSkus. Prices are
monthly per-user USD. A missing price is not an error: the tool still reports
the SKU and surfaces a caveat telling the operator to update the price map.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from m365_review.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def prettify_part_number(sku_part_number: str) -> str:
    """Best-effort readable name for a SKU with no official mapping.

    e.g. 'SOME_NEW_ADDON' -> 'Some New Addon'. Not marketing-accurate, but far
    more readable than the raw part number. Preserves common acronyms/plan tags.
    """
    if not sku_part_number:
        return sku_part_number
    _KEEP_UPPER = {"E3", "E5", "E1", "F1", "F3", "P1", "P2", "US", "EU", "AD", "BI", "VDI"}
    words = sku_part_number.replace("-", "_").split("_")
    out = []
    for w in words:
        if not w:
            continue
        if w.upper() in _KEEP_UPPER:
            out.append(w.upper())
        else:
            out.append(w.capitalize())
    return " ".join(out) or sku_part_number


@dataclass(frozen=True)
class Overlap:
    sku_a: str
    sku_b: str
    redundant: str
    reason: str


class PricingCatalog:
    """Holds the price map, display-name map, and overlap table for one run."""

    def __init__(
        self,
        prices: dict[str, float],
        display_names: dict[str, str],
        overlaps: list[Overlap],
    ):
        self._prices = prices
        self._display_names = display_names
        self._overlaps = overlaps

    # --- prices ---
    def price(self, sku_part_number: str) -> float | None:
        """Monthly per-user USD price, or None if not in the map."""
        return self._prices.get(sku_part_number)

    def has_price(self, sku_part_number: str) -> bool:
        return sku_part_number in self._prices

    # --- display names ---
    def display_name(self, sku_part_number: str) -> str:
        """Human-readable product name.

        Uses Microsoft's official product name when known; otherwise falls back to
        a prettified form of the part number so reports never show raw
        ALL_CAPS_UNDERSCORE identifiers.
        """
        known = self._display_names.get(sku_part_number)
        if known:
            return known
        return prettify_part_number(sku_part_number)

    def has_display_name(self, sku_part_number: str) -> bool:
        """True if an official (non-fallback) display name is known."""
        return sku_part_number in self._display_names

    # --- overlaps (used by R4) ---
    @property
    def overlaps(self) -> list[Overlap]:
        return list(self._overlaps)

    def find_overlaps(self, sku_part_numbers: set[str]) -> list[Overlap]:
        """Return overlap entries where BOTH SKUs are present in the given set."""
        return [
            o for o in self._overlaps
            if o.sku_a in sku_part_numbers and o.sku_b in sku_part_numbers
        ]

    def missing_prices(self, sku_part_numbers: list[str]) -> list[str]:
        """Which of the given part numbers have no price entry (sorted, unique)."""
        return sorted({s for s in sku_part_numbers if s not in self._prices})


def load_pricing(settings: Settings | None = None) -> PricingCatalog:
    """Load all three yaml maps into a PricingCatalog."""
    settings = settings or get_settings()
    prices = _load_price_map(settings.sku_prices_path)
    names = _load_name_map(settings.sku_display_names_path)
    overlaps = _load_overlaps(settings.sku_overlaps_path)
    logger.info(
        "Loaded pricing: %d prices, %d display names, %d overlap rules.",
        len(prices), len(names), len(overlaps),
    )
    return PricingCatalog(prices=prices, display_names=names, overlaps=overlaps)


# --------------------------------------------------------------------------- #
# yaml loaders (tolerant of comments / missing files)
# --------------------------------------------------------------------------- #

def _read_yaml(path: Path) -> dict | list:
    if not path.exists():
        logger.warning("Config file not found: %s (continuing with empty map).", path)
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_price_map(path: Path) -> dict[str, float]:
    data = _read_yaml(path)
    prices: dict[str, float] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            try:
                prices[str(key)] = float(value)
            except (TypeError, ValueError):
                logger.warning("Skipping non-numeric price for %s: %r", key, value)
    return prices


def _load_name_map(path: Path) -> dict[str, str]:
    data = _read_yaml(path)
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _load_overlaps(path: Path) -> list[Overlap]:
    data = _read_yaml(path)
    rows = data.get("overlaps", []) if isinstance(data, dict) else []
    overlaps: list[Overlap] = []
    for row in rows:
        try:
            overlaps.append(
                Overlap(
                    sku_a=row["sku_a"],
                    sku_b=row["sku_b"],
                    redundant=row["redundant"],
                    reason=row.get("reason", ""),
                )
            )
        except (KeyError, TypeError):
            logger.warning("Skipping malformed overlap row: %r", row)
    return overlaps
