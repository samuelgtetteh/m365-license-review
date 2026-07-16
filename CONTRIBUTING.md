# Contributing

Thanks for helping improve M365 License Review. This is a read-only auditing
tool for MSPs — please keep changes aligned with that scope and its safety model.

## Non-negotiables

- **Read-only.** Never add a non-GET Graph call or a write scope. The GET-only
  guard in `graph_client.py` must stay. Recommendations only — the tool never
  changes a tenant.
- **No secrets in the repo.** `.env`, generated reports, and the SQLite database
  are git-ignored. Never commit real client IDs, tenant names, tokens, or PII.
  Notebooks must be committed with outputs stripped (`nbstripout notebooks/*.ipynb`).

## Development setup

```bash
pip install -e ".[dev]"        # Python 3.11+
pytest -q                      # run the test suite
uvicorn m365_review.web.app:app --reload   # web app on :8000
m365-review --help             # CLI
```

Or run the whole stack in Docker: `./run.ps1` / `./run.sh`, or `docker compose up -d`.

## Project layout

- `src/m365_review/core/` — UI-agnostic engine (auth, Graph client, fetchers,
  rules, pricing, reports). No FastAPI/typer imports here.
- `src/m365_review/web/` — FastAPI app (thin). `.../cli.py` — typer CLI (thin).
- `config/` — SKU price/name/overlap maps. `tests/fixtures/` — synthetic Graph data.
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Adding a rule

Each rule is a pure function `(RuleContext) -> list[Finding]` in
`core/rules/`. Add it to the registry in `core/rules/__init__.py`, gate
higher-false-positive rules behind `experimental`, and add a fixture-based test
in `tests/test_rules.py`. Rules must not do I/O and must read time from
`ctx.now` (not the clock) so they stay deterministic.

## Pull requests

- Keep the diff focused; match the surrounding style.
- Add or update tests; `pytest -q` must pass.
- Update `CHANGELOG.md` under an "Unreleased" heading.
- Update docs (`README.md`, `docs/`, or the in-app Help page) when behavior changes.

## Releasing (maintainers)

Tag a version and push it — CI builds and publishes the image to GHCR:

```bash
git tag v0.2.0
git push origin v0.2.0
```

See the "Releasing" section in the [README](README.md#releasing-maintainers).
