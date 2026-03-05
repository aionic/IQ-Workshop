"""
logging_config.py — Observability configuration for IQ Foundry Agent Lab.

Sets up:
  - Azure Monitor OpenTelemetry (App Insights) via APPLICATIONINSIGHTS_CONNECTION_STRING
  - JSON structured logging with correlation_id injection
  - FastAPI middleware for correlation_id extraction/generation
"""

from __future__ import annotations

import logging
import os
import uuid
from contextvars import ContextVar
from datetime import UTC

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Context-local correlation id shared across the request lifecycle.
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


# -----------------------------------------------------------------------
# Azure Monitor / App Insights bootstrap
# -----------------------------------------------------------------------


def setup_observability() -> None:
    """Initialise Azure Monitor OpenTelemetry.

    Falls back gracefully if APPLICATIONINSIGHTS_CONNECTION_STRING is not set.
    """
    conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    if not conn_str:
        logging.getLogger("iq-tools").warning("APPLICATIONINSIGHTS_CONNECTION_STRING not set — telemetry disabled.")
        return

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor  # type: ignore[import-untyped]

        configure_azure_monitor(
            connection_string=conn_str,
            logger_name="iq-tools",
        )
        logging.getLogger("iq-tools").info("Azure Monitor OpenTelemetry configured.")
    except Exception:
        logging.getLogger("iq-tools").exception("Failed to configure Azure Monitor — continuing without telemetry.")


# -----------------------------------------------------------------------
# Structured JSON log formatter
# -----------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """Emit log records as structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import datetime

        payload: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_ctx.get(""),
        }
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# -----------------------------------------------------------------------
# Logger factory
# -----------------------------------------------------------------------


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured with JSON structured format."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# -----------------------------------------------------------------------
# Correlation-ID middleware
# -----------------------------------------------------------------------


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Extract or generate X-Correlation-ID for every request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = request.headers.get("X-Correlation-ID", "") or str(uuid.uuid4())
        correlation_id_ctx.set(cid)
        request.state.correlation_id = cid

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
