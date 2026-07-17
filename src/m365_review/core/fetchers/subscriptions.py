"""Fetch commerce subscriptions (with expiration/renewal dates).

Expiration data is NOT in /subscribedSkus — it lives on the `companySubscription`
resource at ``/directory/subscriptions`` (currently a beta endpoint). Needs only
Directory.Read.All / Organization.Read.All, which we already request.

Degrades gracefully: if the endpoint is unavailable (404 / not enabled), returns
an empty list and ``available=False`` so the report can note it rather than fail.
"""

from __future__ import annotations

import logging

from m365_review.core.graph_client import GRAPH_BASE_BETA, GraphClient, GraphError
from m365_review.core.models import Subscription

logger = logging.getLogger(__name__)

_SUBSCRIPTIONS_URL = f"{GRAPH_BASE_BETA}/directory/subscriptions"


async def fetch_subscriptions(gc: GraphClient) -> tuple[list[Subscription], bool]:
    """Return (subscriptions, available)."""
    try:
        rows = await gc.get_all(_SUBSCRIPTIONS_URL)
        return [Subscription.from_graph(r) for r in rows], True
    except GraphError as exc:
        logger.warning(
            "Subscription/expiration data unavailable (status %s); continuing without it.",
            exc.status,
        )
        return [], False
