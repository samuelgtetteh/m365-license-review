# Azure AD / Entra app registration — step by step

This guide walks an MSP through the **one-time** setup of the single app
registration the tool uses for every client tenant. It takes about 10 minutes.

**Key facts to understand before you start**

- You create **one** app registration in **your own (the MSP's) tenant**. It is
  *multitenant*, so any client's admin can sign in through it.
- The app is a **public client** and has **no client secret** (it uses the
  authorization-code flow with **PKCE**). This means there is no secret to store,
  rotate, or expire.
- Because it is a public client, the redirect URI must be registered under the
  **Mobile and desktop applications** platform — **not** "Web". Registering it
  under "Web" is the single most common mistake and produces error
  `AADSTS7000218` at sign-in (see [Troubleshooting](#troubleshooting)).
- The tool is **read-only**. It requests only the six delegated read scopes below.

---

## 1. Create the registration

1. Go to <https://entra.microsoft.com> → **Entra ID → App registrations → New registration**
   (or **portal.azure.com → Microsoft Entra ID → App registrations → New registration**).
2. **Name:** e.g. `M365 License Review`.
3. **Supported account types:** select
   **Accounts in any organizational directory (Any Microsoft Entra ID tenant – Multitenant)**.
4. Leave **Redirect URI** blank for now. Click **Register**.
5. On the **Overview** page, copy the **Application (client) ID** — you'll need it
   in step 4. (You do *not* need the directory/tenant ID.)

---

## 2. Add the redirect URI (public client)

1. Open **Authentication** in the left menu.
2. Click **Add a platform → Mobile and desktop applications**.
   > If you see the new "Authentication (Preview)" experience, the platform choices
   > are the same. The **"Allow public client flows"** toggle lives on the
   > **Settings** tab (older UI calls it "Advanced settings"). You can switch back to
   > the classic layout with the "switch to the old experience" link if you prefer.
3. In **Custom redirect URIs**, enter **exactly**:
   ```
   http://localhost:8000/auth/callback
   ```
   - `http` (not `https`), host `localhost`, port `8000`, path `/auth/callback`, no trailing slash.
   - It must match `AZURE_REDIRECT_URI` in your `.env`. If you run the tool on a
     different port, change both to match.
4. Click **Configure / Save**.
5. Still under **Authentication**, set **Allow public client flows → Yes** and **Save**.

> ⚠️ **Do not use the "Web" platform.** A Web redirect makes Entra require a client
> secret during token exchange, which this app does not send — you'll get
> `AADSTS7000218`. If you added it under Web by mistake, delete that entry and
> re-add it under **Mobile and desktop applications**.

---

## 3. Add API permissions (read-only)

1. Open **API permissions → Add a permission → Microsoft Graph → Delegated permissions**.
2. Add these six (search each by name):

   | Permission | Why |
   |------------|-----|
   | `User.Read` | Sign-in |
   | `Directory.Read.All` | Read directory (licenses, users) |
   | `User.Read.All` | Read all users |
   | `Organization.Read.All` | Tenant name / verified domains |
   | `AuditLog.Read.All` | Sign-in activity (for the inactivity rule) |
   | `Reports.Read.All` | Usage reports |

3. You do **not** need to click "Grant admin consent" in your own tenant — each
   **client** admin consents for their own tenant the first time they sign in
   (see step 5). Granting in your tenant is optional and only affects your tenant.

---

## 4. Give the client ID to the tool

Pick whichever fits your workflow:

- **`.env`** (default for a single app):
  ```
  AZURE_APP_CLIENT_ID=<the Application (client) ID from step 1>
  ```
- **Web UI:** paste it on the home page before signing in.
- **Saved profile:** save it once under a name (e.g. the client's name) and reuse
  it by name on later runs — no need to paste it again.

---

## 5. What the client admin sees (per tenant)

The first time you audit a new client tenant, the client's admin (whoever signs
in) is shown a **consent screen** listing the six read-only scopes. They approve
once; subsequent runs for that tenant won't prompt again. This consent is the
client's audit trail and is intentional — the tool never bypasses it.

The signing-in account must be able to consent. If your clients restrict user
consent, a client **admin** must sign in (or grant admin consent for the app in
their tenant).

---

## Troubleshooting

| Error / symptom | Cause | Fix |
|-----------------|-------|-----|
| **AADSTS500113** — No reply address is registered for the application | The redirect URI isn't registered on the app | Add `http://localhost:8000/auth/callback` (step 2). Wait ~1 min. |
| **AADSTS7000218** — request body must contain `client_assertion` or `client_secret` | Redirect URI was registered under the **Web** platform, which requires a secret | Delete it from Web; add it under **Mobile and desktop applications** (step 2). No code change needed. |
| **AADSTS50011** — redirect URI mismatch | The URI on the app doesn't exactly match what the tool sent | Make the app's redirect URI and `AZURE_REDIRECT_URI` byte-for-byte identical (scheme, port, path, no trailing slash). |
| **AADSTS650057** / invalid resource | Permissions not added | Add the six delegated Graph scopes (step 3). |
| **403 Forbidden during the audit** (after sign-in works) | A required scope wasn't consented in the client tenant | Have the client admin sign in again and approve the consent screen; confirm all six scopes are present. |
| **AADSTS90002** — tenant not found | n/a for normal use | Ensure the account signing in belongs to a real Entra tenant. |
| Sign-in activity missing / R2 shows "activity unavailable" | Client tenant lacks Entra ID P1 | Expected — the tool degrades to a manual-review list. |
| Usage report names look scrambled | "Concealed names" is enabled in the client's M365 admin center | Ask the client admin to turn it off for per-user detail; totals still work. |

If you hit an `AADSTS` code not listed here, paste it into
<https://login.microsoftonline.com/error> for Microsoft's description.
