# Phase 2 roadmap — selectable security & identity posture audits

Expands the tool from license optimization into a **security & identity posture
auditor**, driven by XL.net's audit runbooks (`office Audit Tool VS Code/`), with
the headline UX change: **every audit is a checkbox the operator selects**.

Target release: **v0.4.0**. Status legend: `planned` · `in progress` · `done`.

---

## Locked decisions (from planning)

1. **Selectable audits** — the operator ticks which audits to run; the tool runs
   only those and fetches only the data/scopes they need.
2. **`Policy.Read.All`** — **added** (read-only). Unlocks the Conditional Access,
   auth-methods-policy, named-locations, and legacy per-user-MFA-state audits.
3. **Legacy per-user MFA state** — **automatable** via
   `GET /users/{id}/authentication/requirements` → `perUserMfaState`
   (disabled/enabled/enforced), permission `Policy.Read.All`. It's a per-user call,
   so it runs only when that audit is selected (throttling handled by graph_client).
4. **Exchange Online** — built into the tool as a **clickable card/action** ("Run
   Exchange Online check") that performs the shared-mailbox sign-in audit, rendered
   into a results page/section.
5. **On-prem AD** — delivered as an **agent tool**: a self-contained PowerShell
   script the operator runs on a domain controller (via RMM/LiveConnect); it emits
   JSON/CSV that the web tool **imports** and formats into the report. The container
   never touches on-prem AD directly.

---

## The selectable-audit framework (Phase 0 — the backbone)

Everything else plugs into this.

- **Audit catalog.** Each audit is a registered entry: `id`, `title`, `category`,
  `description`, `required_scopes`, `required_data` (which fetchers), `severity_hint`,
  `experimental`. Existing rules (R1–R10) become catalog entries; new posture checks
  join the same catalog.
- **Web UI.** A **"Select audits" tab** with checkboxes grouped by category
  (Licensing & cost · Identity & access · Security posture · Exchange · On-prem),
  plus select-all / per-category toggles. Each item shows a small badge when it needs
  an extra permission (e.g. `Policy.Read.All`).
- **Scope-aware sign-in.** Selection happens **before** sign-in, so `/auth/login`
  requests **exactly the scopes the selected audits need** — a licensing-only run
  never prompts for `Policy.Read.All`.
- **Engine.** `run_audit(selected_ids)` fetches only the data those audits require,
  runs only those audits, and the report includes only them.
- **CLI.** `--audit <id>` (repeatable), `--category <name>`, `--all`; `profiles`
  can store a default audit set per client.

Acceptance: selecting only "Licensing" runs with the current scopes and no CA calls;
selecting a CA audit adds `Policy.Read.All` to the consent and the CA fetch.

---

## Audit catalog

| ID | Audit | Category | Data source | Extra scope | Phase | Status |
|----|-------|----------|-------------|-------------|-------|--------|
| lic-disabled (R1) | Disabled users with licenses | Licensing | subscribedSkus, users | — | have | ✅ |
| lic-inactive (R2) | Inactive licensed users (90d) | Licensing | users signInActivity | — | have | ✅ |
| lic-unassigned (R3) | Unassigned purchased licenses | Licensing | subscribedSkus | — | have | ✅ |
| lic-duplicate (R4) | Duplicate/overlapping licenses | Licensing | users, overlaps | — | have | ✅ |
| lic-expirations (R8) | Expiring subscriptions | Licensing | /directory/subscriptions | — | have | ✅ |
| idn-guests (R7) | Licensed guest users | Identity | users | — | have | ✅ |
| idn-mfa-registration (R9) | Users without MFA registered | Identity | userRegistrationDetails | — | have → enrich | ⚙️ |
| idn-admin-audit (R10) | Admins w/o MFA, too many GAs | Identity | directoryRoles, registration | — | have → CA-aware | ⚙️ |
| idn-peruser-mfa-state | Legacy per-user MFA state | Identity | users/{id}/authentication/requirements | Policy.Read.All | 1 | planned |
| sec-ca-require-mfa-all | CA requires MFA (all users) | Security posture | conditionalAccess/policies | Policy.Read.All | 1 | planned |
| sec-ca-block-legacy | CA blocks legacy auth | Security posture | conditionalAccess/policies (+ signIns) | Policy.Read.All | 1 | planned |
| sec-auth-methods-policy | Auth-methods policy vs baseline | Security posture | policies/authenticationMethodsPolicy | Policy.Read.All | 1 | planned |
| sec-trusted-locations | Trusted / named locations review | Security posture | conditionalAccess/namedLocations | Policy.Read.All | 1 | planned |
| sec-ga-mfa-coverage | Global-admin MFA coverage | Security posture | roles + per-user MFA + CA | Policy.Read.All | 1 | planned |
| sec-allowed-domains | Verified / accepted domains | Security posture | /organization, /domains | — | 2 | planned |
| exo-shared-mbx-signin | Shared mailboxes with sign-in on | Exchange | Exchange Online + users | (EXO) | 3 | planned |
| ad-inactive-accounts | Inactive on-prem AD accounts | On-prem | Get-ADUser (agent) → import | (on-prem) | 4 | planned |

Future/back-burner: R5 (E5 under-use), R6 (shared-mailbox size), all-users stale sweep.

---

## Phases

### Phase 0 — Selectable-audit framework ✅ DONE
Audit-catalog model; "Select audits" checkboxes; scope-aware `/auth/login`; engine
runs only selected audits and fetches only their data; CLI `--audit`/`--category` +
`audits` command. Tests for catalog + scope computation. *(shipped to master)*

### Phase 1 — Conditional Access & policy audits (adds `Policy.Read.All`) ✅ DONE
Fetchers: `conditionalAccess/policies`, `conditionalAccess/namedLocations`,
`policies/authenticationMethodsPolicy`, `users/{id}/authentication/requirements`.
Audits: `sec-ca-require-mfa-all`, `sec-ca-block-legacy`, `sec-auth-methods-policy`,
`sec-trusted-locations`, `sec-ga-mfa-coverage`, `idn-peruser-mfa-state`.
Each: pass/fail + evidence (policy name, targeted users, exclusions), graceful 403
note if the scope wasn't consented. Update `AZURE_SETUP.md` (new scope). Fixtures + tests.

### Phase 2 — Domains + richer MFA ✅ DONE
`sec-allowed-domains` (R17 — verified/accepted domains, flags unverified/federated).
Enriched MFA registration (default method, methods registered, SSPR, passwordless,
system-preferred) surfaced in the Excel MFA detail sheet.

### Phase 3 — Exchange Online (clickable card)
Read-only EXO integration (delegated). A **card/action** "Run Exchange Online check"
→ `exo-shared-mbx-signin` (shared mailboxes with sign-in enabled) → results
page/section. Detection only — the tool stays read-only (no disabling sign-in).
Isolated in an `exchange` provider module so Graph stays clean.

### Phase 4 — On-prem AD agent tool
Ship `agents/ad-inactive-accounts.ps1` (self-contained; `Get-ADUser -Filter
'enabled -eq $true'` + LastLogonDate + description → JSON). The operator runs it on
a DC via RMM/LiveConnect; the web tool gets an **Import** action that ingests the
JSON and formats it into the report (with the Disable/Keep/Research action column
from the runbook). No live AD connectivity from the container.

### Phase 5 — Posture scorecard + reporting
These are pass/fail checks, so add a **Security Posture** report section and a
scorecard ("X of Y checks passed", per-audit status) across xlsx/docx/json, plus a
results tab. Findings still flow into the optimization summary where relevant.

### Phase 6 — Release v0.4.0
Version bump; CHANGELOG; docs (checkboxes, new scope, EXO card, AD agent);
CI green; commit/push/tag → GHCR.

### Phase 7 — Analytics & trends
Builds on the selectable audits and the existing SQLite store.

- **In-report analytics** (extends current): license **utilization %** per SKU + overall,
  **savings breakdown** charts (by SKU and by category), **cost-at-risk** from expiring
  subscriptions (30/60/90), and the **security posture score** (X of Y checks passed —
  shared with Phase 5).
- **Run-snapshot store (keystone).** Persist each run's `AuditResult` summary to a new
  `audit_runs` table (keyed by profile + date). Everything below depends on this.
- **Per-client trends.** Savings-identified-over-time, MFA coverage %, admin count,
  findings-by-severity over time, and **"since last audit"** deltas (new / resolved
  findings, newly-expiring subs).
- **MSP fleet analytics.** Aggregate across all client profiles: total savings identified,
  MFA-coverage leaderboard, clients missing block-legacy-auth / with too many Global
  Admins, and per-client benchmark vs. fleet average.
- **Web `/analytics` dashboard + BI export.** In-app charts (per-client trend + fleet
  rollup) and a flattened CSV / Power BI-friendly export.

**Sequencing:** the snapshot store is the prerequisite for trends/fleet. Slot Phase 7
**after the audit phases (1–3)** so there's meaningful data to trend, but the in-report
analytics + posture score can land alongside Phase 5. Can be pulled earlier if desired.

Data/privacy note: snapshots are summaries (counts, totals, coverage %), stored locally
in the same git-ignored SQLite DB as profiles — no new PII beyond what reports already hold.

---

## New scope & setup impact

- **`Policy.Read.All`** added to the requestable scope set (requested only when a
  Policy-dependent audit is selected). `AZURE_SETUP.md` gets a note; existing clients
  re-consent the first time they run a Policy audit.
- Exchange Online audit requires the signed-in admin to hold an Exchange/Global
  admin role; documented on the EXO card.

## Data-source notes / gotchas

- **Per-user MFA state** is one call per user → only run when selected; rely on
  existing 429/backoff handling; consider a progress note for large tenants.
- **`authenticationMethodsPolicy`** returns enabled methods + config → compare
  against a shipped **baseline** (configurable yaml) to judge "aligned".
- **Block-legacy-auth**: verify a CA policy with `clientAppTypes` = legacy
  (exchangeActiveSync, other) + `grantControls` = block + broad user scope; optionally
  cross-reference actual legacy sign-ins from `auditLogs/signIns` (AuditLog.Read.All).
- **Shared mailboxes**: Graph can't list them; use Exchange Online. Keep it read-only.
- **On-prem AD**: not reachable from the container — agent script + import only.

## Testing & versioning

- Every new audit ships with synthetic fixtures + tests (pattern already in place).
- CI must stay green; image publish stays gated on tests.
- Ship as **v0.4.0** once Phases 0–3 land; on-prem agent (Phase 4) and posture
  scorecard (Phase 5) can follow in 0.4.x if needed.

## Build order (start here)

1. **Phase 0** (framework) — nothing else can be "selectable" without it.
2. **Phase 1** (CA/policy + per-user MFA state) — the core of the reference docs.
3. **Phase 2** (domains + MFA enrich).
4. **Phase 3** (Exchange card).
5. **Phase 5** (posture scorecard) + **Phase 7** in-report analytics / snapshot store.
6. **Phase 4** (AD agent).
7. **Phase 7** per-client trends + fleet dashboard (needs a few runs of snapshot data).
8. **Phase 6** — release v0.4.0 (cut once Phases 0–3 land; analytics can follow in 0.4.x/0.5.0).
