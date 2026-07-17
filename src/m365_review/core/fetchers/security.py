"""Identity-security fetchers: MFA registration + privileged roles.

Both use scopes we already request:
* MFA registration — ``/reports/authenticationMethods/userRegistrationDetails``
  (needs AuditLog.Read.All / Reports.Read.All; the signed-in admin also needs an
  appropriate directory role to read it).
* Privileged roles — ``/directoryRoles?$expand=members`` (Directory.Read.All).

Each degrades gracefully: on 403/unavailable it returns ([], False) so the audit
continues and the report notes the gap.
"""

from __future__ import annotations

import logging

from m365_review.core.graph_client import GraphClient, GraphError
from m365_review.core.models import DirectoryRole, UserRegistration

logger = logging.getLogger(__name__)

_MFA_PATH = (
    "/reports/authenticationMethods/userRegistrationDetails"
    "?$select=userPrincipalName,userDisplayName,userType,isAdmin,isMfaRegistered,isMfaCapable"
)
_ROLES_PATH = "/directoryRoles?$expand=members"


async def fetch_user_registration(gc: GraphClient) -> tuple[list[UserRegistration], bool]:
    """Return (registration details, available)."""
    try:
        rows = await gc.get_all(_MFA_PATH)
        return [UserRegistration.from_graph(r) for r in rows], True
    except GraphError as exc:
        logger.warning("MFA registration data unavailable (status %s).", exc.status)
        return [], False


async def fetch_directory_roles(gc: GraphClient) -> tuple[list[DirectoryRole], bool]:
    """Return (activated directory roles with members, available)."""
    try:
        rows = await gc.get_all(_ROLES_PATH)
        return [DirectoryRole.from_graph(r) for r in rows], True
    except GraphError as exc:
        logger.warning("Directory role data unavailable (status %s).", exc.status)
        return [], False
