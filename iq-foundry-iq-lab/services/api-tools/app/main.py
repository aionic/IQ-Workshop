"""
main.py — FastAPI application for IQ Foundry Agent Lab tool endpoints.

Endpoints:
    POST /tools/query-ticket-context    — Read ticket + anomaly + device context
    POST /tools/request-approval        — Request approval for a proposed remediation
    POST /tools/execute-remediation     — Execute an approved remediation action
    POST /tools/post-teams-summary      — Post summary to Teams (stub/real)
    GET  /admin/approvals               — List pending approval requests
    POST /admin/approvals/{id}/decide   — Approve or reject a pending request
    GET  /health                        — Liveness/readiness check
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app import db
from app.logging_config import (
    CorrelationIdMiddleware,
    get_logger,
    setup_observability,
)
from app.schemas import (
    ApprovalRecord,
    DecideApprovalRequest,
    ErrorResponse,
    ExecuteRemediationRequest,
    ExecuteRemediationResponse,
    PostTeamsSummaryRequest,
    PostTeamsSummaryResponse,
    QueryTicketContextRequest,
    QueryTicketContextResponse,
    RequestApprovalRequest,
    RequestApprovalResponse,
)

logger = get_logger("iq-tools.api")


# -----------------------------------------------------------------------
# Lifespan (startup / shutdown)
# -----------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application startup & shutdown hooks."""
    setup_observability()
    db.init_db_pool()
    logger.info("Application started.")
    yield
    db.close_db_pool()
    logger.info("Application shut down.")


app = FastAPI(
    title="IQ Foundry Agent Lab — Tool Service",
    description="Tool endpoints for the IQ Foundry hosted agent workshop.",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(CorrelationIdMiddleware)


# -----------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------


@app.get("/health")
async def health():
    """Liveness/readiness check — verifies DB connectivity."""
    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        logger.warning("Health check DB probe failed: %s", exc)
        return {"status": "ok", "db": "unavailable"}


# -----------------------------------------------------------------------
# POST /tools/query-ticket-context
# -----------------------------------------------------------------------


@app.post(
    "/tools/query-ticket-context",
    response_model=QueryTicketContextResponse,
    responses={404: {"model": ErrorResponse}},
)
async def query_ticket_context(body: QueryTicketContextRequest, request: Request):
    """Return enriched ticket context with linked anomaly and device data."""
    logger.info("query-ticket-context ticket_id=%s", body.ticket_id)

    try:
        row = db.get_ticket_context(body.ticket_id)
    except Exception:
        logger.exception("DB error in query-ticket-context")
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable — safe fallback", "fallback": True},
        )

    if not row:
        raise HTTPException(status_code=404, detail=f"Ticket {body.ticket_id} not found")

    # Normalise datetime fields to ISO strings
    for dt_field in ("created_utc", "detected_utc"):
        val = row.get(dt_field)
        if val and hasattr(val, "isoformat"):
            row[dt_field] = val.isoformat()

    return QueryTicketContextResponse(**row)


# -----------------------------------------------------------------------
# POST /tools/request-approval
# -----------------------------------------------------------------------


@app.post(
    "/tools/request-approval",
    response_model=RequestApprovalResponse,
)
async def request_approval(body: RequestApprovalRequest, request: Request):
    """Create a PENDING approval request for a proposed remediation."""
    cid = body.correlation_id or getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.info("request-approval ticket_id=%s correlation_id=%s", body.ticket_id, cid)

    try:
        row = db.create_approval_request(
            ticket_id=body.ticket_id,
            proposed_action=body.proposed_action,
            rationale=body.rationale,
            correlation_id=cid,
        )
    except Exception:
        logger.exception("DB error in request-approval")
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable — safe fallback", "fallback": True},
        )

    return RequestApprovalResponse(
        remediation_id=row["remediation_id"],
        approval_token=str(row["remediation_id"]),
        status=row["status"],
        correlation_id=row["correlation_id"],
    )


# -----------------------------------------------------------------------
# POST /tools/execute-remediation
# -----------------------------------------------------------------------


