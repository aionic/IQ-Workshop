"""
db.py — Database access layer for IQ Foundry Agent Lab.

All database interactions go through this module. No other module should import pyodbc.
Supports dual auth modes:
  - DB_AUTH_MODE=password  → local SQL Server container (SA auth)
  - DB_AUTH_MODE=token     → Azure SQL (Managed Identity token auth)

Environment variables:
  - AZURE_SQL_SERVER_FQDN  (default: localhost for local dev)
  - AZURE_SQL_DATABASE_NAME (default: sqldb-iq)
  - DB_AUTH_MODE            (default: password)
  - SA_PASSWORD             (only for local dev, DB_AUTH_MODE=password)
  - AZURE_CLIENT_ID         (user-assigned MI client ID, DB_AUTH_MODE=token)
"""

from __future__ import annotations

import logging
import os
import struct
import time
from typing import Any

import pyodbc

logger = logging.getLogger("iq-tools.db")

# -----------------------------------------------------------------------
# Module-level state
# -----------------------------------------------------------------------
_conn_str: str = ""
_auth_mode: str = "password"
_token_cache: dict[str, Any] = {"token": None, "expires_on": 0.0}
_SQL_TOKEN_SCOPE = "https://database.windows.net/.default"  # noqa: S105


# -----------------------------------------------------------------------
# Connection management
# -----------------------------------------------------------------------


def init_db_pool() -> None:
    """Build the ODBC connection string. Called once on FastAPI startup."""
    global _conn_str, _auth_mode

    server = os.getenv("AZURE_SQL_SERVER_FQDN", "localhost")
    database = os.getenv("AZURE_SQL_DATABASE_NAME", "sqldb-iq")
    _auth_mode = os.getenv("DB_AUTH_MODE", "password")

    driver = _find_odbc_driver()

    if _auth_mode == "password":
        sa_password = os.getenv("SA_PASSWORD", "")
        _conn_str = (
            f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
            f"UID=sa;PWD={sa_password};TrustServerCertificate=yes;"
        )
    else:
        # Token auth — connection string without credentials; token supplied per-connect.
        _conn_str = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Encrypt=yes;TrustServerCertificate=no;"

    logger.info("DB initialised (auth_mode=%s, server=%s, db=%s)", _auth_mode, server, database)


def close_db_pool() -> None:
    """Teardown hook (no persistent pool in pyodbc — placeholder)."""
    _token_cache["token"] = None
    _token_cache["expires_on"] = 0.0
    logger.info("DB pool closed.")


def get_connection() -> pyodbc.Connection:
    """Return a fresh pyodbc connection.

    For token auth, obtains (or refreshes) an AAD access token and passes
    it via the pyodbc ``attrs_before`` mechanism.
    """
    if _auth_mode == "password":
        return pyodbc.connect(_conn_str, autocommit=False)

    # Token auth path
    token = _get_sql_token()
    token_bytes = token.encode("utf-16-le")
    token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
    # SQL_COPT_SS_ACCESS_TOKEN = 1256
    return pyodbc.connect(_conn_str, attrs_before={1256: token_struct}, autocommit=False)


# -----------------------------------------------------------------------
# Token helpers
# -----------------------------------------------------------------------


def _get_sql_token() -> str:
    """Return a cached AAD token, refreshing proactively 5 min before expiry."""
    now = time.time()
    if _token_cache["token"] and (_token_cache["expires_on"] - now) > 300:
        return _token_cache["token"]

    client_id = os.getenv("AZURE_CLIENT_ID", "")
    try:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential  # type: ignore[import-untyped]

        if client_id:  # noqa: SIM108
            cred = ManagedIdentityCredential(client_id=client_id)
        else:
            cred = DefaultAzureCredential()

        result = cred.get_token(_SQL_TOKEN_SCOPE)
        _token_cache["token"] = result.token
        _token_cache["expires_on"] = result.expires_on
        logger.info("SQL token acquired (expires_on=%s)", result.expires_on)
        return result.token
    except Exception:
        logger.exception("Failed to acquire SQL AAD token")
        raise


def _find_odbc_driver() -> str:
    """Return the best available ODBC driver name."""
    preferred = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    available = pyodbc.drivers()
    for drv in preferred:
        if drv in available:
            return drv
    # Fallback — return 18 and let the error surface if missing
    return "ODBC Driver 18 for SQL Server"


def _row_to_dict(cursor: pyodbc.Cursor, row: pyodbc.Row) -> dict[str, Any]:
    """Convert a pyodbc Row to a plain dict using cursor.description."""
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row, strict=True))


# -----------------------------------------------------------------------
# Read operations
# -----------------------------------------------------------------------


