# M365 License Review

A **read-only** Microsoft 365 license review & optimization tool for MSPs. A
human operator authenticates interactively into one client tenant, and the tool
analyzes license assignment vs. usage and produces a client-ready optimization
report — in **Word (.docx)**, **Excel (.xlsx)**, and **JSON**.

It ships as a **Docker image** with two entry points over one shared engine:

- a **web app** — the operator opens `http://localhost:8000`, signs in, and downloads the report;
- a **CLI** — the same audit for scripting/automation.

> **Read-only by design.** The tool requests only read scopes and makes only
> `GET` calls to Microsoft Graph — enforced by a runtime guard that hard-fails on
> any other method. It never changes anything in a tenant.

---

## Quick start

You need **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** (or Docker Engine). No Python, no manual config.

### Easiest — one command

```powershell
# Windows (PowerShell)
./run.ps1
```
```bash
# macOS / Linux
./run.sh
```

This checks Docker, starts the tool, waits until it's healthy, and opens
`http://localhost:8000` in your browser. First run builds the image (~2 min);
after that it's instant.

### Or with Docker Compose directly

```bash
docker compose up -d          # build + start (first run), then open http://localhost:8000
docker compose down           # stop
```

There's **nothing to configure**: the session secret is auto-generated on first
start, and you enter (or save) the Azure client ID in the web UI. Reports are
written to `./reports/`, saved profiles to `./data/` — both persist on your machine.

### Using the prebuilt image (no local build)

Once a release is published, pull the image instead of building:

```bash
# set once
export M365_IMAGE=ghcr.io/samuelgtetteh/m365-license-review:latest   # PowerShell: $env:M365_IMAGE="..."
docker compose pull
docker compose up -d
```

### CLI

The CLI runs inside the container — see the in-app **Help** page (`/help`) for the
full guide. Quick version:

```bash
docker compose run --rm m365-review m365-review run --profile "Contoso" --tenant contoso.com
docker compose run --rm m365-review m365-review profiles list
```

### Running from source (development)

```bash
pip install -e ".[dev]"
uvicorn m365_review.web.app:app --reload      # web
m365-review run                                # CLI (uses your browser to sign in)
pytest -q                                      # tests
```

Requires **Python 3.11+**.

---

## Azure AD app registration (one-time, by the MSP)

The tool needs **one** multi-tenant app registration in the MSP's own Azure AD
tenant, reused for every client.

1. **Azure Portal → App registrations → New registration.**
2. **Supported account types:** *Accounts in any organizational directory (multitenant).*
3. **Authentication → Add a platform → Mobile and desktop applications** — add the
   custom redirect URI `http://localhost:8000/auth/callback` (must match
   `AZURE_REDIRECT_URI`). Then **Allow public client flows → Yes**.
   > ⚠️ Use **Mobile and desktop applications**, *not* Web. This app is a public
   > client with no secret; a **Web** redirect would fail token exchange with
   > `AADSTS7000218` (client secret required).
4. **API permissions → Microsoft Graph → Delegated**, add (read-only):
   - `User.Read`
   - `Directory.Read.All`
   - `User.Read.All`
   - `Organization.Read.All`
   - `AuditLog.Read.All` (sign-in activity)
   - `Reports.Read.All` (usage reports)
5. Copy the **Application (client) ID** into `.env` as `AZURE_APP_CLIENT_ID`.
   **There is no client secret** — the flow is public-client + PKCE.

The first time the tool runs against a new client tenant, the signed-in client
admin sees a consent screen listing these scopes and approves once. That consent
screen is the client's audit trail; the tool does not bypass it.

**Full step-by-step (with the exact portal clicks and every AADSTS error and its
fix): [docs/AZURE_SETUP.md](docs/AZURE_SETUP.md).**

---

## How it works

```
Operator → web/CLI → auth (MSAL, auth-code+PKCE) → Graph (GET only)
                                                      → fetch org / SKUs / users
                                                      → rules engine (R1–R3)
                                                      → AuditResult
                                                      → .docx / .xlsx / .json
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

### Rules in v1

| Rule | Finding |
|------|---------|
| **R1** | Licenses assigned to disabled users |
| **R2** | Licenses on users with no sign-in in 90 days (degrades gracefully without Azure AD P1) |
| **R3** | Unassigned purchased licenses (owned − assigned) |

Rules R4–R7 (duplicate SKUs, E5 under-use, oversized shared mailboxes, licensed
guests) are planned; experimental ones will be gated behind
`--enable-experimental-rules`.

### The report

Every format leads with a **License Optimization Summary** — prioritized
recommendations with estimated monthly and annual savings — followed by
per-finding detail and a full license inventory. The Excel workbook adds a
hidden raw-data sheet for auditability.

---

## SKU pricing

Savings are computed from `config/sku_prices.yaml` (monthly per-user USD, keyed
by `skuPartNumber`). It ships seeded with **Microsoft public list prices** —
**replace these with your CSP/partner rate card** and update quarterly.
`m365-review sku-check` lists a tenant's SKUs and flags any missing from the map.

`config/sku_display_names.yaml` maps part numbers to readable product names
(e.g. `FLOW_FREE` → "Microsoft Power Automate Free"). It's generated from
Microsoft's official "Product names and service plan identifiers" reference and
ships with ~600 SKUs; refresh it any time with:

```bash
python scripts/update_sku_names.py
```

Any SKU not in the map is prettified (e.g. `SOME_NEW_ADDON` → "Some New Addon")
so reports never show raw identifiers. `config/sku_overlaps.yaml` feeds the
(planned) duplicate-license rule.

---

## Reproducibility

The `notebooks/` directory demonstrates the entire pipeline against **synthetic
fixtures** (no live tenant required), so anyone can reproduce the analysis:

```bash
pip install -e ".[dev]"
jupyter lab notebooks/
```

---

## Security

- **Read-only:** only read scopes requested; `graph_client` refuses any non-GET method.
- **Tokens** live in memory for the run only — never logged, written to disk, or included in reports; the web session drops the token as soon as the audit finishes.
- **Secrets:** `.env` is git-ignored (only `.env.example` is committed).
- **Reports contain client PII** (names, UPNs, sign-in dates). They are git-ignored — **store them in an access-controlled location.**
- **Notebooks** run only on synthetic fixtures, with outputs stripped before commit.
- The container runs as a non-root user.

This tool is intended to run **locally** (localhost, one tenant per session). A
shared/hosted deployment would need operator authentication, session-isolation
review, and TLS — out of scope for v1.

---

## Releasing (maintainers)

Publishing a versioned image to GHCR is automated by
[`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml):

```bash
git tag v0.1.0
git push origin v0.1.0
```

The workflow builds a multi-arch image and pushes it to
`ghcr.io/samuelgtetteh/m365-license-review` tagged with the version and `latest`. Then anyone can
run the tool with `docker compose pull && docker compose up -d` (see
[Using the prebuilt image](#using-the-prebuilt-image-no-local-build)).

First publish only: on GitHub, make the GHCR package **public** (Packages →
package → Package settings → Change visibility) so users can pull without auth.
No secrets to configure — the workflow uses the built-in `GITHUB_TOKEN`.

## License

MIT — see [LICENSE](LICENSE).
