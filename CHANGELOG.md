# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.1.0]: https://github.com/samuelgtetteh/m365-license-review/releases/tag/v0.1.0