def get_ticket_context(ticket_id: str) -> dict[str, Any] | None:
    """Return enriched ticket context via a 3-table parameterized JOIN.

    Returns ``None`` if the ticket does not exist.
    """
    sql = """
        SELECT
            t.ticket_id,
            t.status,
            t.priority,
            t.summary,
            t.customer_id,
            t.owner,
            t.created_utc,
            a.severity,
            a.signal_type,
            a.detected_utc,
            a.metric_jitter_ms,
            a.metric_loss_pct,
            a.metric_latency_ms,
            d.device_id,
            d.site_id,
            d.model,
            d.health_state
        FROM dbo.iq_tickets  t
        JOIN dbo.iq_anomalies a ON a.anomaly_id = t.anomaly_id
        JOIN dbo.iq_devices   d ON d.device_id  = a.device_id
        WHERE t.ticket_id = ?
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (ticket_id,))
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None
    finally:
        conn.close()


# -----------------------------------------------------------------------
# Write operations — approval workflow
# -----------------------------------------------------------------------


def create_approval_request(
    ticket_id: str,
    proposed_action: str,
    rationale: str,
    correlation_id: str,
) -> dict[str, Any]:
    """Insert a PENDING row into iq_remediation_log and return it."""
    sql = """
        INSERT INTO dbo.iq_remediation_log
            (ticket_id, proposed_action, rationale, status, correlation_id)
        OUTPUT
            INSERTED.remediation_id,
            INSERTED.status,
            INSERTED.correlation_id,
            INSERTED.created_utc
        VALUES (?, ?, ?, 'PENDING', ?)
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (ticket_id, proposed_action, rationale, correlation_id))
        row = cursor.fetchone()
        conn.commit()
        if row is None:
            msg = "INSERT … OUTPUT returned no row"
            raise RuntimeError(msg)
        return _row_to_dict(cursor, row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_approval(remediation_id: int) -> dict[str, Any] | None:
    """Fetch a single remediation log row by its PK."""
    sql = """
        SELECT remediation_id, ticket_id, proposed_action, rationale,
               status, approved_by, approved_utc, correlation_id, created_utc
        FROM dbo.iq_remediation_log
        WHERE remediation_id = ?
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (remediation_id,))
        row = cursor.fetchone()
        return _row_to_dict(cursor, row) if row else None
    finally:
        conn.close()


def list_pending_approvals() -> list[dict[str, Any]]:
    """Return all remediation rows with status = PENDING."""
    sql = """
        SELECT remediation_id, ticket_id, proposed_action, rationale,
               status, approved_by, approved_utc, correlation_id, created_utc
        FROM dbo.iq_remediation_log
        WHERE status = 'PENDING'
        ORDER BY created_utc DESC
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        return [_row_to_dict(cursor, r) for r in cursor.fetchall()]
    finally:
        conn.close()


def decide_approval(
    remediation_id: int,
    decision: str,
    approver: str,
) -> dict[str, Any] | None:
    """Set a PENDING row to APPROVED or REJECTED."""
    sql = """
        UPDATE dbo.iq_remediation_log
        SET status = ?, approved_by = ?, approved_utc = GETUTCDATE()
        OUTPUT
            INSERTED.remediation_id,
            INSERTED.ticket_id,
            INSERTED.proposed_action,
            INSERTED.rationale,
            INSERTED.status,
            INSERTED.approved_by,
            INSERTED.approved_utc,
            INSERTED.correlation_id,
            INSERTED.created_utc
        WHERE remediation_id = ? AND status = 'PENDING'
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (decision, approver, remediation_id))
        row = cursor.fetchone()
        conn.commit()
        return _row_to_dict(cursor, row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_remediation(
    ticket_id: str,
    action: str,
    approved_by: str,
    approval_token: str,
    correlation_id: str,
) -> dict[str, Any] | None:
    """Validate the approval is APPROVED, record the outcome, and update ticket status.

    ``approval_token`` is the ``remediation_id`` stringified by the caller.
    Returns the updated row, or ``None`` if validation fails.
    """
    try:
        rem_id = int(approval_token)
    except (ValueError, TypeError):
        return None

    conn = get_connection()
    try:
        cursor = conn.cursor()

        # 1. Validate approval + ticket binding and record execution atomically
        outcome = f"Executed: {action}"
        cursor.execute(
            """
            UPDATE dbo.iq_remediation_log
            SET status = 'EXECUTED',
                executed_utc = GETUTCDATE(),
                outcome = ?
            OUTPUT
                INSERTED.remediation_id,
                INSERTED.executed_utc,
                INSERTED.outcome,
                INSERTED.correlation_id
            WHERE remediation_id = ?
              AND ticket_id = ?
              AND status = 'APPROVED'
            """,
            (outcome, rem_id, ticket_id),
        )
        result = cursor.fetchone()
        if result is None:
            return None
        # Capture column metadata before the next statement resets cursor.description
        result_dict = _row_to_dict(cursor, result)

        # 3. Update ticket status to Investigate
        cursor.execute(
            "UPDATE dbo.iq_tickets SET status = 'Investigate' WHERE ticket_id = ?",
            (ticket_id,),
        )

        conn.commit()
        return result_dict
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
