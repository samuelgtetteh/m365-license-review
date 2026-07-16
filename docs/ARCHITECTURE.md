# Architecture

M365 License Review is a **read-only** Microsoft 365 license-optimization tool
for MSPs. A human operator authenticates interactively into one client tenant
per run; the tool reads license, user, and usage data via Microsoft Graph, runs
a rules engine, and emits a client-ready report in three formats.

It ships as a **Docker image** exposing two entry points over one shared engine:
a **web app** (primary) and a **CLI** (automation/scripting).

---

## 1. High-level shape

```
                          ┌──────────────────────────────────────────┐
                          │             Docker container               │
                          │                                            │
  Operator's browser ───► │  web/  (FastAPI + Jinja2)   ┐              │
   http://localhost:8000  │                             │              │
                          │  cli.py (typer)             ├─► core/ ◄────┼──► Microsoft Graph
   Terminal / automation ►│                             │  engine      │    (v1.0, GET only)
                          │                             ┘              │
                          │                                            │
                          │  config/  (SKU yaml maps, read-only mount) │
                          │  reports/ (xlsx/docx/json, volume mount)   │
                          └──────────────────────────────────────────┘

  notebooks/  ── import core/, run against synthetic fixtures (no live tenant)
```

**Key principle:** `web/` and `cli.py` are thin. All real work — auth, HTTP,
fetching, rules, pricing, report generation — lives in `core/` and has no
dependency on FastAPI or typer. The notebooks and tests exercise `core/`
directly, which is what makes the tool reproducible.

---

## 2. Component map

| Layer | Module | Responsibility |
|-------|--------|----------------|
| **Config** | `settings.py` | Env/.env loading (pydantic-settings). Holds the **read-only** Graph scope list. |
| **Auth** | `core/auth.py` | MSAL public client (no secret). Auth-code+PKCE (web), interactive/device (CLI). Produces a `TenantSession`. |
| **HTTP** | `core/graph_client.py` | Async httpx wrapper: pagination, 429/5xx retry, **GET-only runtime guard**. |
| **Fetch** | `core/fetchers/*` | One module per Graph area: `organization`, `skus`, `users`, `reports`. |
| **Model** | `core/models.py` | Pydantic models for Graph payloads + the canonical `AuditResult`. |
| **Pricing** | `core/pricing.py` | Loads the SKU yaml maps; price + display-name + overlap lookups. |
| **Rules** | `core/rules/*` | Pure functions `(TenantData) -> list[Finding]`. Registry in `rules/__init__.py`. |
| **Report** | `core/report/*` | One `AuditResult` → three writers: `xlsx_writer`, `docx_writer`, `json_writer`. |
| **Orchestration** | `core/engine.py` | Ties it together: `TenantSession` → fetch → rules → `AuditResult` → files. |
| **Web** | `web/app.py`, `web/sessions.py` | Routes + in-memory session/token store. |
| **CLI** | `cli.py` | `run`, `sku-check` commands. |

---

## 3. Request / data flow (web)

```
 GET  /                     Index: audit options + "Sign in" + equivalent-CLI panel
 GET  /auth/login           begin_web_auth() → store flow dict in session → 302 to Microsoft
      └── Microsoft login + consent (client admin approves read-only scopes)
 GET  /auth/callback?...    complete_web_auth(flow, params) → TenantSession (token in memory)
 GET  /confirm              Show "Signed in to: {display name} ({tid})" + Proceed button
 POST /run                  engine.run_audit(session, options); progress streamed via SSE
 GET  /download/{id}        Serve xlsx / docx / json (or a zip of all selected)
 GET  /sku-check            List tenant SKUs, flag any missing from sku_prices.yaml
```

The `/confirm` step is a deliberate belt-and-suspenders guard: the operator
visually verifies the correct tenant before any audit runs.

**CLI flow** mirrors this without HTTP: `cli_interactive_auth()` →
`engine.run_audit()` → files on disk.

---

## 4. Authentication & tenancy

- **One** multi-tenant Azure AD app registration in the MSP's own tenant,
  reused across all clients. Its client ID is configured via
  `AZURE_APP_CLIENT_ID` (env, or an index-page override field).
- Authority is `https://login.microsoftonline.com/organizations` — never a
  hard-coded tenant ID. The audited tenant is identified *after* sign-in from
  the id-token `tid` claim.
- **Public client, no secret.** Auth-code flow uses PKCE; the redirect URI
  (`AZURE_REDIRECT_URI`, default `http://localhost:8000/auth/callback`) must be
  registered on the app.
