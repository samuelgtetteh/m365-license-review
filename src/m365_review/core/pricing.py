"""SKU pricing, display names, and overlap table — loaded from config/*.yaml.

Lookup key everywhere is the ``skuPartNumber`` from /subscribedSkus. Prices are
monthly per-user USD. A missing price is not an error: the tool still reports
the SKU and surfaces a caveat telling the operator to update the price map.
"""

from __future__ import annotations

import csv
import io
import json
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
        source: str = "local price map",
    ):
        self._prices = prices
        self._display_names = display_names
        self._overlaps = overlaps
        self.source = source  # human-readable description of where prices came from

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
    """Load pricing: local yaml as the base, optionally overlaid with online rates."""
    settings = settings or get_settings()
    prices = _load_price_map(settings.sku_prices_path)
    names = _load_name_map(settings.sku_display_names_path)
    overlaps = _load_overlaps(settings.sku_overlaps_path)
    source = "local price map (config/sku_prices.yaml)"

    # Overlay online rates when a source URL is configured.
    if settings.price_source_url:
        online, online_source = _load_online_prices(
            settings.price_source_url, settings.price_cache_path
        )
        if online:
            prices.update(online)  # online overrides / extends the yaml
            source = online_source
        else:
            logger.warning("Online price source yielded no prices; using the local yaml.")

    logger.info(
        "Loaded pricing: %d prices, %d display names, %d overlap rules (source: %s).",
        len(prices), len(names), len(overlaps), source,
    )
    return PricingCatalog(prices=prices, display_names=names, overlaps=overlaps, source=source)


# --------------------------------------------------------------------------- #
# Online price source (URL -> JSON/CSV), cached, with graceful fallback
# --------------------------------------------------------------------------- #

def parse_price_payload(text: str) -> dict[str, float]:
    """Parse a rate card from JSON (dict or list) or CSV text into {sku: price}.

    Accepts:
      * JSON object:  {"SPE_E3": 36.0, ...}
      * JSON array:   [{"sku": "SPE_E3", "price": 36.0}, ...]
      * CSV:          headers include sku/sku_part_number/skuPartNumber + price/unit_price_usd
    """
    text = (text or "").strip()
    if not text:
        return {}

    # Try JSON first.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return {str(k): float(v) for k, v in obj.items() if _is_number(v)}
        if isinstance(obj, list):
            out: dict[str, float] = {}
            for row in obj:
                if not isinstance(row, dict):
                    continue
                sku = row.get("sku") or row.get("sku_part_number") or row.get("skuPartNumber")
                price = row.get("price", row.get("unit_price_usd"))
                if sku and _is_number(price):
                    out[str(sku).strip()] = float(price)
            return out
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back to CSV.
    out = {}
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        sku = row.get("sku") or row.get("sku_part_number") or row.get("skuPartNumber")
        price = row.get("price", row.get("unit_price_usd"))
        if sku and price not in (None, ""):
            try:
                out[str(sku).strip()] = float(price)
            except (TypeError, ValueError):
                continue
    return out


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _load_online_prices(url: str, cache_path: Path) -> tuple[dict[str, float], str]:
    """Fetch prices from the URL (cached). Returns (prices, source-description)."""
    import httpx

    try:
        resp = httpx.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
        prices = parse_price_payload(resp.text)
        if prices:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(prices), encoding="utf-8")
            except OSError:
                pass
            return prices, f"online rate card ({url})"
        logger.warning("Online price source returned no usable rows: %s", url)
    except Exception as exc:  # noqa: BLE001 — network/parse errors -> fall back to cache
        logger.warning("Could not fetch online prices (%s): %s", type(exc).__name__, exc)

    # Offline / failed: use the cached copy if present.
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return {str(k): float(v) for k, v in cached.items()}, f"cached rate card ({url})"
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return {}, "local price map"


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
