"""
test_validation.py — Schema validation & input edge-case tests.

Verifies that malformed or missing input produces 422 Unprocessable Entity
(Pydantic validation) and that edge cases are handled gracefully.
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
    with patch("app.db.init_db_pool"), patch("app.db.close_db_pool"):
        yield


@pytest_asyncio.fixture
async def client(mock_init_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# -----------------------------------------------------------------------
# POST /tools/query-ticket-context — validation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_ticket_context_missing_body(client: AsyncClient):
    """Empty body → 422."""
    resp = await client.post("/tools/query-ticket-context", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_query_ticket_context_wrong_field_name(client: AsyncClient):
    """Wrong field name → 422."""
    resp = await client.post(
        "/tools/query-ticket-context",
        json={"id": "TKT-0042"},  # expected: ticket_id
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_query_ticket_context_no_json(client: AsyncClient):
    """No JSON content → 422."""
    resp = await client.post(
        "/tools/query-ticket-context",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------
# POST /tools/request-approval — validation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_missing_required_fields(client: AsyncClient):
    """Missing ticket_id and proposed_action → 422."""
    resp = await client.post(
        "/tools/request-approval",
        json={"rationale": "Just a rationale"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_request_approval_empty_body(client: AsyncClient):
    """Empty body → 422."""
    resp = await client.post("/tools/request-approval", json={})
    assert resp.status_code == 422


# -----------------------------------------------------------------------
# POST /tools/execute-remediation — validation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_remediation_missing_fields(client: AsyncClient):
    """Missing required fields → 422."""
    resp = await client.post(
        "/tools/execute-remediation",
        json={"ticket_id": "TKT-0042"},  # missing action, approved_by, etc.
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_execute_remediation_extra_fields_accepted(client: AsyncClient):
    """Extra fields should be silently ignored per Pydantic v2 defaults."""
    with patch(
        "app.main.db.execute_remediation",
        return_value={
            "remediation_id": 99,
            "executed_utc": "2026-02-20T12:00:00",
            "outcome": "Executed: Escalate",
            "correlation_id": "c-001",
        },
    ):
        resp = await client.post(
            "/tools/execute-remediation",
            json={
                "ticket_id": "TKT-0042",
                "action": "Escalate",
                "approved_by": "admin@contoso.com",
                "approval_token": "99",
                "correlation_id": "c-001",
                "extra_field": "should be ignored",
            },
        )
    assert resp.status_code == 200


# -----------------------------------------------------------------------
# POST /admin/approvals/{id}/decide — validation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_approval_invalid_decision(client: AsyncClient):
    """Decision not in [APPROVED, REJECTED] → 422."""
    resp = await client.post(
        "/admin/approvals/99/decide",
        json={"decision": "MAYBE", "approver": "admin@contoso.com"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_decide_approval_missing_approver(client: AsyncClient):
    """Missing approver → 422."""
    resp = await client.post(
        "/admin/approvals/99/decide",
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 422


# -----------------------------------------------------------------------
# POST /tools/post-teams-summary — validation
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teams_summary_missing_fields(client: AsyncClient):
    """Missing required fields → 422."""
    resp = await client.post(
        "/tools/post-teams-summary",
        json={"ticket_id": "TKT-0042"},  # missing summary, action_taken, etc.
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_teams_summary_empty_body(client: AsyncClient):
    """Empty body → 422."""
    resp = await client.post("/tools/post-teams-summary", json={})
    assert resp.status_code == 422
