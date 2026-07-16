"""JSON report writer — the full structured AuditResult for machine consumption.

Includes a small ``optimization_summary`` block up top so downstream tooling
(v2 trending, dashboards, billing exports) gets the headline numbers without
recomputing them.
"""

from __future__ import annotations

import json
from pathlib import Path

from m365_review.core.models import AuditResult


def build_json_payload(result: AuditResult) -> dict:
    """Assemble the serializable dict. Separated out so notebooks can inspect it."""
    return {
        "tenant": {
            "display_name": result.tenant_display_name,
            "tenant_id": result.tenant_id,
        },
        "generated_at": result.generated_at.isoformat(),
        "optimization_summary": {
            "total_estimated_monthly_savings_usd": result.total_monthly_savings_usd,
            "total_estimated_annual_savings_usd": result.total_annual_savings_usd,
            "total_licenses_purchased": result.total_purchased,
            "total_licenses_assigned": result.total_assigned,
            "findings_by_severity": result.severity_counts(),
            "finding_count": len(result.findings),
        },
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "recommendation": f.recommendation,
                "estimated_monthly_savings_usd": f.estimated_monthly_savings_usd,
                "estimated_annual_savings_usd": f.estimated_annual_savings_usd,
                "affected_user_count": f.affected_count,
                "affected_users": [
                    {
                        "user_principal_name": u.user_principal_name,
                        "display_name": u.display_name,
                        "detail": u.detail,
                        "monthly_cost_usd": u.monthly_cost_usd,
                    }
                    for u in f.affected_users
                ],
                "notes": f.notes,
            }
            for f in result.findings
        ],
        # Inventory is split into paid vs free/self-service categories.
        "license_inventory": {
            "paid": [_inv_row(r) for r in result.inventory if not r.is_unlimited],
            "free": [_inv_row(r) for r in result.inventory if r.is_unlimited],
        },
        "caveats": result.caveats,
    }


def _inv_row(row) -> dict:
    return {
        "sku_part_number": row.sku_part_number,
        "display_name": row.display_name,
        "purchased": row.purchased,
        "assigned": row.assigned,
        "slack": row.slack,
        "unit_price_usd": row.unit_price_usd,
        "monthly_cost_usd": row.monthly_cost_usd,
        "slack_monthly_usd": row.slack_monthly_usd,
        "price_known": row.price_known,
        "is_unlimited": row.is_unlimited,
    }


def write_json(result: AuditResult, path: Path) -> Path:
    payload = build_json_payload(result)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
