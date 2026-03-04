"""
mcp_server.py — MCP (Model Context Protocol) server for IQ Foundry Agent Lab.

Co-hosted on the same ASGI application as the FastAPI tool service.
Exposes the same 4 tools via the MCP protocol using FastMCP with
Streamable HTTP transport.

Mount point: /mcp (configured via streamable_http_path)

Tools:
    query_ticket_context   — Read ticket + anomaly + device context
    request_approval       — Request approval for a proposed remediation
    execute_remediation    — Execute an approved remediation action
    post_teams_summary     — Post summary to Teams (stub/real)
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from app import db
from app.logging_config import correlation_id_ctx, get_logger

logger = get_logger("iq-tools.mcp")

# ---------------------------------------------------------------------------
# FastMCP instance — stateless HTTP with JSON responses for scalability
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "IQ Tool Service",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


# ---------------------------------------------------------------------------
# Helper: normalise datetime fields to ISO strings
# ---------------------------------------------------------------------------


def _normalise_datetimes(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Convert datetime objects to ISO-8601 strings in-place."""
    for field in fields:
        val = row.get(field)
        if val and hasattr(val, "isoformat"):
            row[field] = val.isoformat()
    return row


def _ensure_correlation_id(correlation_id: str | None) -> str:
    """Return the provided correlation_id or generate a new UUID."""
    cid = correlation_id or str(uuid.uuid4())
    # Set on the context var so structured logs pick it up
    correlation_id_ctx.set(cid)
    return cid


# ---------------------------------------------------------------------------
# Tool: query_ticket_context
# ---------------------------------------------------------------------------


@mcp.tool()
def query_ticket_context(ticket_id: str) -> str:
    """Query ticket context with linked anomaly and device data.

    Returns minimal structured fields for a given ticket: ticket metadata,
    anomaly metrics, and device/site info. Only scoped fields are returned.

    :param ticket_id: The ticket identifier (e.g. TKT-0042).
    :return: JSON with ticket metadata, anomaly metrics, and device/site info.
    """
    logger.info("mcp query_ticket_context ticket_id=%s", ticket_id)

    try:
        row = db.get_ticket_context(ticket_id)
    except Exception:
        logger.exception("DB error in mcp query_ticket_context")
        return json.dumps({"error": "Database unavailable — safe fallback", "fallback": True})

    if not row:
        return json.dumps({"error": f"Ticket {ticket_id} not found", "fallback": False})

    _normalise_datetimes(row, ["created_utc", "detected_utc"])
    return json.dumps(row, default=str)


# ---------------------------------------------------------------------------
# Tool: request_approval
# ---------------------------------------------------------------------------


@mcp.tool()
def request_approval(
    ticket_id: str,
    proposed_action: str,
    rationale: str,
    correlation_id: str = "",
) -> str:
    """Request approval for a proposed remediation action.

    Creates a pending approval request. Returns an approval_token and sets
    status to PENDING. The request must be approved via the admin endpoint
    before execution.

    :param ticket_id: Ticket to remediate.
    :param proposed_action: Action to perform (e.g. restart_bgp_sessions).
    :param rationale: Why this action is appropriate.
    :param correlation_id: Optional correlation ID for tracing.
    :return: JSON with remediation_id, approval_token, status, and correlation_id.
    """
    cid = _ensure_correlation_id(correlation_id or None)
    logger.info("mcp request_approval ticket_id=%s correlation_id=%s", ticket_id, cid)

    try:
        row = db.create_approval_request(
            ticket_id=ticket_id,
            proposed_action=proposed_action,
            rationale=rationale,
            correlation_id=cid,
        )
    except Exception:
        logger.exception("DB error in mcp request_approval")
        return json.dumps({"error": "Database unavailable — safe fallback", "fallback": True})

    result = {
        "remediation_id": row["remediation_id"],
        "approval_token": str(row["remediation_id"]),
        "status": row["status"],
        "correlation_id": row["correlation_id"],
    }
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Tool: execute_remediation
# ---------------------------------------------------------------------------


@mcp.tool()
def execute_remediation(
    ticket_id: str,
    action: str,
    approved_by: str,
    approval_token: str,
    correlation_id: str = "",
) -> str:
    """Execute an approved remediation action.

    Validates the approval token is APPROVED, writes a remediation log entry,
    and updates the ticket status. Requires a valid, approved approval_token.

    :param ticket_id: The ticket identifier.
    :param action: The action to execute.
    :param approved_by: Email of the person who approved.
    :param approval_token: Token from request_approval (must be APPROVED).
    :param correlation_id: Correlation ID for tracing.
    :return: JSON with remediation_id, outcome, executed_utc, and correlation_id.
    """
    cid = _ensure_correlation_id(correlation_id or None)
    logger.info(
        "mcp execute_remediation ticket_id=%s approval_token=%s correlation_id=%s",
        ticket_id,
        approval_token,
        cid,
    )

    try:
        result = db.execute_remediation(
            ticket_id=ticket_id,
            action=action,
            approved_by=approved_by,
            approval_token=approval_token,
            correlation_id=cid,
        )
    except Exception:
        logger.exception("DB error in mcp execute_remediation")
        return json.dumps({"error": "Database unavailable — safe fallback", "fallback": True})

    if not result:
        return json.dumps({
            "error": "Approval token not approved or invalid. Request approval first.",
            "fallback": False,
        })

    executed = result.get("executed_utc")
    if executed and hasattr(executed, "isoformat"):
        executed = executed.isoformat()

    return json.dumps({
        "remediation_id": result["remediation_id"],
        "outcome": result["outcome"],
        "executed_utc": str(executed),
        "correlation_id": result["correlation_id"],
    }, default=str)


# ---------------------------------------------------------------------------
# Tool: post_teams_summary
# ---------------------------------------------------------------------------


@mcp.tool()
def post_teams_summary(
    ticket_id: str,
    summary: str,
    action_taken: str,
    approved_by: str,
    correlation_id: str = "",
) -> str:
    """Post a remediation summary to Microsoft Teams.

    Posts a triage/remediation summary to a Teams channel via webhook.
    If no webhook is configured, the payload is logged and teams_posted
    returns false. Always logs the payload for audit.

    :param ticket_id: The ticket identifier.
    :param summary: Summary text.
    :param action_taken: Action that was executed.
    :param approved_by: Approver email.
    :param correlation_id: Correlation ID for tracing.
    :return: JSON with teams_posted, logged, and correlation_id.
    """
    cid = _ensure_correlation_id(correlation_id or None)
    logger.info("mcp post_teams_summary ticket_id=%s correlation_id=%s", ticket_id, cid)

    teams_posted = False
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL", "")

    if webhook_url:
        try:
            import httpx

            payload = {
                "text": (
                    f"**Remediation Summary**\n\n"
                    f"- **Ticket:** {ticket_id}\n"
                    f"- **Action:** {action_taken}\n"
                    f"- **Approved by:** {approved_by}\n"
                    f"- **Summary:** {summary}\n"
                    f"- **Correlation:** {cid}"
                ),
            }
            resp = httpx.post(webhook_url, json=payload, timeout=10)
            teams_posted = resp.is_success
        except Exception:
            logger.exception("Teams webhook post failed")
    else:
        logger.info("TEAMS_WEBHOOK_URL not set — skipping Teams post, logging only.")

    return json.dumps({
        "teams_posted": teams_posted,
        "logged": True,
        "correlation_id": cid,
    })
