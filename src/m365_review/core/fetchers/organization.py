"""Fetch tenant identity from GET /organization."""

from __future__ import annotations

from m365_review.core.graph_client import GraphClient
from m365_review.core.models import Organization


async def fetch_organization(gc: GraphClient) -> Organization:
    """Return the tenant's organization record (display name, domains, country).

    ``/organization`` returns a collection with a single element for a tenant.
    """
    body = await gc.get_json("/organization")
    values = body.get("value", [])
    if not values:
        raise RuntimeError("GET /organization returned no organization record.")
    return Organization.from_graph(values[0])
