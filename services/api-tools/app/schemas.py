"""
schemas.py — Pydantic v2 models for all request/response types.

All endpoints import their models from this module.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# -----------------------------------------------------------------------
# Shared
# -----------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Standardised error envelope returned by all endpoints."""

    detail: str
    fallback: bool = False


# -----------------------------------------------------------------------
# POST /tools/query-ticket-context
# -----------------------------------------------------------------------


class QueryTicketContextRequest(BaseModel):
    ticket_id: str = Field(..., examples=["TKT-0042"])


class QueryTicketContextResponse(BaseModel):
    ticket_id: str
    status: str
    priority: str
    severity: str
    signal_type: str
    device_id: str
    site_id: str
    model: str
    health_state: str
    metric_jitter_ms: float | None = None
    metric_loss_pct: float | None = None
    metric_latency_ms: float | None = None
    summary: str
    customer_id: str
    owner: str | None = None
    created_utc: str
    detected_utc: str


# -----------------------------------------------------------------------
# POST /tools/request-approval
# -----------------------------------------------------------------------


class RequestApprovalRequest(BaseModel):
    ticket_id: str
    proposed_action: str
    rationale: str
    correlation_id: str | None = None


class RequestApprovalResponse(BaseModel):
    remediation_id: int
    approval_token: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "EXECUTED"]
    correlation_id: str


# -----------------------------------------------------------------------
# POST /tools/execute-remediation
# -----------------------------------------------------------------------


class ExecuteRemediationRequest(BaseModel):
    ticket_id: str
    action: str
    approved_by: str
    approval_token: str
    correlation_id: str


class ExecuteRemediationResponse(BaseModel):
    remediation_id: int
    outcome: str
    executed_utc: str
    correlation_id: str


# -----------------------------------------------------------------------
# POST /tools/post-teams-summary (phase-3 stub)
# -----------------------------------------------------------------------


class PostTeamsSummaryRequest(BaseModel):
    ticket_id: str
    summary: str
    action_taken: str
    approved_by: str
    correlation_id: str


class PostTeamsSummaryResponse(BaseModel):
    teams_posted: bool
    logged: bool
    correlation_id: str


# -----------------------------------------------------------------------
# POST /admin/approvals/{remediation_id}/decide
# -----------------------------------------------------------------------


class DecideApprovalRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    approver: str


class ApprovalRecord(BaseModel):
    """A single pending/decided approval row."""

    remediation_id: int
    ticket_id: str
    proposed_action: str
    rationale: str | None = None
    status: str
    approved_by: str | None = None
    approved_utc: str | None = None
    correlation_id: str
    created_utc: str
