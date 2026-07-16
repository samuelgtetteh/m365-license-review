"""Report writers. One canonical AuditResult -> .xlsx / .docx / .json.

``write_reports`` dispatches to the requested formats and returns a mapping of
format -> written path. Each writer is independent and imports its heavy
dependency (openpyxl / python-docx) lazily, so a JSON-only run needn't have the
Office libraries loaded.
"""

from __future__ import annotations

import logging
from pathlib import Path

from m365_review.core.models import AuditResult

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ("xlsx", "docx", "json")


def write_reports(
    result: AuditResult,
    *,
    output_dir: Path,
    formats: list[str],
) -> dict[str, Path]:
    """Write the requested formats. Returns {format: path}."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = result.base_filename()

    written: dict[str, Path] = {}
    for fmt in formats:
        fmt = fmt.lower()
        path = output_dir / f"{base}.{fmt}"
        if fmt == "json":
            from m365_review.core.report.json_writer import write_json

            write_json(result, path)
        elif fmt == "xlsx":
            from m365_review.core.report.xlsx_writer import write_xlsx

            write_xlsx(result, path)
        elif fmt == "docx":
            from m365_review.core.report.docx_writer import write_docx

            write_docx(result, path)
        else:
            logger.warning("Unknown output format %r; skipping.", fmt)
            continue
        written[fmt] = path
        logger.info("Wrote %s report: %s", fmt, path)
    return written
