# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead, use
GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**), or contact the maintainer directly.

We aim to acknowledge reports within a few business days.

## Supported versions

The latest published release (`:latest` on GHCR) is supported. Older tags are
best-effort.

## Design & handling notes (context for reviewers)

- **Read-only.** The tool requests only delegated *read* Microsoft Graph scopes
  and makes only `GET` calls — enforced by a runtime guard in `graph_client.py`
  that raises on any non-GET method. It never writes to a tenant.
- **No stored credentials.** Access tokens live in memory for a run only; they
  are never logged, written to disk, or included in reports.
- **Secrets are git-ignored.** `.env`, the SQLite profiles database, generated
  reports, and image tarballs are excluded from version control.
- **Reports contain PII** (names, UPNs, sign-in dates). Treat generated files as
  sensitive and store them in an access-controlled location.
- **Public client, no secret.** Auth uses the authorization-code + PKCE flow with
  no client secret to manage or leak.

If you find anything that contradicts the above, that's exactly the kind of report
we want.
