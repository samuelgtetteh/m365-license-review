"""Conditional Access, named-location, auth-methods-policy, and per-user MFA fetchers.

All require the delegated **Policy.Read.All** scope (per-user MFA state also reads
`/users/{id}/authentication/requirements`). Each degrades gracefully (returns
``available=False``) so a missing scope/consent doesn't fail the whole run.
"""

from __future__ import annotations

import logging

from m365_review.core.graph_client import GRAPH_BASE_BETA, GraphClient, GraphError
from m365_review.core.models import (
    AuthMethodConfig,
    ConditionalAccessPolicy,
    NamedLocation,
    User,
    UserMfaRequirement,
)

logger = logging.getLogger(__name__)


async def fetch_ca_policies(gc: GraphClient) -> tuple[list[ConditionalAccessPolicy], bool]:
    try:
        rows = await gc.get_all("/identity/conditionalAccess/policies")
        return [ConditionalAccessPolicy.from_graph(r) for r in rows], True
    except GraphError as exc:
        logger.warning("Conditional Access policies unavailable (status %s).", exc.status)
        return [], False


async def fetch_named_locations(gc: GraphClient) -> tuple[list[NamedLocation], bool]:
    try:
        rows = await gc.get_all("/identity/conditionalAccess/namedLocations")
        return [NamedLocation.from_graph(r) for r in rows], True
    except GraphError as exc:
        logger.warning("Named locations unavailable (status %s).", exc.status)
        return [], False


async def fetch_auth_methods_policy(gc: GraphClient) -> tuple[list[AuthMethodConfig], bool]:
    try:
        body = await gc.get_json("/policies/authenticationMethodsPolicy")
        configs = body.get("authenticationMethodConfigurations", []) or []
        return [AuthMethodConfig.from_graph(c) for c in configs], True
    except GraphError as exc:
        logger.warning("Authentication methods policy unavailable (status %s).", exc.status)
        return [], False


async def fetch_per_user_mfa(
    gc: GraphClient, users: list[User]
) -> tuple[list[UserMfaRequirement], bool]:
    """Per-user MFA state — one call per user (beta). Returns (results, available)."""
    if not users:
        return [], True
    results: list[UserMfaRequirement] = []
    any_ok = False
    for u in users:
        try:
            body = await gc.get_json(
                f"{GRAPH_BASE_BETA}/users/{u.id}/authentication/requirements"
            )
            any_ok = True
            results.append(
                UserMfaRequirement(
                    user_principal_name=u.user_principal_name,
                    display_name=u.display_name,
                    state=body.get("perUserMfaState", "disabled"),
                )
            )
        except GraphError as exc:
            if exc.status in (403, 401):
                # No permission → treat the whole audit as unavailable.
                logger.warning("Per-user MFA state unavailable (status %s).", exc.status)
                return [], False
            # A single-user error (e.g. 404 for a synced-but-odd object) is skipped.
            continue
    return results, any_ok
