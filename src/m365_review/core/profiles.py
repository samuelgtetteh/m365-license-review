"""Saved connection profiles, persisted in SQLite.

An operator can save a friendly **name** (e.g. the client/company) together with
the Azure **client ID** once; later runs select the profile by name and the tool
loads the client ID and starts sign-in — no re-typing.

Storage notes:
* The Azure Application (client) ID is **not a secret** (it is public by design),
  so it is stored in **plaintext**. This store must never hold client *secrets*,
  tokens, or any credential — the tool has none of those by design.
* Backed by stdlib ``sqlite3`` (no extra dependency). The DB file lives on a
  persistent, git-ignored volume so profiles survive container restarts.
* As a light audit aid, each profile records when it was last used and the last
  tenant (id + name) it was used to audit.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from m365_review.settings import Settings, get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    name             TEXT PRIMARY KEY,
    client_id        TEXT NOT NULL,
    tenant_domain    TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL,
    last_used_at     TEXT,
    last_tenant_id   TEXT,
    last_tenant_name TEXT
);
"""


@dataclass
class Profile:
    name: str
    client_id: str
    tenant_domain: str | None = None
    notes: str | None = None
    created_at: str | None = None
    last_used_at: str | None = None
    last_tenant_id: str | None = None
    last_tenant_name: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Profile":
        return cls(**{k: row[k] for k in row.keys()})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProfileStore:
    """Small repository over the SQLite ``profiles`` table.

    Opens a short-lived connection per operation, which keeps it safe to use from
    FastAPI's async handlers (each call runs on whatever thread) without sharing a
    connection across threads.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # --- reads ---
    def list(self) -> list[Profile]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM profiles ORDER BY last_used_at DESC, name ASC"
            ).fetchall()
        return [Profile.from_row(r) for r in rows]

    def get(self, name: str) -> Profile | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
        return Profile.from_row(row) if row else None

    # --- writes ---
    def upsert(
        self,
        name: str,
        client_id: str,
        *,
        tenant_domain: str | None = None,
        notes: str | None = None,
    ) -> Profile:
        """Create or update a profile by name. Preserves created_at on update."""
        name = name.strip()
        client_id = client_id.strip()
        if not name:
            raise ValueError("Profile name is required.")
        if not client_id:
            raise ValueError("Client ID is required.")

        existing = self.get(name)
        created = existing.created_at if existing else _now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (name, client_id, tenant_domain, notes, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    client_id = excluded.client_id,
                    tenant_domain = excluded.tenant_domain,
                    notes = excluded.notes
                """,
                (name, client_id, tenant_domain, notes, created),
            )
        return self.get(name)  # type: ignore[return-value]

    def touch(
        self,
        name: str,
        *,
        tenant_id: str | None = None,
        tenant_name: str | None = None,
    ) -> None:
        """Record that a profile was just used to audit a tenant."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE profiles
                   SET last_used_at = ?, last_tenant_id = ?, last_tenant_name = ?
                 WHERE name = ?
                """,
                (_now_iso(), tenant_id, tenant_name, name),
            )

    def delete(self, name: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
        return cur.rowcount > 0


def get_store(settings: Settings | None = None) -> ProfileStore:
    """Construct a ProfileStore at the configured DB path."""
    settings = settings or get_settings()
    return ProfileStore(settings.db_path)
