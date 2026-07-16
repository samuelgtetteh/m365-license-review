"""Fetch licenses owned by the tenant from GET /subscribedSkus.

This is the source of truth for "how many licenses do they own vs. use".
"""

from __future__ import annotations

from m365_review.core.graph_client import GraphClient
from m365_review.core.models import SubscribedSku


async def fetch_subscribed_skus(gc: GraphClient) -> list[SubscribedSku]:
    """Return all subscribed SKUs with purchased/consumed counts."""
    rows = await gc.get_all("/subscribedSkus")
    return [SubscribedSku.from_graph(r) for r in rows]
