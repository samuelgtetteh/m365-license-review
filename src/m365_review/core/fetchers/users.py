"""Fetch users, their license assignments, and sign-in activity.

``signInActivity`` requires Azure AD P1+. On free/basic tenants the field is
absent or the call 403s. We attempt the rich query first and degrade to a
query without ``signInActivity`` if needed, flagging it for the report so R2
can fall back to a ``createdDateTime`` heuristic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from m365_review.core.graph_client import GraphClient, GraphError
from m365_review.core.models import User

logger = logging.getLogger(__name__)

# Fields we always want.
_BASE_SELECT = (
    "id,displayName,userPrincipalName,accountEnabled,assignedLicenses,"
    "createdDateTime,userType,mail"
)
_WITH_ACTIVITY = f"{_BASE_SELECT},signInActivity"

_USERS_PATH = f"/users?$select={_WITH_ACTIVITY}&$top=999"
_USERS_PATH_NO_ACTIVITY = f"/users?$select={_BASE_SELECT}&$top=999"


@dataclass
class UsersResult:
    users: list[User]
    sign_in_activity_available: bool


async def fetch_users(gc: GraphClient) -> UsersResult:
    """Return all users. Falls back gracefully if signInActivity is unavailable."""
    try:
        rows = await gc.get_all(_USERS_PATH)
        users = [User.from_graph(r) for r in rows]
        # Some tenants return 200 but omit the field entirely — detect that too.
        available = any(u.sign_in_activity_available for u in users) if users else True
        if not available:
            logger.info("signInActivity absent from user payloads; tenant likely lacks AAD P1.")
        return UsersResult(users=users, sign_in_activity_available=available)
    except GraphError as exc:
        if exc.missing_scope or (exc.status in (400, 403)):
            logger.warning(
                "signInActivity query failed (%s); retrying without it (no AAD P1 / no AuditLog consent).",
                exc.status,
            )
            rows = await gc.get_all(_USERS_PATH_NO_ACTIVITY)
            users = [User.from_graph(r) for r in rows]
            for u in users:
                u.sign_in_activity_available = False
            return UsersResult(users=users, sign_in_activity_available=False)
        raise
