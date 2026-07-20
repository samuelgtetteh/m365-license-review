# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — selectable audits (Phase 0) + security posture (Phase 1)
- **Selectable audits.** Every audit is now a catalog entry the operator ticks on
  the "Run audit" tab (grouped by category); the tool runs only the selected audits,
  fetches only the data they need, and **requests only the scopes they need**
  (a licensing-only run never prompts for `Policy.Read.All`). CLI: `--audit`,
  `--category`, and `m365-review audits` to list them.
- **Conditional Access & policy audits** (new `Policy.Read.All` scope): require-MFA-all
  (R11), block-legacy-auth (R12), global-admin MFA coverage (R15), auth-methods-policy
  alignment (R13), trusted/named-locations review (R14), and legacy per-user MFA state
  (R16, via `/users/{id}/authentication/requirements`). All degrade gracefully if the
  scope isn't consented.
- **Verified/accepted domains audit** (R17) — lists tenant domains, flags unverified
  or federated ones (Directory.Read.All).
- **Enriched MFA registration** — default method, methods registered, SSPR, passwordless,
  and system-preferred flags, surfaced in the Excel MFA detail sheet.

## [0.3.0] - 2026-07-16

### Added — identity-security audits
- **R9 — Users without MFA registered.** Member accounts with no registered MFA
  method (from `reports/authenticationMethods/userRegistrationDetails`).
- **R10 — Privileged role / admin audit.** Admins without MFA, and too many Global
  Administrators (from `/directoryRoles`).
- **R7 — Licensed guest users.** Guests holding licenses they usually don't need.
- New Excel detail sheets **Detail - MFA** and **Detail - Admin Roles**, plus an
  `identity_security` block in the JSON export. Everything degrades gracefully
  (and is noted in the report) if a tenant/admin can't return the data.
- **Tabbed home page** (Run audit · What we check · Reports · Command line ·
  Security) and a **light/dark theme toggle** that persists across pages.

All new checks use the read-only scopes already requested — no new consent.

## [0.2.0] - 2026-07-16

### Added
- **Subscription expirations** — new audit + a dedicated export section in every
  format (Excel sheet, Word section, JSON `subscription_expirations` block). Pulls
  renewal/expiry dates from `/directory/subscriptions`, flags expired / expiring-soon
  (rule **R8**), and degrades gracefully if the endpoint is unavailable.
- **R4 — duplicate/overlapping licenses** — flags users holding a SKU that a
  superset license already covers (data-driven via `config/sku_overlaps.yaml`).
- **Online pricing** — optional `PRICE_SOURCE_URL` fetches a rate card (JSON/CSV)
  at runtime, caches it, and falls back to the local yaml when offline. The report
  notes which source was used.
- **Report branding** — optional `REPORT_COMPANY_NAME` adds "Prepared by …"; the
  Excel summary gains a findings-by-severity pie chart.

### Changed / engineering
- **CI** now runs the test suite on every push/PR, and the image publish is gated
  on tests passing.
- Test coverage extended to the Graph client (GET-only guard, pagination, 429
  retry, 403 scope handling) — suite now at 45 tests.
- Added `SECURITY.md`, Dependabot, and issue/PR templates.

## [0.1.1] - 2026-07-16

### Added
- **Flexible port** — the app now builds its sign-in redirect URI from the port the
  browser actually uses, so it works on any host port. The `run.ps1` / `run.sh`
  launchers auto-pick a free port (8000 → 8080 → 8010 → …), and Compose honors a
  `HOST_PORT` override. Register the fallback ports' `…/auth/callback` URIs in the
  Azure app so sign-in works on whichever port is chosen.
- **Step-by-step Getting Started guide** (`docs/GETTING_STARTED.md`) — self-contained:
  a single `docker run` gets the tool running with no files to download.

## [0.1.0] - 2026-07-16

Initial release.

### Added
- **Read-only M365 license review** over Microsoft Graph (GET-only, enforced by a
  transport-layer guard). Requests only delegated read scopes.
- **Web app** (FastAPI): named-profile picker, browser sign-in (auth code + PKCE),
  tenant confirmation, live progress, and report download.
- **CLI** (`m365-review`): `run`, `sku-check`, and `profiles` (list/add/remove/show),
  with `--profile`, `--client-id`, `--tenant`, and device-code sign-in for headless use.
- **Rules engine** — R1 (licenses on disabled users), R2 (90-day inactive, with a
  graceful no-P1 fallback), R3 (unassigned/slack licenses).
- **Reports** in **.xlsx**, **.docx**, and **.json**, each led by a dedicated
  License Optimization Summary, with paid vs. free licenses shown separately.
- **Friendly product names** everywhere, sourced from Microsoft's official
  "product names and service plan identifiers" list (`scripts/update_sku_names.py`);
  unknown SKUs are prettified rather than shown as raw identifiers.
- **Saved profiles** in SQLite (name → client ID), persisted on a mounted volume.
- **Packaging**: Docker image, one-command launchers (`run.ps1` / `run.sh`),
  auto-generated session secret (no manual `.env`), and a GitHub Actions workflow
  that publishes the image to GHCR on version tags.

### Notes
- Free / self-service SKUs (10,000+ default quota) are excluded from license totals
  and the unused-license check.
- Inactive/disabled subscriptions (suspended/deleted/locked-out) are excluded from
  the report; expired-but-in-grace seats are counted.
- Device-code sign-in requires "Allow public client flows" on the app registration
  and a tenant-specific authority; tenants that block device code via Conditional
  Access should use the web app.

[0.3.0]: https://github.com/samuelgtetteh/m365-license-review/releases/tag/v0.3.0
[0.2.0]: https://github.com/samuelgtetteh/m365-license-review/releases/tag/v0.2.0
[0.1.1]: https://github.com/samuelgtetteh/m365-license-review/releases/tag/v0.1.1
[0.1.0]: https://github.com/samuelgtetteh/m365-license-review/releases/tag/v0.1.0
