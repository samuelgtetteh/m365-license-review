#!/usr/bin/env python
"""Regenerate config/sku_display_names.yaml from Microsoft's official reference.

Microsoft publishes "Product names and service plan identifiers for licensing"
as a CSV. Its `String_Id` column is exactly the `skuPartNumber` the Graph API
returns, and `Product_Display_Name` is the human-friendly product name (e.g.
FLOW_FREE -> "Microsoft Power Automate Free"). This script downloads that CSV
and writes a complete part-number -> display-name map.

Run it periodically (Microsoft adds SKUs over time):

    python scripts/update_sku_names.py                 # fetch + overwrite yaml
    python scripts/update_sku_names.py --dry-run       # show count, don't write
    python scripts/update_sku_names.py --url <csv-url> # override source

Docs: https://learn.microsoft.com/entra/identity/users/licensing-service-plan-reference
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

import httpx

DEFAULT_CSV_URL = (
    "https://download.microsoft.com/download/e/3/e/e3e9faf2-f28b-490a-9ada-"
    "c6089a1fc5b0/Product%20names%20and%20service%20plan%20identifiers%20for%20licensing.csv"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPO_ROOT / "config" / "sku_display_names.yaml"

HEADER = """\
# ---------------------------------------------------------------------------
# SKU display-name map — skuPartNumber : human-readable product name
# ---------------------------------------------------------------------------
# AUTO-GENERATED from Microsoft's "Product names and service plan identifiers
# for licensing" reference. Regenerate with:  python scripts/update_sku_names.py
# Source: https://learn.microsoft.com/entra/identity/users/licensing-service-plan-reference
#
# Lookup key = `skuPartNumber` (String_Id) from GET /subscribedSkus.
# If a part number is missing here, the tool prettifies it as a fallback.
# ---------------------------------------------------------------------------
"""


def fetch_mapping(url: str) -> dict[str, str]:
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    # The CSV is UTF-8 with a BOM.
    text = resp.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    mapping: dict[str, str] = {}
    for row in reader:
        sid = (row.get("String_Id") or "").strip()
        name = (row.get("Product_Display_Name") or "").strip()
        if sid and name and sid not in mapping:
            mapping[sid] = name
    return mapping


def write_yaml(mapping: dict[str, str]) -> None:
    lines = [HEADER]
    for sid in sorted(mapping):
        name = mapping[sid].replace('"', "'")
        lines.append(f'{sid}: "{name}"')
    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT_CSV_URL, help="CSV source URL.")
    ap.add_argument("--dry-run", action="store_true", help="Don't write, just report.")
    args = ap.parse_args()

    print(f"Downloading: {args.url}")
    mapping = fetch_mapping(args.url)
    print(f"Parsed {len(mapping)} unique SKU part numbers.")

    # Sanity check a couple of well-known ones.
    for probe in ("FLOW_FREE", "SPB", "O365_BUSINESS_ESSENTIALS"):
        if probe in mapping:
            print(f"  {probe} -> {mapping[probe]}")

    if args.dry_run:
        print("(dry run — not writing)")
        return
    write_yaml(mapping)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