- Each first-time client sign-in shows a consent screen listing the read-only
  scopes — this *is* the client's audit trail and is intentionally not bypassed.

### Read-only scopes (the only scopes ever requested)
`User.Read`, `Directory.Read.All`, `User.Read.All`, `Organization.Read.All`,
`AuditLog.Read.All`, `Reports.Read.All`.

---

## 5. Rules engine

Each rule is a pure function returning `Finding`s. A `Finding` carries
`rule_id`, `severity`, `title`, `description`, `affected_users`,
`estimated_monthly_savings_usd`, `recommendation`.

| Rule | v1? | Check |
|------|-----|-------|
| **R1** | ✅ | Licenses on disabled users |
| **R2** | ✅ | Licenses on users with no sign-in in 90 days (P1-gated; degrades gracefully) |
| **R3** | ✅ | Unassigned purchased licenses (owned − consumed) |
| **R4** | later | Duplicate/overlapping SKUs on one user (uses `sku_overlaps.yaml`) |
| **R5** | later (experimental) | E5 on users not using premium features |
| **R6** | later | Shared mailbox >50 GB with no Exchange license |
| **R7** | later (experimental) | Licensed guest users |

Experimental rules are gated behind `--enable-experimental-rules` / a UI toggle.

---

## 6. Output

One canonical `AuditResult` object is serialized by three independent writers:

- **`.xlsx`** (openpyxl) — Summary, Findings, per-rule detail sheets, license
  inventory, hidden raw-data sheet. Conditional formatting on severity.
- **`.docx`** (python-docx) — client-facing narrative: how-to-read intro,
  summary, findings table, per-rule detail sections.
- **`.json`** — the full structured result for machine consumption / v2 trending.

Files are named `{tenant_display_name}_{YYYY-MM-DD}.{ext}` and written to
`OUTPUT_DIR` (a mounted volume in Docker).

---

## 7. Graph API robustness (built into `graph_client.py`)

- Follow `@odata.nextLink` on every list endpoint (centralized, not per-fetcher).
- Honor `Retry-After` on 429; exponential backoff on 5xx.
- `/reports/*` return 302 to a signed blob + CSV — follow redirects, parse CSV.
- `signInActivity` is Azure AD P1+ only; on 403/missing, degrade to a
  `createdDateTime` heuristic and flag it in the report.
- Report data lags 24–72 h and UPNs may be anonymized ("concealed names") —
  both surfaced as report notes.
- Handles tiny tenants (1 user / 1 SKU) as first-class.

---

## 8. Security model

| Concern | Control |
|---------|---------|
| Write access | Only read scopes requested; `graph_client` **hard-fails on any non-GET method**. |
| Token handling | In memory only, per session; never logged (`TenantSession.__repr__` redacts), never written, never in reports. |
| Session (web) | Signed, httponly, samesite cookie (`SESSION_SECRET`); OAuth `state` for CSRF (validated by MSAL). |
| Secrets in git | `.env` git-ignored; only `.env.example` shipped. Public repo. |
| Report PII | Reports contain names/UPNs/sign-in dates → git-ignored; README mandates access-controlled storage. |
| Notebook leakage | Notebooks run on synthetic fixtures only; outputs stripped (`nbstripout`) before commit. |
| Non-root | Container runs as an unprivileged user. |

---

## 9. Reproducibility (notebooks)

`notebooks/` demonstrates that the whole pipeline reproduces deterministically
without a live tenant, by importing `core/` and feeding it committed synthetic
fixtures (`tests/fixtures/`):

1. `01_auth_walkthrough` — explains the auth flow (no real tokens).
2. `02_fetch_and_explore` — fetcher output shapes against fixtures.
3. `03_rules_engine` — each rule R1–R7 run on fixtures → findings.
4. `04_report_generation` — build real `.xlsx` / `.docx` / `.json` from fixtures.

Anyone cloning the repo can `jupyter lab` and re-run top-to-bottom.

---

## 10. Deployment

```bash
cp .env.example .env          # set AZURE_APP_CLIENT_ID + SESSION_SECRET
docker compose up --build     # → http://localhost:8000
# CLI (headless):
docker compose run --rm m365-review m365-review run --format xlsx --format json
```

Intended to run **locally** on an operator's machine (localhost, one tenant per
session). A hosted multi-user deployment would require additional operator
auth, session isolation review, and TLS — explicitly out of scope for v1.

---

## 11. Out of scope for v1

Multi-tenant batch runs, web dashboard/history, database/trending, automated
license changes, PSA/RMM/billing integration, GDAP auth, non-USD currency,
localization. See `PROGRESS.md` for live build state.
