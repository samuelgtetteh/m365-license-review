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
| **Pricing** | `core/pricing.py` | Loads the SKU yaml maps; price + display-name (Microsoft's official names, ~600 SKUs, with a prettified fallback) + overlap lookups. |
| **Profiles** | `core/profiles.py` | SQLite store of saved `name → client ID` connection profiles (+ last-audited tenant). |
| **Rules** | `core/rules/*` | Pure functions `(TenantData) -> list[Finding]`. Registry in `rules/__init__.py`. |
| **Report** | `core/report/*` | One `AuditResult` → three writers (`xlsx`, `docx`, `json`), each led by a License Optimization Summary and splitting **paid vs. free** licenses. |
| **Orchestration** | `core/engine.py` | Ties it together: `TenantSession` → fetch → rules → `AuditResult` → files. |
| **Web** | `web/app.py`, `web/sessions.py` | Routes + in-memory session/token store; profile picker. |
| **CLI** | `cli.py` | `run` (`--profile`/`--client-id`/`--tenant`, interactive picker, device-code), `sku-check`, `profiles` (list/add/remove/show). |

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
- **Public client, no secret.** Auth-code flow uses PKCE. The redirect URI is
  derived from the port the browser actually uses (so the tool works on any host
  port); each port's `…/auth/callback` must be registered on the app. An explicit
  `AZURE_REDIRECT_URI` env var overrides this (for proxy/HTTPS deployments).
- The **session secret** is auto-generated and persisted to `data/.session_secret`
  if not supplied, so no manual configuration is needed.
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

**License classification (applied in `engine.build_result`):**
- **Free / self-service SKUs** (a ≥10,000 default quota, e.g. Power Automate Free,
  RMS ad-hoc) are excluded from purchased/assigned totals and from R3 — their
  phantom "slack" isn't reclaimable. They're shown in a separate inventory category.
- **Inactive subscriptions** (`capabilityStatus` suspended/deleted/locked-out) are
  excluded from totals, inventory, and rules, and named in a caveat.
- **"Purchased" = usable seats** = `enabled + warning` (grace-period seats count).
- Rules still resolve license *names* against the full SKU set, so a disabled user's
  license from an inactive subscription is still shown by name, not a raw GUID.

---

## 6. Output

One canonical `AuditResult` object is serialized by three independent writers,
each **led by a License Optimization Summary** and using friendly product names:

- **`.xlsx`** (openpyxl) — Summary, License Optimization, License Inventory
  (**paid vs. free** sections), per-rule detail sheets, hidden raw-data sheet.
- **`.docx`** (python-docx) — client-facing narrative: how-to-read, optimization
  summary + prioritized table, per-finding detail, paid/free inventory tables.
- **`.json`** — full structured result (with an `optimization_summary` block and
  `paid`/`free` inventory) for automation / trending.

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

## 10. Deployment & packaging

No manual configuration is required — the session secret auto-generates and the
client ID is entered in the UI. Ways to run:

```bash
# Simplest (published image, no files):
docker run -d -p 8000:8000 -v m365_data:/app/data ghcr.io/<owner>/m365-license-review:latest
# From the repo:
./run.ps1            # or ./run.sh — auto-picks a free host port, opens the browser
docker compose up -d # HOST_PORT overridable
# Offline: docker save / docker load, then docker run
```

- **Distribution:** a GitHub Action (`.github/workflows/docker-publish.yml`) builds a
  multi-arch image and pushes it to **GHCR** on each `v*` tag. See the README's
  "Releasing" section. `docs/GETTING_STARTED.md` is the end-user guide.
- Intended to run **locally** on an operator's machine (localhost, one tenant per
  session). A hosted multi-user deployment would need operator auth, session
  isolation review, and TLS — out of scope for v1.

---

## 11. Out of scope for v1

Multi-tenant batch runs, web dashboard/history, historical trending, automated
license changes, PSA/RMM/billing integration, GDAP auth, non-USD currency,
localization. (SQLite is used for saved connection profiles only — not for
audit-result history.) See `PROGRESS.md` for live build state.
