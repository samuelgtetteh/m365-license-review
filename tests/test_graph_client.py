"""Tests for the Graph client: GET-only guard, pagination, retry, scope errors."""

from __future__ import annotations

import httpx
import pytest
import respx

from m365_review.core.auth import TenantSession
from m365_review.core.graph_client import (
    GRAPH_BASE,
    GraphClient,
    GraphError,
    WriteAttemptError,
)

SESSION = TenantSession(access_token="tok", tenant_id="tid")


async def test_get_only_guard_blocks_non_get():
    async with GraphClient(SESSION) as gc:
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            with pytest.raises(WriteAttemptError):
                await gc._request("/users", method=method)


@respx.mock
async def test_pagination_follows_nextlink():
    # nextLink points back at the same URL; ordered side_effect yields page1 then
    # page2 (no nextLink), so the client makes exactly two GETs and stops.
    page1 = {"value": [{"id": "1"}, {"id": "2"}], "@odata.nextLink": f"{GRAPH_BASE}/users"}
    page2 = {"value": [{"id": "3"}]}
    route = respx.get(f"{GRAPH_BASE}/users")
    route.side_effect = [
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ]

    async with GraphClient(SESSION) as gc:
        items = await gc.get_all("/users")
    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert route.call_count == 2


@respx.mock
async def test_retries_on_429_then_succeeds():
    route = respx.get(f"{GRAPH_BASE}/organization")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}, json={}),
        httpx.Response(200, json={"value": [{"id": "org"}]}),
    ]
    async with GraphClient(SESSION) as gc:
        body = await gc.get_json("/organization")
    assert body["value"][0]["id"] == "org"
    assert route.call_count == 2


@respx.mock
async def test_403_surfaces_missing_scope():
    respx.get(f"{GRAPH_BASE}/users").mock(
        return_value=httpx.Response(403, json={"error": {"message": "Insufficient privileges"}})
    )
    async with GraphClient(SESSION) as gc:
        with pytest.raises(GraphError) as ei:
            await gc.get_all("/users")
    assert ei.value.status == 403
    assert ei.value.missing_scope is True


@respx.mock
async def test_report_csv_parsed():
    csv_text = "UPN,Last activity\nalice@x.com,2026-01-01\nbob@x.com,\n"
    respx.get(f"{GRAPH_BASE}/reports/getX").mock(return_value=httpx.Response(200, text=csv_text))
    async with GraphClient(SESSION) as gc:
        rows = await gc.get_report_csv("/reports/getX")
    assert rows[0]["UPN"] == "alice@x.com"
    assert len(rows) == 2
