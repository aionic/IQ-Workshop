"""
test_fallback.py — Safe fallback tests.

Verifies that every DB-dependent endpoint returns 503 + {"fallback": true}
when the database layer raises an exception.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def mock_init_db():
    """Prevent real DB init during tests."""
    with patch("app.db.init_db_pool"), patch("app.db.close_db_pool"):
        yield


@pytest_asyncio.fixture
async def client(mock_init_db):
    """Async test client bound to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# -----------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------

DB_ERROR = RuntimeError("Simulated DB failure")


def _assert_fallback(resp, *, status: int = 503):
    """Assert the response matches the safe-fallback contract."""
    assert resp.status_code == status
    data = resp.json()
    assert data["fallback"] is True
    assert "unavailable" in data["detail"].lower() or "fallback" in data["detail"].lower()


# -----------------------------------------------------------------------
# POST /tools/query-ticket-context — DB error
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_ticket_context_db_error(client: AsyncClient):
    """DB exception → 503 safe fallback."""
    with patch("app.main.db.get_ticket_context", side_effect=DB_ERROR):
        resp = await client.post(
            "/tools/query-ticket-context",
            json={"ticket_id": "TKT-0042"},
        )
    _assert_fallback(resp)


# -----------------------------------------------------------------------
# POST /tools/request-approval — DB error
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_db_error(client: AsyncClient):
    """DB exception → 503 safe fallback."""
    with patch("app.main.db.create_approval_request", side_effect=DB_ERROR):
        resp = await client.post(
            "/tools/request-approval",
            json={
                "ticket_id": "TKT-0042",
                "proposed_action": "Escalate",
                "rationale": "Testing",
                "correlation_id": "corr-001",
            },
        )
    _assert_fallback(resp)


# -----------------------------------------------------------------------
# POST /tools/execute-remediation — DB error
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_db_error(client: AsyncClient):
    """DB exception → 503 safe fallback."""
    with patch("app.main.db.execute_remediation", side_effect=DB_ERROR):
        resp = await client.post(
            "/tools/execute-remediation",
            json={
                "ticket_id": "TKT-0042",
                "action": "Escalate",
                "approved_by": "admin@contoso.com",
                "approval_token": "99",
                "correlation_id": "corr-001",
            },
        )
    _assert_fallback(resp)


# -----------------------------------------------------------------------
# GET /admin/approvals — DB error
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_approvals_db_error(client: AsyncClient):
    """DB exception → 503 safe fallback."""
    with patch("app.main.db.list_pending_approvals", side_effect=DB_ERROR):
        resp = await client.get("/admin/approvals")
    _assert_fallback(resp)


# -----------------------------------------------------------------------
# POST /admin/approvals/{id}/decide — DB error
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_approval_db_error(client: AsyncClient):
    """DB exception → 503 safe fallback."""
    with patch("app.main.db.decide_approval", side_effect=DB_ERROR):
        resp = await client.post(
            "/admin/approvals/99/decide",
            json={"decision": "APPROVED", "approver": "admin@contoso.com"},
        )
    _assert_fallback(resp)


# -----------------------------------------------------------------------
# Health endpoint — DB down reports "unavailable" not crash
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_db_down_still_200(client: AsyncClient):
    """Health endpoint returns 200 with db=unavailable when DB is down."""
    with patch("app.main.db.get_connection", side_effect=DB_ERROR):
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "unavailable"
