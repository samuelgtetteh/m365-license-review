"""Audit catalog — the single registry of selectable audits.

Each audit is an :class:`AuditDef`: a stable id, a category, the rule that
implements it, the tenant data it needs, and any extra Graph scope it requires.
The web UI renders these as grouped checkboxes; the engine runs only the selected
ones and fetches only the data they need; sign-in requests only the scopes they
need. Existing rules (R1-R10) are wrapped here; Phase 1+ audits join the same list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from m365_review.core.rules import (
    r1_disabled_licensed,
    r2_inactive_licensed,
    r3_unassigned_licenses,
    r4_duplicate_skus,
    r7_licensed_guests,
    r8_expiring_subscriptions,
    r9_users_without_mfa,
    r10_admin_audit,
)

# Scopes always requested (sign-in + tenant identity).
BASE_SCOPES: tuple[str, ...] = ("User.Read", "Organization.Read.All")

# Which Graph scopes each unit of tenant data needs.
DATA_SCOPES: dict[str, tuple[str, ...]] = {
    "skus": ("Directory.Read.All",),
    "subscriptions": ("Directory.Read.All",),
    "users": ("User.Read.All", "AuditLog.Read.All"),
    "user_registration": ("AuditLog.Read.All",),
    "directory_roles": ("Directory.Read.All",),
}

# Category display order for the UI.
CATEGORY_ORDER: tuple[str, ...] = (
    "Licensing & cost",
    "Identity & access",
    "Security posture",
    "Exchange",
    "On-prem",
)


@dataclass(frozen=True)
class AuditDef:
    id: str
    title: str
    category: str
    description: str
    rule: object                       # module exposing .evaluate(ctx)
    data: tuple[str, ...] = ()          # tenant-data units this audit needs
    scopes: tuple[str, ...] = ()        # extra Graph scopes beyond data/base
    experimental: bool = False


CATALOG: list[AuditDef] = [
    # --- Licensing & cost ---
    AuditDef("lic-disabled", "Disabled users with licenses", "Licensing & cost",
             "Licenses still assigned to disabled accounts.",
             r1_disabled_licensed, data=("users", "skus")),
    AuditDef("lic-inactive", "Inactive licensed users (90 days)", "Licensing & cost",
             "Licensed, enabled users with no sign-in in 90 days.",
             r2_inactive_licensed, data=("users", "skus")),
    AuditDef("lic-unassigned", "Unassigned purchased licenses", "Licensing & cost",
             "Purchased seats that aren't assigned to anyone.",
             r3_unassigned_licenses, data=("skus",)),
    AuditDef("lic-duplicate", "Duplicate / overlapping licenses", "Licensing & cost",
             "Users holding a SKU a superset license already covers.",
             r4_duplicate_skus, data=("users", "skus")),
    AuditDef("lic-expirations", "Expiring subscriptions", "Licensing & cost",
             "Subscriptions expired or expiring within 30 days.",
             r8_expiring_subscriptions, data=("subscriptions", "skus")),
    # --- Identity & access ---
    AuditDef("idn-guests", "Licensed guest users", "Identity & access",
             "Guest accounts holding licenses they usually don't need.",
             r7_licensed_guests, data=("users", "skus")),
    AuditDef("idn-mfa-registration", "Users without MFA registered", "Identity & access",
             "Member accounts with no registered MFA method.",
             r9_users_without_mfa, data=("user_registration",)),
    AuditDef("idn-admin-audit", "Admin audit (MFA + count)", "Identity & access",
             "Admins without MFA, and too many Global Administrators.",
             r10_admin_audit, data=("user_registration", "directory_roles")),
]

_BY_ID = {a.id: a for a in CATALOG}


def all_audits() -> list[AuditDef]:
    return list(CATALOG)


def get(audit_id: str) -> AuditDef | None:
    return _BY_ID.get(audit_id)


def by_category() -> dict[str, list[AuditDef]]:
    """Audits grouped by category, in CATEGORY_ORDER."""
    grouped: dict[str, list[AuditDef]] = {c: [] for c in CATEGORY_ORDER}
    for a in CATALOG:
        grouped.setdefault(a.category, []).append(a)
    return {c: items for c, items in grouped.items() if items}


def resolve(
    ids: list[str] | None = None,
    categories: list[str] | None = None,
    select_all: bool = False,
    include_experimental: bool = False,
) -> list[AuditDef]:
    """Turn a selection (ids / categories / all) into concrete AuditDefs.

    An empty/unspecified selection resolves to all (non-experimental) audits, so
    callers that don't select anything keep the previous "run everything" behavior.
    """
    if select_all or (not ids and not categories):
        chosen = [a for a in CATALOG if include_experimental or not a.experimental]
    else:
        wanted_ids = set(ids or [])
        wanted_cats = set(categories or [])
        chosen = [
            a for a in CATALOG
            if a.id in wanted_ids or a.category in wanted_cats
        ]
    return chosen


def required_data(defs: list[AuditDef]) -> set[str]:
    """Union of tenant-data units the given audits need."""
    needed: set[str] = set()
    for a in defs:
        needed.update(a.data)
    return needed


def required_scopes(defs: list[AuditDef]) -> list[str]:
    """Minimal Graph scope set for the given audits (base + data + audit-specific)."""
    scopes: set[str] = set(BASE_SCOPES)
    for unit in required_data(defs):
        scopes.update(DATA_SCOPES.get(unit, ()))
    for a in defs:
        scopes.update(a.scopes)
    return sorted(scopes)
