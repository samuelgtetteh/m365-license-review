"""In-memory, per-browser session store for the web app.

Why in-memory: the tool audits ONE tenant per session on a locally-run
container. Access tokens must never touch disk (handoff §13), so there is no
persistent session backend. Sessions die with the process.

A signed, httponly, samesite cookie carries only an opaque session id; all
sensitive state (the MSAL flow dict, the ``TenantSession`` with its token, the
selected audit options, generated report paths) is held server-side here.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer

from m365_review.core.auth import TenantSession
from m365_review.settings import get_settings

COOKIE_NAME = "m365_sid"
_SID_BYTES = 32


@dataclass
class WebSession:
    """Server-side state for one browser session. Never serialized to a client."""

    sid: str
    auth_flow: dict[str, Any] | None = None       # MSAL flow dict between /login and /callback
    tenant: TenantSession | None = None            # set after successful sign-in
    options: dict[str, Any] = field(default_factory=dict)   # formats, experimental, client_id
    reports: dict[str, Path] = field(default_factory=dict)  # format -> file path after a run

    def clear_sensitive(self) -> None:
        """Drop the token and auth flow. Call after a run or on logout."""
        self.tenant = None
        self.auth_flow = None


class SessionStore:
    """Thread-unsafe-simple dict store. Fine for a single-worker local container."""

    def __init__(self) -> None:
        self._sessions: dict[str, WebSession] = {}
        self._serializer = URLSafeSerializer(get_settings().session_secret, salt="m365-sid")

    # --- cookie <-> sid ---
    def sign_sid(self, sid: str) -> str:
        return self._serializer.dumps(sid)

    def unsign_sid(self, signed: str) -> str | None:
        try:
            return self._serializer.loads(signed)
        except BadSignature:
            return None

    # --- lifecycle ---
    def create(self) -> WebSession:
        sid = secrets.token_urlsafe(_SID_BYTES)
        session = WebSession(sid=sid)
        self._sessions[sid] = session
        return session

    def get(self, sid: str | None) -> WebSession | None:
        if not sid:
            return None
        return self._sessions.get(sid)

    def get_by_cookie(self, signed_cookie: str | None) -> WebSession | None:
        if not signed_cookie:
            return None
        sid = self.unsign_sid(signed_cookie)
        return self.get(sid)

    def destroy(self, sid: str | None) -> None:
        if sid and sid in self._sessions:
            self._sessions[sid].clear_sensitive()
            del self._sessions[sid]


# Module-level singleton used by the app.
store = SessionStore()
