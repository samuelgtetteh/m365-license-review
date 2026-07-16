"""Shared, UI-agnostic engine: auth, Graph client, fetchers, rules, pricing, reporting.

Both the web app and the CLI import from here. This layer must never depend on
FastAPI or typer.
"""