@app.post(
    "/tools/execute-remediation",
    response_model=ExecuteRemediationResponse,
    responses={403: {"model": ErrorResponse}},
)
async def execute_remediation(body: ExecuteRemediationRequest, request: Request):
    """Execute an approved remediation action and update the ticket."""
    logger.info(
        "execute-remediation ticket_id=%s approval_token=%s correlation_id=%s",
        body.ticket_id,
        body.approval_token,
        body.correlation_id,
    )

    try:
        result = db.execute_remediation(
            ticket_id=body.ticket_id,
            action=body.action,
            approved_by=body.approved_by,
            approval_token=body.approval_token,
            correlation_id=body.correlation_id,
        )
    except Exception:
        logger.exception("DB error in execute-remediation")
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable — safe fallback", "fallback": True},
        )

    if not result:
        raise HTTPException(
            status_code=403,
            detail="Approval token not approved or invalid. Request approval first.",
        )

    # Normalise datetime
    executed = result.get("executed_utc")
    if executed and hasattr(executed, "isoformat"):
        executed = executed.isoformat()

    return ExecuteRemediationResponse(
        remediation_id=result["remediation_id"],
        outcome=result["outcome"],
        executed_utc=str(executed),
        correlation_id=result["correlation_id"],
    )


# -----------------------------------------------------------------------
# GET /admin/approvals
# -----------------------------------------------------------------------


@app.get(
    "/admin/approvals",
    response_model=list[ApprovalRecord],
)
async def list_approvals():
    """List all pending approval requests for admin review."""
    logger.info("list-approvals")
    try:
        rows = db.list_pending_approvals()
    except Exception:
        logger.exception("DB error in list-approvals")
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable — safe fallback", "fallback": True},
        )

    results = []
    for row in rows:
        for dt_field in ("approved_utc", "created_utc"):
            val = row.get(dt_field)
            if val and hasattr(val, "isoformat"):
                row[dt_field] = val.isoformat()
            elif val is None:
                row[dt_field] = None
        results.append(ApprovalRecord(**row))
    return results


# -----------------------------------------------------------------------
# POST /admin/approvals/{remediation_id}/decide
# -----------------------------------------------------------------------


@app.post(
    "/admin/approvals/{remediation_id}/decide",
    response_model=ApprovalRecord,
    responses={404: {"model": ErrorResponse}},
)
async def decide_approval_endpoint(remediation_id: int, body: DecideApprovalRequest):
    """Approve or reject a pending approval request."""
    logger.info(
        "decide-approval remediation_id=%d decision=%s approver=%s",
        remediation_id,
        body.decision,
        body.approver,
    )

    try:
        row = db.decide_approval(
            remediation_id=remediation_id,
            decision=body.decision,
            approver=body.approver,
        )
    except Exception:
        logger.exception("DB error in decide-approval")
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable — safe fallback", "fallback": True},
        )

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Remediation {remediation_id} not found or not PENDING.",
        )

    for dt_field in ("approved_utc", "created_utc"):
        val = row.get(dt_field)
        if val and hasattr(val, "isoformat"):
            row[dt_field] = val.isoformat()
        elif val is None:
            row[dt_field] = None

    return ApprovalRecord(**row)


# -----------------------------------------------------------------------
# POST /tools/post-teams-summary  (phase-3 stub)
# -----------------------------------------------------------------------


@app.post(
    "/tools/post-teams-summary",
    response_model=PostTeamsSummaryResponse,
)
async def post_teams_summary(body: PostTeamsSummaryRequest, request: Request):
    """Post a remediation summary to Teams.

    Phase 3 stub — logs the payload and returns logged=True.
    If TEAMS_WEBHOOK_URL is set, posts to the webhook.
    """
    import os

    cid = body.correlation_id
    logger.info("post-teams-summary ticket_id=%s correlation_id=%s", body.ticket_id, cid)

    teams_posted = False
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

    if webhook_url:
        try:
            import httpx

            payload = {
                "text": (
                    f"**Remediation Summary**\n\n"
                    f"- **Ticket:** {body.ticket_id}\n"
                    f"- **Action:** {body.action_taken}\n"
                    f"- **Approved by:** {body.approved_by}\n"
                    f"- **Summary:** {body.summary}\n"
                    f"- **Correlation:** {cid}"
                ),
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook_url, json=payload, timeout=10)
                teams_posted = resp.is_success
        except Exception:
            logger.exception("Teams webhook post failed")
    else:
        logger.info("TEAMS_WEBHOOK_URL not set — skipping Teams post, logging only.")

    return PostTeamsSummaryResponse(
        teams_posted=teams_posted,
        logged=True,
        correlation_id=cid,
    )
