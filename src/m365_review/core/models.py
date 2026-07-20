"""Pydantic domain models.

Two groups:

* **Graph shapes** — normalized views of the Graph payloads the fetchers return
  (`Organization`, `SubscribedSku`, `User`). Fetchers map raw JSON into these so
  the rest of the code never touches Graph's camelCase / nesting directly.
* **Result shapes** — `Finding`, `TenantData` (input to rules), and `AuditResult`
  (the single object every report writer serializes).
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Graph shapes
# --------------------------------------------------------------------------- #

class Organization(BaseModel):
    id: str
    display_name: str
    verified_domains: list[str] = Field(default_factory=list)
    country: str | None = None

    @classmethod
    def from_graph(cls, data: dict) -> "Organization":
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            verified_domains=[d.get("name", "") for d in data.get("verifiedDomains", [])],
            country=data.get("countryLetterCode") or data.get("country"),
        )


# Microsoft stamps free / self-service SKUs (Power Automate Free, RMS ad-hoc,
# Teams Exploratory, Business Central for IWs, ...) with a huge default quota
# (10,000+). Those are not "purchased" seats and must not inflate license totals
# or be treated as reclaimable slack.
FREE_QUOTA_THRESHOLD = 10_000


# Subscription capabilityStatus values that mean the license is NOT usable and
# should be excluded from the report (disabled / expired-and-past-grace).
_INACTIVE_STATUSES = {"suspended", "deleted", "lockedout"}


class SubscribedSku(BaseModel):
    sku_id: str
    sku_part_number: str
    prepaid_enabled: int = 0     # active, usable seats
    prepaid_warning: int = 0     # expired but in grace period — still usable
    prepaid_suspended: int = 0   # suspended — NOT usable
    consumed_units: int = 0      # assigned seats
    capability_status: str | None = None

    @property
    def usable(self) -> int:
        """Seats the tenant can actually use: active + in-grace (enabled + warning)."""
        return self.prepaid_enabled + self.prepaid_warning

    @property
    def slack(self) -> int:
        """Usable minus assigned (unused seats). Never negative."""
        return max(0, self.usable - self.consumed_units)

    @property
    def is_unlimited(self) -> bool:
        """True for free/self-service SKUs with a default 10,000+ quota."""
        return self.usable >= FREE_QUOTA_THRESHOLD

    @property
    def is_active(self) -> bool:
        """False for disabled subscriptions (suspended/deleted/locked-out).

        An unknown/empty status is treated as active (be lenient).
        """
        return (self.capability_status or "").strip().lower() not in _INACTIVE_STATUSES

    @classmethod
    def from_graph(cls, data: dict) -> "SubscribedSku":
        prepaid = data.get("prepaidUnits", {}) or {}
        return cls(
            sku_id=data.get("skuId", ""),
            sku_part_number=data.get("skuPartNumber", ""),
            prepaid_enabled=int(prepaid.get("enabled", 0) or 0),
            prepaid_warning=int(prepaid.get("warning", 0) or 0),
            prepaid_suspended=int(prepaid.get("suspended", 0) or 0),
            consumed_units=int(data.get("consumedUnits", 0) or 0),
            capability_status=data.get("capabilityStatus"),
        )


class Subscription(BaseModel):
    """A commerce subscription (from /directory/subscriptions) with dates.

    This is where expiration/renewal information lives — /subscribedSkus has none.
    """

    sku_id: str
    sku_part_number: str
    display_name: str = ""          # filled by the engine via the pricing catalog
    status: str | None = None       # Enabled | Warning | Suspended | Deleted | LockedOut
    total_licenses: int = 0
    is_trial: bool = False
    created_datetime: datetime | None = None
    next_lifecycle_datetime: datetime | None = None   # next renewal or expiration

    def days_until_expiry(self, now: datetime) -> int | None:
        if self.next_lifecycle_datetime is None:
            return None
        return (self.next_lifecycle_datetime - now).days

    def is_expired(self, now: datetime) -> bool:
        d = self.days_until_expiry(now)
        return d is not None and d < 0

    def is_expiring_within(self, now: datetime, days: int) -> bool:
        d = self.days_until_expiry(now)
        return d is not None and 0 <= d <= days

    @classmethod
    def from_graph(cls, data: dict) -> "Subscription":
        return cls(
            sku_id=data.get("skuId", ""),
            sku_part_number=data.get("skuPartNumber", ""),
            status=data.get("status"),
            total_licenses=int(data.get("totalLicenses", 0) or 0),
            is_trial=bool(data.get("isTrial", False)),
            created_datetime=_parse_dt(data.get("createdDateTime")),
            next_lifecycle_datetime=_parse_dt(data.get("nextLifecycleDateTime")),
        )


class User(BaseModel):
    id: str
    display_name: str | None = None
    user_principal_name: str | None = None
    mail: str | None = None
    account_enabled: bool = True
    user_type: str | None = None                     # "Member" | "Guest"
    created_datetime: datetime | None = None
    assigned_license_sku_ids: list[str] = Field(default_factory=list)
    last_sign_in: datetime | None = None
    last_non_interactive_sign_in: datetime | None = None
    sign_in_activity_available: bool = True           # False if tenant lacks AAD P1

    @property
    def is_licensed(self) -> bool:
        return len(self.assigned_license_sku_ids) > 0

    @property
    def effective_last_sign_in(self) -> datetime | None:
        """Most recent of interactive / non-interactive sign-in."""
        candidates = [d for d in (self.last_sign_in, self.last_non_interactive_sign_in) if d]
        return max(candidates) if candidates else None

    @classmethod
    def from_graph(cls, data: dict) -> "User":
        activity = data.get("signInActivity") or {}
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName"),
            user_principal_name=data.get("userPrincipalName"),
            mail=data.get("mail"),
            account_enabled=bool(data.get("accountEnabled", True)),
            user_type=data.get("userType"),
            created_datetime=_parse_dt(data.get("createdDateTime")),
            assigned_license_sku_ids=[
                lic.get("skuId", "") for lic in data.get("assignedLicenses", []) if lic.get("skuId")
            ],
            last_sign_in=_parse_dt(activity.get("lastSignInDateTime")),
            last_non_interactive_sign_in=_parse_dt(activity.get("lastNonInteractiveSignInDateTime")),
            sign_in_activity_available="signInActivity" in data,
        )


class UserRegistration(BaseModel):
    """Per-user auth-method registration (from reports/authenticationMethods)."""

    user_principal_name: str | None = None
    display_name: str | None = None
    user_type: str | None = None          # "member" | "guest"
    is_admin: bool = False
    is_mfa_registered: bool = False
    is_mfa_capable: bool = False

    @classmethod
    def from_graph(cls, data: dict) -> "UserRegistration":
        return cls(
            user_principal_name=data.get("userPrincipalName"),
            display_name=data.get("userDisplayName"),
            user_type=(data.get("userType") or "").lower() or None,
            is_admin=bool(data.get("isAdmin", False)),
            is_mfa_registered=bool(data.get("isMfaRegistered", False)),
            is_mfa_capable=bool(data.get("isMfaCapable", False)),
        )


class RoleMember(BaseModel):
    id: str
    display_name: str | None = None
    user_principal_name: str | None = None


class DirectoryRole(BaseModel):
    """An activated directory role and its members (from /directoryRoles)."""

    id: str
    display_name: str
    members: list[RoleMember] = Field(default_factory=list)

    @property
    def is_privileged(self) -> bool:
        name = (self.display_name or "").lower()
        return any(k in name for k in ("administrator", "admin"))

    @classmethod
    def from_graph(cls, data: dict) -> "DirectoryRole":
        members = []
        for m in data.get("members", []):
            members.append(
                RoleMember(
                    id=m.get("id", ""),
                    display_name=m.get("displayName"),
                    user_principal_name=m.get("userPrincipalName"),
                )
            )
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            members=members,
        )


GLOBAL_ADMIN_ROLE_TEMPLATE_ID = "62e90394-69f5-4237-9190-012177145e10"


class ConditionalAccessPolicy(BaseModel):
    id: str
    display_name: str
    state: str = ""                     # enabled | disabled | enabledForReportingButNotEnforced
    include_users: list[str] = Field(default_factory=list)
    exclude_users: list[str] = Field(default_factory=list)
    include_roles: list[str] = Field(default_factory=list)
    exclude_roles: list[str] = Field(default_factory=list)
    include_groups: list[str] = Field(default_factory=list)
    include_applications: list[str] = Field(default_factory=list)
    client_app_types: list[str] = Field(default_factory=list)
    grant_controls: list[str] = Field(default_factory=list)

    @property
    def is_enabled(self) -> bool:
        return self.state == "enabled"

    @property
    def targets_all_users(self) -> bool:
        return "All" in self.include_users

    def targets_role(self, role_template_id: str) -> bool:
        return role_template_id in self.include_roles

    @classmethod
    def from_graph(cls, data: dict) -> "ConditionalAccessPolicy":
        cond = data.get("conditions", {}) or {}
        users = cond.get("users", {}) or {}
        apps = cond.get("applications", {}) or {}
        grant = data.get("grantControls") or {}
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            state=data.get("state", ""),
            include_users=users.get("includeUsers", []) or [],
            exclude_users=users.get("excludeUsers", []) or [],
            include_roles=users.get("includeRoles", []) or [],
            exclude_roles=users.get("excludeRoles", []) or [],
            include_groups=users.get("includeGroups", []) or [],
            include_applications=apps.get("includeApplications", []) or [],
            client_app_types=cond.get("clientAppTypes", []) or [],
            grant_controls=(grant.get("builtInControls", []) or []),
        )


class NamedLocation(BaseModel):
    id: str
    display_name: str
    location_type: str = "unknown"      # ip | country | unknown
    is_trusted: bool = False

    @classmethod
    def from_graph(cls, data: dict) -> "NamedLocation":
        odata = (data.get("@odata.type") or "").lower()
        if "ipnamedlocation" in odata:
            ltype, trusted = "ip", bool(data.get("isTrusted", False))
        elif "countrynamedlocation" in odata:
            ltype, trusted = "country", False
        else:
            ltype, trusted = "unknown", bool(data.get("isTrusted", False))
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            location_type=ltype,
            is_trusted=trusted,
        )


class AuthMethodConfig(BaseModel):
    id: str                              # e.g. MicrosoftAuthenticator, Sms, Voice, Fido2, Email
    state: str = "disabled"              # enabled | disabled

    @classmethod
    def from_graph(cls, data: dict) -> "AuthMethodConfig":
        return cls(id=data.get("id", ""), state=data.get("state", "disabled"))


class UserMfaRequirement(BaseModel):
    """Legacy per-user MFA state from /users/{id}/authentication/requirements."""

    user_principal_name: str | None = None
    display_name: str | None = None
    state: str = "disabled"              # disabled | enabled | enforced


# --------------------------------------------------------------------------- #
# Result shapes
# --------------------------------------------------------------------------- #

class Severity(str, Enum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"

    @property
    def rank(self) -> int:
        return {"info": 0, "low": 1, "medium": 2, "high": 3}[self.value]


class AffectedUser(BaseModel):
    """A user implicated in a finding, with the detail relevant to that rule."""

    user_principal_name: str | None = None
    display_name: str | None = None
    detail: str | None = None                     # e.g. "last sign-in 2024-01-03" or license list
    monthly_cost_usd: float | None = None


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    title: str
    description: str
    recommendation: str
    affected_users: list[AffectedUser] = Field(default_factory=list)
    estimated_monthly_savings_usd: float = 0.0
    notes: list[str] = Field(default_factory=list)   # caveats, e.g. price-map gaps

    @property
    def estimated_annual_savings_usd(self) -> float:
        return round(self.estimated_monthly_savings_usd * 12, 2)

    @property
    def affected_count(self) -> int:
        return len(self.affected_users)


class SkuInventoryRow(BaseModel):
    """A row of the license-inventory report (SKU + pricing + usage)."""

    sku_part_number: str
    display_name: str
    purchased: int
    assigned: int
    slack: int
    unit_price_usd: float | None = None
    price_known: bool = True
    is_unlimited: bool = False   # free/self-service SKU (excluded from totals)

    @property
    def monthly_cost_usd(self) -> float | None:
        if self.unit_price_usd is None:
            return None
        return round(self.unit_price_usd * self.purchased, 2)

    @property
    def slack_monthly_usd(self) -> float | None:
        if self.unit_price_usd is None:
            return None
        return round(self.unit_price_usd * self.slack, 2)


class TenantData(BaseModel):
    """Everything fetched from a tenant — the input to every rule."""

    organization: Organization
    tenant_id: str
    skus: list[SubscribedSku] = Field(default_factory=list)
    subscriptions: list[Subscription] = Field(default_factory=list)
    users: list[User] = Field(default_factory=list)
    user_registration: list[UserRegistration] = Field(default_factory=list)
    directory_roles: list[DirectoryRole] = Field(default_factory=list)
    ca_policies: list[ConditionalAccessPolicy] = Field(default_factory=list)
    named_locations: list[NamedLocation] = Field(default_factory=list)
    auth_methods: list[AuthMethodConfig] = Field(default_factory=list)
    per_user_mfa: list[UserMfaRequirement] = Field(default_factory=list)
    # Usage-report rows (populated only when experimental rules are enabled).
    active_user_detail: list[dict] = Field(default_factory=list)
    mailbox_usage_detail: list[dict] = Field(default_factory=list)
    teams_activity_detail: list[dict] = Field(default_factory=list)
    onedrive_usage_detail: list[dict] = Field(default_factory=list)
    # Data-quality flags surfaced in the report.
    sign_in_activity_available: bool = True
    subscriptions_available: bool = True
    mfa_data_available: bool = True
    roles_available: bool = True
    ca_available: bool = True
    named_locations_available: bool = True
    auth_methods_available: bool = True
    per_user_mfa_available: bool = True
    report_names_concealed: bool = False


class AuditResult(BaseModel):
    """Canonical audit output. Every report writer serializes this and only this."""

    tenant_display_name: str
    tenant_id: str
    generated_at: datetime
    findings: list[Finding] = Field(default_factory=list)
    inventory: list[SkuInventoryRow] = Field(default_factory=list)
    total_purchased: int = 0
    total_assigned: int = 0
    caveats: list[str] = Field(default_factory=list)
    # Subscription expiration data (exported as its own report section).
    subscriptions: list[Subscription] = Field(default_factory=list)
    subscriptions_available: bool = True   # False if the endpoint was unavailable
    # Maps a license skuId (GUID) -> friendly product name, so any raw GUID
    # reference (e.g. the raw-data sheet) can be shown in human-readable form.
    sku_id_to_name: dict[str, str] = Field(default_factory=dict)
    # Retained for the hidden "raw data" sheet / json export.
    tenant_data: TenantData | None = None

    def expiration_summary(self) -> dict[str, int]:
        """Counts of subscriptions by expiry proximity (relative to generated_at)."""
        now = self.generated_at
        counts = {"expired": 0, "within_30": 0, "within_60": 0, "within_90": 0, "total": 0}
        for s in self.subscriptions:
            counts["total"] += 1
            if s.is_expired(now):
                counts["expired"] += 1
            elif s.is_expiring_within(now, 30):
                counts["within_30"] += 1
            elif s.is_expiring_within(now, 60):
                counts["within_60"] += 1
            elif s.is_expiring_within(now, 90):
                counts["within_90"] += 1
        return counts

    @property
    def report_date(self) -> date:
        return self.generated_at.date()

    @property
    def total_monthly_savings_usd(self) -> float:
        return round(sum(f.estimated_monthly_savings_usd for f in self.findings), 2)

    @property
    def total_annual_savings_usd(self) -> float:
        return round(self.total_monthly_savings_usd * 12, 2)

    def severity_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts

    def base_filename(self) -> str:
        """Filesystem-safe `{tenant}_{YYYY-MM-DD}` base for output files."""
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.tenant_display_name)
        safe = "_".join(safe.split()) or "tenant"
        return f"{safe}_{self.report_date.isoformat()}"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Graph returns ISO-8601 with a trailing Z
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
