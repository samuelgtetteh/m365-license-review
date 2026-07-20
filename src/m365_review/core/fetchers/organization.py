"""Fetch tenant identity from GET /organization."""

from __future__ import annotations

import logging

from m365_review.core.graph_client import GraphClient, GraphError
from m365_review.core.models import Domain, Organization

logger = logging.getLogger(__name__)


async def fetch_organization(gc: GraphClient) -> Organization:
    """Return the tenant's organization record (display name, domains, country).

    ``/organization`` returns a collection with a single element for a tenant.
    """
    body = await gc.get_json("/organization")
    values = body.get("value", [])
    if not values:
        raise RuntimeError("GET /organization returned no organization record.")
    return Organization.from_graph(values[0])


async def fetch_domains(gc: GraphClient) -> tuple[list[Domain], bool]:
    """Return (verified/accepted domains, available). Uses /domains (Directory.Read.All)."""
    try:
        rows = await gc.get_all("/domains")
        return [Domain.from_graph(r) for r in rows], True
    except GraphError as exc:
        logger.warning("Domains unavailable (status %s).", exc.status)
        return [], False
