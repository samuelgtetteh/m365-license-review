"""Async Microsoft Graph client.

Centralizes everything finicky about Graph so fetchers stay trivial:

* **GET-only guard** — a hard runtime assertion; any attempt to use a non-GET
  method raises. This enforces the read-only guarantee at the transport layer.
* **Pagination** — transparently follows ``@odata.nextLink`` on list endpoints.
* **Throttling** — honors ``Retry-After`` on 429; exponential backoff on 5xx.
* **Report endpoints** — follow the 302 redirect to the signed CSV blob and
  return parsed rows.
* **403 scope errors** — surfaced with the missing-scope detail, not swallowed.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from typing import Any, AsyncIterator

import httpx

from m365_review.core.auth import TenantSession

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_RETRIES = 5
_BACKOFF_BASE = 1.5  # seconds
_DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


class GraphError(RuntimeError):
    """A Graph call failed in a way the caller should see."""

    def __init__(self, message: str, *, status: int | None = None, missing_scope: bool = False):
        super().__init__(message)
        self.status = status
        self.missing_scope = missing_scope


class WriteAttemptError(RuntimeError):
    """Raised if any non-GET method is attempted. The tool is read-only."""


class GraphClient:
    """Thin async wrapper around httpx for read-only Graph access.

    Usage::

        async with GraphClient(session) as gc:
            org = await gc.get_json("/organization")
            skus = [s async for s in gc.paged("/subscribedSkus")]
    """

    def __init__(self, session: TenantSession, *, base_url: str = GRAPH_BASE):
        self._token = session.access_token
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GraphClient":
        self._client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,  # required: /reports/* returns 302 to a signed blob
            headers={"Authorization": f"Bearer {self._token}"},
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    # Core request with retry. GET only — enforced here.
    # ------------------------------------------------------------------ #
    async def _request(self, url: str, *, method: str = "GET") -> httpx.Response:
        if method.upper() != "GET":
            # The read-only guarantee, enforced at the transport layer.
            raise WriteAttemptError(
                f"Refusing non-GET Graph request ({method}). This tool is strictly read-only."
            )
        assert self._client is not None, "GraphClient must be used as an async context manager"

        full_url = url if url.startswith("http") else f"{self._base_url}{url}"

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            resp = await self._client.get(full_url)

            if resp.status_code == 429:
                delay = _retry_after_seconds(resp, attempt)
                logger.warning("Graph 429 throttle on %s; sleeping %.1fs", _safe_path(full_url), delay)
                await asyncio.sleep(delay)
                continue

            if 500 <= resp.status_code < 600:
                delay = _BACKOFF_BASE ** attempt
                logger.warning("Graph %s on %s; retry in %.1fs", resp.status_code, _safe_path(full_url), delay)
                last_exc = GraphError(f"Server error {resp.status_code}", status=resp.status_code)
                await asyncio.sleep(delay)
                continue

            if resp.status_code == 403:
                raise GraphError(
                    f"403 Forbidden on {_safe_path(full_url)}. A required delegated scope may "
                    f"not be consented. Ask the client admin to re-consent. Detail: "
                    f"{_error_detail(resp)}",
                    status=403,
                    missing_scope=True,
                )

            if resp.status_code >= 400:
                raise GraphError(
                    f"{resp.status_code} on {_safe_path(full_url)}: {_error_detail(resp)}",
                    status=resp.status_code,
                )

            return resp

        raise last_exc or GraphError(f"Exhausted retries on {_safe_path(full_url)}")

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #
    async def get_json(self, path: str) -> dict[str, Any]:
        """GET a single JSON resource."""
        resp = await self._request(path)
        return resp.json()

    async def paged(self, path: str) -> AsyncIterator[dict[str, Any]]:
        """GET a collection, yielding each item, following @odata.nextLink."""
        url: str | None = path
        while url:
            resp = await self._request(url)
            body = resp.json()
            for item in body.get("value", []):
                yield item
            url = body.get("@odata.nextLink")

    async def get_all(self, path: str) -> list[dict[str, Any]]:
        """Collect an entire paged collection into a list."""
        return [item async for item in self.paged(path)]

    async def get_report_csv(self, path: str) -> list[dict[str, str]]:
        """GET a /reports/* CSV endpoint and parse it into dict rows.

        These endpoints 302-redirect to a signed blob returning CSV text
        (httpx follows the redirect). Data can lag 24-72h and UPNs may be
        anonymized ("concealed names") — the caller flags that in the report.
        """
        resp = await self._request(path)
        text = resp.text
        if not text.strip():
            return []
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]


# --------------------------------------------------------------------------- #
# Helpers (module-level, testable)
# --------------------------------------------------------------------------- #

def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return _BACKOFF_BASE ** attempt


def _error_detail(resp: httpx.Response) -> str:
    """Extract Graph's error message without dumping the whole body."""
    try:
        data = resp.json()
        return str(data.get("error", {}).get("message", ""))[:300]
    except Exception:  # noqa: BLE001
        return resp.text[:200]


def _safe_path(url: str) -> str:
    """Log-safe path: strip query strings (they can carry tokens on blob URLs)."""
    return url.split("?", 1)[0]
