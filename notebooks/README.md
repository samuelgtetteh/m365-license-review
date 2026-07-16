# Notebooks

Reproducibility walkthroughs. Each imports `m365_review.core` and runs against
the **synthetic fixtures** in `../tests/fixtures/` — no live tenant, no tokens.

| Notebook | What it shows |
|----------|---------------|
| `01_auth_walkthrough.ipynb` | How auth works (web auth-code+PKCE, CLI interactive/device); token redaction. No live sign-in. |
| `02_fetch_and_explore.ipynb` | Fetcher output shapes: SKUs purchased vs. assigned, users & sign-in activity. |
| `03_rules_engine.ipynb` | Every rule run on fixtures → findings + savings, including the no-P1 degraded path. |
| `04_report_generation.ipynb` | Build the `AuditResult` and write `.xlsx` / `.docx` / `.json`. |

## Run

```bash
pip install -e ".[dev]"
jupyter lab           # then open notebooks/ and run top-to-bottom
```

**Before committing**, strip outputs so no data is baked in:

```bash
nbstripout notebooks/*.ipynb
```
