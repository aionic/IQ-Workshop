"""
test_endpoints.py — Unit tests for IQ Foundry Agent Lab tool endpoints.

Uses httpx.AsyncClient with FastAPI TestClient pattern.
DB layer is mocked by default. Set TEST_USE_DB=true for integration tests.
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
# Sample data (mirrors schema.sql columns)
# -----------------------------------------------------------------------

SAMPLE_TICKET_ROW = {
    "ticket_id": "TKT-0042",
    "status": "New",
    "priority": "P2",
    "summary": "High jitter_spike on DEV-0007",
    "customer_id": "CUST-003",
    "owner": "alice.chen@contoso.com",
    "created_utc": datetime(2026, 2, 20, 10, 30, 0),
    "severity": "High",
    "signal_type": "jitter_spike",
    "detected_utc": datetime(2026, 2, 20, 10, 15, 0),
    "metric_jitter_ms": 142.5,
    "metric_loss_pct": 0.3,
    "metric_latency_ms": 28.0,
    "device_id": "DEV-0007",
    "site_id": "SITE-03",
    "model": "Nokia 7750 SR",
    "health_state": "Degraded",
}

SAMPLE_APPROVAL_ROW = {
    "remediation_id": 99,
    "status": "PENDING",
    "correlation_id": "test-corr-0001",
    "created_utc": datetime(2026, 2, 20, 11, 0, 0),
}


# -----------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient):
    """GET /health returns 200."""
    with patch("app.main.db.get_connection") as mock_conn:
        mock_cursor = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cursor
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# -----------------------------------------------------------------------
# POST /tools/query-ticket-context
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_ticket_context_success(client: AsyncClient):
    """Known ticket returns 200 with all expected fields."""
    with patch("app.main.db.get_ticket_context", return_value=SAMPLE_TICKET_ROW.copy()):
        resp = await client.post(
            "/tools/query-ticket-context",
            json={"ticket_id": "TKT-0042"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticket_id"] == "TKT-0042"
    assert data["severity"] == "High"
    assert data["device_id"] == "DEV-0007"
    assert data["site_id"] == "SITE-03"


@pytest.mark.asyncio
async def test_query_ticket_context_not_found(client: AsyncClient):
    """Unknown ticket returns 404."""
    with patch("app.main.db.get_ticket_context", return_value=None):
        resp = await client.post(
            "/tools/query-ticket-context",
            json={"ticket_id": "TKT-9999"},
        )
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# POST /tools/request-approval
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_success(client: AsyncClient):
    """Approval request returns PENDING with an approval_token."""
    with patch("app.main.db.create_approval_request", return_value=SAMPLE_APPROVAL_ROW.copy()):
        resp = await client.post(
            "/tools/request-approval",
            json={
                "ticket_id": "TKT-0042",
                "proposed_action": "Escalate to Investigate",
                "rationale": "Jitter exceeded threshold",
                "correlation_id": "test-corr-0001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "PENDING"
    assert data["approval_token"] == "99"  # noqa: S105
    assert data["correlation_id"] == "test-corr-0001"


# -----------------------------------------------------------------------
# POST /tools/execute-remediation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_approved(client: AsyncClient):
    """Valid approved token returns 200 with outcome."""
    exec_result = {
        "remediation_id": 99,
        "executed_utc": datetime(2026, 2, 20, 12, 0, 0),
        "outcome": "Executed: Escalate to Investigate",
        "correlation_id": "test-corr-0001",
    }
    with patch("app.main.db.execute_remediation", return_value=exec_result):
        resp = await client.post(
            "/tools/execute-remediation",
            json={
                "ticket_id": "TKT-0042",
                "action": "Escalate to Investigate",
                "approved_by": "admin@contoso.com",
                "approval_token": "99",
                "correlation_id": "test-corr-0001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["remediation_id"] == 99
    assert "Executed" in data["outcome"]


@pytest.mark.asyncio
async def test_execute_remediation_unapproved(client: AsyncClient):
    """Unapproved token returns 403."""
    with patch("app.main.db.execute_remediation", return_value=None):
        resp = await client.post(
            "/tools/execute-remediation",
            json={
                "ticket_id": "TKT-0042",
                "action": "Escalate to Investigate",
                "approved_by": "admin@contoso.com",
                "approval_token": "bad-token",
                "correlation_id": "test-corr-0001",
            },
        )
    assert resp.status_code == 403


# -----------------------------------------------------------------------
# Approval flow: request → decide → execute
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_flow_end_to_end(client: AsyncClient):
    """Full flow: request approval → admin decides → execute."""
    # 1. Request approval
    with patch("app.main.db.create_approval_request", return_value=SAMPLE_APPROVAL_ROW.copy()):
        resp = await client.post(
            "/tools/request-approval",
            json={
                "ticket_id": "TKT-0042",
                "proposed_action": "Escalate",
                "rationale": "Test",
            },
        )
    assert resp.status_code == 200
    approval_token = resp.json()["approval_token"]

    # 2. Admin decides APPROVED
    decided_row = {
        "remediation_id": 99,
        "ticket_id": "TKT-0042",
        "proposed_action": "Escalate",
        "rationale": "Test",
        "status": "APPROVED",
        "approved_by": "admin@contoso.com",
        "approved_utc": datetime(2026, 2, 20, 11, 30, 0),
        "correlation_id": "test-corr-0001",
        "created_utc": datetime(2026, 2, 20, 11, 0, 0),
    }
    with patch("app.main.db.decide_approval", return_value=decided_row):
        resp = await client.post(
            "/admin/approvals/99/decide",
            json={"decision": "APPROVED", "approver": "admin@contoso.com"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "APPROVED"

    # 3. Execute remediation
    exec_result = {
        "remediation_id": 99,
        "executed_utc": datetime(2026, 2, 20, 12, 0, 0),
        "outcome": "Executed: Escalate",
        "correlation_id": "test-corr-0001",
    }
    with patch("app.main.db.execute_remediation", return_value=exec_result):
        resp = await client.post(
            "/tools/execute-remediation",
            json={
                "ticket_id": "TKT-0042",
                "action": "Escalate",
                "approved_by": "admin@contoso.com",
                "approval_token": approval_token,
                "correlation_id": "test-corr-0001",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["remediation_id"] == 99


# -----------------------------------------------------------------------
# POST /tools/post-teams-summary (stub)
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teams_summary_stub_no_webhook(client: AsyncClient):
    """Without TEAMS_WEBHOOK_URL, posts are logged but not sent."""
    with patch.dict("os.environ", {"TEAMS_WEBHOOK_URL": ""}, clear=False):
        resp = await client.post(
            "/tools/post-teams-summary",
            json={
                "ticket_id": "TKT-0042",
                "summary": "Jitter resolved",
                "action_taken": "Escalate to Investigate",
                "approved_by": "admin@contoso.com",
                "correlation_id": "test-corr-0001",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["logged"] is True
    assert data["teams_posted"] is False
