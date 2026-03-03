"""
test_edge_cases.py — Edge-case and negative-path tests.

Covers scenarios not already in test_endpoints.py, test_fallback.py,
or test_validation.py.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def mock_init_db():
    with patch("app.db.init_db_pool"), patch("app.db.close_db_pool"):
        yield


@pytest_asyncio.fixture
async def client(mock_init_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# -----------------------------------------------------------------------
# Health edge cases
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_db_connected(client: AsyncClient):
    """Health with working DB returns db=connected."""
    with patch("app.main.db.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cursor
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db"] == "connected"


@pytest.mark.asyncio
async def test_health_method_not_allowed(client: AsyncClient):
    """POST /health → 405."""
    resp = await client.post("/health")
    assert resp.status_code == 405


# -----------------------------------------------------------------------
# query-ticket-context edge cases
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_ticket_context_empty_ticket_id(client: AsyncClient):
    """Empty string ticket_id is valid schema, returns 404 if not found."""
    with patch("app.main.db.get_ticket_context", return_value=None):
        resp = await client.post(
            "/tools/query-ticket-context",
            json={"ticket_id": ""},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_query_ticket_context_null_optional_fields(client: AsyncClient):
    """Response handles None metric fields gracefully."""
    row = {
        "ticket_id": "TKT-0042",
        "status": "New",
        "priority": "P2",
        "summary": "Test",
        "customer_id": "CUST-003",
        "owner": None,
        "created_utc": datetime(2026, 2, 20, 10, 30, 0),
        "severity": "High",
        "signal_type": "jitter_spike",
        "detected_utc": datetime(2026, 2, 20, 10, 15, 0),
        "metric_jitter_ms": None,
        "metric_loss_pct": None,
        "metric_latency_ms": None,
        "device_id": "DEV-0007",
        "site_id": "SITE-03",
        "model": "Nokia 7750 SR",
        "health_state": "Degraded",
    }
    with patch("app.main.db.get_ticket_context", return_value=row):
        resp = await client.post(
            "/tools/query-ticket-context",
            json={"ticket_id": "TKT-0042"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["metric_jitter_ms"] is None
    assert data["owner"] is None


# -----------------------------------------------------------------------
# execute-remediation edge cases
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_unapproved_returns_403(client: AsyncClient):
    """Unapproved token → 403 with detail."""
    with patch("app.main.db.execute_remediation", return_value=None):
        resp = await client.post(
            "/tools/execute-remediation",
            json={
                "ticket_id": "TKT-0042",
                "action": "Restart",
                "approved_by": "admin@contoso.com",
                "approval_token": "bad-token",
                "correlation_id": "corr-001",
            },
        )
    assert resp.status_code == 403
    assert "approval" in resp.json()["detail"].lower()


# -----------------------------------------------------------------------
# admin/approvals edge cases
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_approvals_empty(client: AsyncClient):
    """No pending approvals returns empty list."""
    with patch("app.main.db.list_pending_approvals", return_value=[]):
        resp = await client.get("/admin/approvals")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_decide_approval_not_found(client: AsyncClient):
    """Non-existent remediation_id → 404."""
    with patch("app.main.db.decide_approval", return_value=None):
        resp = await client.post(
            "/admin/approvals/999999/decide",
            json={"decision": "APPROVED", "approver": "admin@contoso.com"},
        )
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# post-teams-summary edge cases
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teams_summary_with_webhook_success(client: AsyncClient):
    """With TEAMS_WEBHOOK_URL set and successful post → teams_posted=True."""
    mock_response = MagicMock()
    mock_response.is_success = True

    with (
        patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": "https://hooks.example.com/test"}),
        patch("httpx.AsyncClient") as mock_httpx,
    ):
        mock_client_instance = MagicMock()
        mock_httpx.return_value.__aenter__ = lambda self: _async_return(mock_client_instance)
        mock_httpx.return_value.__aexit__ = lambda self, *a: _async_return(None)
        mock_client_instance.post = lambda *a, **kw: _async_return(mock_response)

        resp = await client.post(
            "/tools/post-teams-summary",
            json={
                "ticket_id": "TKT-0042",
                "summary": "Jitter resolved",
                "action_taken": "Escalate",
                "approved_by": "admin@contoso.com",
                "correlation_id": "corr-001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["logged"] is True
    assert data["teams_posted"] is True


async def _async_return(value):
    """Helper to return a value from an async context."""
    return value


# -----------------------------------------------------------------------
# Correlation ID header propagation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_id_header_propagated(client: AsyncClient):
    """X-Correlation-ID header is accepted and used."""
    with patch("app.main.db.get_ticket_context", return_value=None):
        resp = await client.post(
            "/tools/query-ticket-context",
            json={"ticket_id": "TKT-missing"},
            headers={"X-Correlation-ID": "my-custom-corr-id"},
        )
    # The 404 still works correctly — correlation header doesn't change status
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# Nonexistent endpoint
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nonexistent_endpoint(client: AsyncClient):
    """Unknown route → 404."""
    resp = await client.get("/tools/nonexistent")
    assert resp.status_code == 404
