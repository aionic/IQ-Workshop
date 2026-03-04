# ============================================================================
# Dockerfile — IQ Foundry Agent Lab Tool Service
# Build: docker build --platform linux/amd64 -t iq-tools .
# Run:   docker run -p 8000:8000 --env-file ../../.env iq-tools
# ============================================================================

FROM python:3.12-slim AS base

# --- Install uv (fast Python package manager) ---
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# --- Install ODBC Driver 18 for SQL Server ---
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql18 \
        unixodbc-dev \
    && apt-get purge -y curl gnupg2 apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies (via uv, never pip) ---
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# --- Application code ---
COPY app/ ./app/

# --- Non-root user ---
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
