# Getting started

This guide takes you from nothing to a finished license report. There are two
one-time setups (install Docker, register one Azure app), after which each audit
takes a couple of minutes.

**Time:** ~15 minutes the first time; ~2 minutes per audit after that.

---

## Overview

```
[ One-time ]  1. Install Docker Desktop
              2. Register ONE Azure app (reused for every client)
              3. Start the tool

[ Each audit ] 4. Open the web app → pick/add the client → sign in → download the report
```

---

## Step 1 — Install Docker Desktop

Download and install from <https://www.docker.com/products/docker-desktop/>, then
**launch it** and wait until it says "Engine running". That's the only software
you need — no Python, nothing else.

---

## Step 2 — Register the Azure app (one time, done by the MSP)

The tool needs **one** app registration in **your own** Microsoft Entra (Azure AD)
tenant. It's multi-tenant, so any client admin can sign in through it. It is a
**public client with no secret**.

1. Go to <https://entra.microsoft.com> → **App registrations** → **New registration**.
2. **Name:** `M365 License Review`.
3. **Supported account types:** *Accounts in any organizational directory (multitenant)*.
4. Leave Redirect URI blank → **Register**.
5. Copy the **Application (client) ID** from the Overview page — you'll paste it into the tool later.
6. **Authentication** → **Add a platform** → **Mobile and desktop applications**.
   - Add this custom redirect URI **exactly**: `http://localhost:8000/auth/callback`
   - ⚠️ Use **Mobile and desktop applications**, *not* "Web" — this is a public
     client with no secret. (Using "Web" causes error `AADSTS7000218`.)
   - Set **Allow public client flows** → **Yes** → **Save**.
7. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated**,
   add these six (all read-only):
   `User.Read`, `Directory.Read.All`, `User.Read.All`, `Organization.Read.All`,
   `AuditLog.Read.All`, `Reports.Read.All`.

You do **not** need to "grant admin consent" in your own tenant — each client
admin consents for their tenant the first time they sign in.

> Full walkthrough with every error and its fix: [AZURE_SETUP.md](AZURE_SETUP.md).

---

## Step 3 — Start the tool

Pick **one** of the options below.

### Option A — Prebuilt image (recommended; no build, needs internet)

1. Download `docker-compose.yml` and the `config/` folder from the project (or
   clone the repo).
2. In that folder, tell it which image to use, then start:

   **Windows (PowerShell):**
   ```powershell
   $env:M365_IMAGE = "ghcr.io/samuelgtetteh/m365-license-review:latest"
   docker compose pull
   docker compose up -d
   ```
   **macOS / Linux:**
   ```bash
   export M365_IMAGE=ghcr.io/samuelgtetteh/m365-license-review:latest
   docker compose pull
   docker compose up -d
   ```

### Option B — One command (builds locally the first time)

Clone the repo, then from its folder:

- **Windows:** double-click `run.ps1`, or in PowerShell: `./run.ps1`
- **macOS / Linux:** `./run.sh`

This checks Docker, starts the tool, and opens your browser automatically.

### Option C — Plain Docker Compose (builds locally)

From the project folder:
```bash
docker compose up -d      # first run builds the image (~2 min)
```

### Option D — Offline / USB (no internet on the target machine)

On a machine that has the image, export it:
```powershell
docker save -o m365-license-review.tar m365-license-review:local
```
Copy `m365-license-review.tar`, `docker-compose.yml`, and `config/` to the USB.
On the target machine (Docker installed):
```powershell
docker load -i m365-license-review.tar
docker compose up -d
```

**All options end the same way:** the app is running at
<http://localhost:8000>. There's nothing to configure — the session secret is
generated automatically and the client ID is entered in the web page.

To stop it later: `docker compose down`.

---

## Step 4 — Run your first audit (web app)

1. Open <http://localhost:8000>.
2. **Choose the client:**
   - If you've audited this client before, pick it from the **saved profiles** dropdown.
   - Otherwise select **"Add a new profile"**, give it a name (e.g. the client's
     company name) and paste the **Application (client) ID** from Step 2. It's
     saved so you won't need to paste it again.
3. Leave the output formats checked (Excel, Word, JSON) and click
   **Sign in to a client tenant**.
4. You're sent to Microsoft — **sign in as the client's admin**. The first time
   for a new client, approve the read-only consent screen.
5. **Confirm the tenant** shown is the right client, then click **Proceed with audit**.
6. Watch the progress bar. When it finishes, **download** the report (any format,
   or all as a zip).

Reports are saved on your machine in the `reports/` folder as well.

> Need help while using it? The app has a built-in **Help** page at
> <http://localhost:8000/help>.

---

## Where things are stored

| What | Where | Notes |
|------|-------|-------|
| Generated reports | `reports/` | Contain client names/UPNs — store securely |
| Saved client profiles | `data/` (SQLite) | Stays on your machine; never shared |
| SKU prices | `config/sku_prices.yaml` | Public list prices by default — replace with your CSP rates |

---

## Keeping prices accurate

Savings are estimated from `config/sku_prices.yaml` (monthly USD per license).
It ships with Microsoft public list prices — **edit it with your CSP/partner
rates** for accurate figures. Product **names** update automatically from
Microsoft's official list; refresh them any time with
`python scripts/update_sku_names.py` (or they're already current in the image).

---

## Quick troubleshooting

| Symptom | Fix |
|---------|-----|
| `docker` not recognized | Docker Desktop isn't running / not on PATH. Start it; reopen the terminal. |
| Sign-in: "No reply address" (`AADSTS500113`) | Add `http://localhost:8000/auth/callback` under **Mobile and desktop applications** (Step 2.6). |
| Sign-in: "client_secret required" (`AADSTS7000218`) | The redirect was added under **Web**. Remove it and re-add under **Mobile and desktop applications**. |
| 403 during the audit | A client admin needs to approve the consent screen (the six read scopes). |
| Report totals look huge | Free/self-service SKUs are excluded from totals automatically; check you're on the latest image. |

More errors and fixes: [AZURE_SETUP.md](AZURE_SETUP.md) and the in-app Help page.

---

## Security at a glance

- **Read-only:** the tool only reads (GET) from Microsoft Graph and never changes a tenant.
- **No stored credentials:** access tokens live in memory for the run only.
- **Your data stays local:** reports, profiles, and the database never leave your machine (they're git-ignored and not in any shared image).
