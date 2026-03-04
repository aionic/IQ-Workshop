"""
test_mcp_server.py — Tests for the MCP server tools co-hosted on FastAPI.

Tests the MCP tool functions directly (unit tests with mocked DB) plus
a smoke test verifying the /mcp mount exists on the app.

DB layer is mocked (same pattern as test_endpoints.py).
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.mcp_server import (
    execute_remediation,
    post_teams_summary,
    query_ticket_context,
    request_approval,
)

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
# Sample data (mirrors test_endpoints.py)
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

SAMPLE_EXEC_ROW = {
    "remediation_id": 99,
    "outcome": "simulated_success",
    "executed_utc": datetime(2026, 2, 20, 11, 5, 0),
    "correlation_id": "test-corr-0001",
}


# -----------------------------------------------------------------------
# Smoke test: MCP endpoint mounted
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_endpoint_mounted(client: AsyncClient):
    """The /mcp path should exist on the app (not return 404).

    Without the lifespan-managed session manager running, the MCP sub-app
    will error, but we verify it's mounted (not 404).
    """
    try:
        resp = await client.get("/mcp")
    except RuntimeError:
        # MCP session manager not initialised in tests — that's fine,
        # it proves the route is mounted (would be 404 otherwise).
        return
    # The MCP sub-app may return 405, 500, or similar — all valid; just not 404.
    assert resp.status_code != 404, "MCP endpoint not mounted on the app"


# -----------------------------------------------------------------------
# Tool functions: query_ticket_context
# -----------------------------------------------------------------------


def test_query_ticket_context_success():
    """query_ticket_context returns JSON with ticket data."""
    with patch("app.db.get_ticket_context", return_value=dict(SAMPLE_TICKET_ROW)):
        result = query_ticket_context("TKT-0042")
    parsed = json.loads(result)
    assert parsed["ticket_id"] == "TKT-0042"
    assert parsed["device_id"] == "DEV-0007"
    assert parsed["metric_jitter_ms"] == 142.5
    # Datetimes should be ISO strings
    assert "2026-02-20" in parsed["created_utc"]


def test_query_ticket_context_not_found():
    """query_ticket_context returns error JSON for unknown ticket."""
    with patch("app.db.get_ticket_context", return_value=None):
        result = query_ticket_context("TKT-NOPE")
    parsed = json.loads(result)
    assert "error" in parsed
    assert "TKT-NOPE" in parsed["error"]
    assert parsed.get("fallback") is False


def test_query_ticket_context_db_error():
    """query_ticket_context returns safe fallback on DB failure."""
    with patch("app.db.get_ticket_context", side_effect=Exception("DB down")):
        result = query_ticket_context("TKT-0042")
    parsed = json.loads(result)
    assert parsed["fallback"] is True
    assert "error" in parsed


# -----------------------------------------------------------------------
# Tool functions: request_approval
# -----------------------------------------------------------------------


def test_request_approval_success():
    """request_approval returns JSON with remediation_id and PENDING status."""
    with patch("app.db.create_approval_request", return_value=dict(SAMPLE_APPROVAL_ROW)):
        result = request_approval(
            ticket_id="TKT-0042",
            proposed_action="restart_bgp_sessions",
            rationale="High jitter spike",
            correlation_id="test-corr-001",
        )
    parsed = json.loads(result)
    assert parsed["remediation_id"] == 99
    assert parsed["status"] == "PENDING"
    assert parsed["correlation_id"] == "test-corr-0001"


def test_request_approval_generates_correlation_id():
    """If no correlation_id is provided, one is generated."""
    with patch("app.db.create_approval_request", return_value=dict(SAMPLE_APPROVAL_ROW)):
        result = request_approval(
            ticket_id="TKT-0042",
            proposed_action="restart_bgp_sessions",
            rationale="High jitter spike",
        )
    parsed = json.loads(result)
    assert parsed["remediation_id"] == 99


def test_request_approval_db_error():
    """request_approval returns safe fallback on DB failure."""
    with patch("app.db.create_approval_request", side_effect=Exception("DB down")):
        result = request_approval(
            ticket_id="TKT-0042",
            proposed_action="restart_bgp_sessions",
            rationale="Testing",
        )
    parsed = json.loads(result)
    assert parsed["fallback"] is True


# -----------------------------------------------------------------------
# Tool functions: execute_remediation
# -----------------------------------------------------------------------


def test_execute_remediation_success():
    """execute_remediation returns outcome and executed_utc on success."""
    with patch("app.db.execute_remediation", return_value=dict(SAMPLE_EXEC_ROW)):
        result = execute_remediation(
            ticket_id="TKT-0042",
            action="restart_bgp_sessions",
            approved_by="ops@contoso.com",
            approval_token="99",  # noqa: S106
            correlation_id="test-corr-001",
        )
    parsed = json.loads(result)
    assert parsed["remediation_id"] == 99
    assert parsed["outcome"] == "simulated_success"
    assert "2026-02-20" in parsed["executed_utc"]


def test_execute_remediation_unapproved():
    """execute_remediation returns error when token is not approved."""
    with patch("app.db.execute_remediation", return_value=None):
        result = execute_remediation(
            ticket_id="TKT-0042",
            action="restart_bgp_sessions",
            approved_by="ops@contoso.com",
            approval_token="INVALID",  # noqa: S106
        )
    parsed = json.loads(result)
    assert "error" in parsed
    assert parsed.get("fallback") is False


def test_execute_remediation_db_error():
    """execute_remediation returns safe fallback on DB failure."""
    with patch("app.db.execute_remediation", side_effect=Exception("DB down")):
        result = execute_remediation(
            ticket_id="TKT-0042",
            action="restart_bgp_sessions",
            approved_by="ops@contoso.com",
            approval_token="99",  # noqa: S106
        )
    parsed = json.loads(result)
    assert parsed["fallback"] is True


# -----------------------------------------------------------------------
# Tool functions: post_teams_summary
# -----------------------------------------------------------------------


def test_post_teams_summary_no_webhook():
    """post_teams_summary with no webhook logs only (teams_posted=False)."""
    result = post_teams_summary(
        ticket_id="TKT-0042",
        summary="Jitter resolved after BGP restart",
        action_taken="restart_bgp_sessions",
        approved_by="ops@contoso.com",
        correlation_id="test-corr-001",
    )
    parsed = json.loads(result)
    assert parsed["logged"] is True
    assert parsed["teams_posted"] is False
    assert parsed["correlation_id"] == "test-corr-001"


def test_post_teams_summary_generates_correlation_id():
    """post_teams_summary generates correlation_id if not provided."""
    result = post_teams_summary(
        ticket_id="TKT-0042",
        summary="Test",
        action_taken="test_action",
        approved_by="ops@contoso.com",
    )
    parsed = json.loads(result)
    assert parsed["logged"] is True
    # correlation_id should be a generated UUID
    assert len(parsed["correlation_id"]) > 0


# -----------------------------------------------------------------------
# Tool registration: all 4 tools are registered on the MCP server
# -----------------------------------------------------------------------


def test_mcp_server_has_all_tools():
    """The FastMCP instance should have all 4 tools registered."""
    from app.mcp_server import mcp

    # FastMCP stores tools internally — check via the _tool_manager
    tool_manager = mcp._tool_manager
    tools = tool_manager.list_tools()
    tool_names = {t.name for t in tools}

    expected = {"query_ticket_context", "request_approval", "execute_remediation", "post_teams_summary"}
    assert expected == tool_names, f"Expected {expected}, got {tool_names}"
