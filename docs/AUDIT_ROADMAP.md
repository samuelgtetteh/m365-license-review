# Audit roadmap

Planned and proposed audit checks for M365 License Review, with priority, effort,
and Graph-scope impact. This is the "what's next" tracker — update the **Status**
column as items move. No client data belongs in this file.

**Status:** `planned` · `in progress` · `done` · `deferred`
**Effort:** S (hours) · M (a day) · L (multi-day / false-positive-prone)
**New scope?** whether it needs a delegated Graph scope we don't already request
(current scopes: `User.Read`, `Directory.Read.All`, `User.Read.All`,
`Organization.Read.All`, `AuditLog.Read.All`, `Reports.Read.All`).

---

## Immediate next: License / subscription expirations (EXP)

**Goal (from request):** surface subscription expiration & renewal dates and
**export them separately** in all three formats (.xlsx / .docx / .json).

**Data source:** `GET /directory/subscriptions` → `companySubscription` objects:
`skuId`, `skuPartNumber`, `status`, `totalLicenses`, `createdDateTime`,
`nextLifecycleDateTime` (next renewal or expiry), `isTrial`. Scope: already have.
*Caveat:* currently a **beta** endpoint — fetcher calls the beta base URL and
degrades to "expiration data unavailable" (a report note) if it 404s.

**Plan:**
1. `core/models.py` — new `Subscription` model: `sku_part_number`, `display_name`
   (via pricing), `status`, `total_licenses`, `created_datetime`,
   `next_lifecycle_datetime`, `is_trial`; derived `days_until_expiry`,
   `is_expired`, `is_expiring_within(days)`. Add `subscriptions: list[Subscription]`
   to `TenantData` and an `expirations` list to `AuditResult`.
2. `core/graph_client.py` — allow a beta base URL (e.g. `get_json(path, beta=True)`).
3. `core/fetchers/subscriptions.py` — `fetch_subscriptions(gc)`; map to models;
   graceful empty/unavailable handling.
4. `core/engine.py` — fetch subscriptions; build the expirations dataset + a small
   summary (counts expiring in 30/60/90 days, next expiry date, expired count).
5. **Separate export in each writer:**
   - **xlsx** — new `Subscription Expirations` sheet: Product · SKU · Status ·
     Licenses · Created · Renews/Expires · Days remaining · Trial? — red for
     expired, amber for < 30 days.
   - **docx** — new "Subscription expirations" section with the same table.
   - **json** — new top-level `subscription_expirations` block (+ summary).
6. Optional finding **R8 — "Subscriptions expiring soon"** in the optimization
   summary (severity by proximity; also flag expired-but-still-consuming).
7. Fixtures (`tests/fixtures/subscriptions.json`) + tests + a notebook cell.

**Status:** planned (next build)

---

## Backlog (prioritized)

| ID | Check | Category | Value | Effort | New scope? | Status |
|----|-------|----------|-------|--------|-----------|--------|
| EXP | Subscription expiration / renewal dates (separate export) | Licensing | High | M | No | planned (next) |
| R4  | Duplicate / overlapping SKUs on one user | Licensing | High | S | No | planned |
| LIC-GRP | Group-based license assignment **errors** (`licenseAssignmentStates`) | Licensing | High | S | No | planned |
| GUEST/R7 | Licensed & stale guest users | Identity/Cost | High | S | No | planned |
| STALE | Inactive / never-signed-in accounts (all, not just licensed) | Identity | High | S | No (P1-gated) | planned |
| MFA | Users without MFA registered | Security | High | M | Maybe¹ | planned |
| ADMIN | Privileged-role audit (Global Admin count, admins w/o MFA) | Security | High | M | Maybe² | planned |
| LIC-SVC | Disabled service plans inside assigned SKUs (paying for off features) | Licensing | Med | M | No | planned |
| R6  | Shared mailboxes > 50 GB needing a license | Compliance | Med | M | No | planned |
| TRIAL | Trial subscriptions about to expire/convert | Licensing | Med | S | No | planned (folds into EXP) |
| R5  | E5/premium under-use → downgrade candidates | Cost | High | L | No | deferred (experimental) |
| LEGACYAUTH | Legacy-authentication sign-ins | Security | High | M | No | planned |
| MBX-QUOTA | Mailboxes nearing quota / archive candidates | Capacity | Med | M | No | planned |
| OD-QUOTA | OneDrive storage nearing quota | Capacity | Med | M | No | planned |
| SEC-DEFAULTS | Security defaults on/off; CA policy coverage | Posture | High | M | **Yes³** | deferred |

¹ MFA registration via `reports/authenticationMethods/userRegistrationDetails` — covered by `AuditLog.Read.All`/`Reports.Read.All` we already have; confirm at build.
² Roles via `/directoryRoles` + members — covered by `Directory.Read.All`; `RoleManagement.Read.Directory` is cleaner if we add it.
³ `/policies/*` needs `Policy.Read.All` — a new scope requiring re-consent per client.

---

## Cross-cutting patterns to keep

- **Separate, clearly-labeled export sections** (like EXP) for each new data domain,
  in all three formats — don't bury new data inside existing sheets.
- **Read-only, GET-only** always; never add a write scope.
- **Friendly names everywhere**; free vs. paid separation preserved.
- **Graceful degradation** when a scope/endpoint/edition (P1, beta) is unavailable —
  emit a report caveat, never crash.
- **Fixtures + tests + a notebook cell** for every new check (reproducibility).
- When a check needs a **new Graph scope**, document it in `AZURE_SETUP.md` and warn
  the operator (re-consent required per client).

---

## Suggested build order

1. **EXP** — expiration dates + separate export (in progress next).
2. **R4** + **LIC-GRP** + **GUEST/R7** + **STALE** — quick, high-value, no new scope.
3. **MFA** + **ADMIN** + **LEGACYAUTH** — the security-posture batch (confirm scopes).
4. **LIC-SVC** + **R6** + capacity (**MBX-QUOTA**, **OD-QUOTA**).
5. **R5** (experimental) and **SEC-DEFAULTS/CA** (needs `Policy.Read.All`).
