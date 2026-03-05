# ============================================================================
# Dockerfile — IQ Foundry Agent Lab Tool Service
# Build context: services/api-tools/
# Build: docker build --platform linux/amd64 -t iq-tools services/api-tools/
# Run:   docker run -p 8000:8000 --env-file .env iq-tools
# ============================================================================

FROM python:3.12-slim

# ---- System dependencies (ODBC 18 driver) ----------------------------------
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl gnupg2 apt-transport-https \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
        msodbcsql18 \
        unixodbc-dev \
    && apt-get purge -y curl gnupg2 apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# ---- Python dependencies ----------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv

WORKDIR /app
COPY requirements.txt .
RUN uv venv /app/.venv \
    && VIRTUAL_ENV=/app/.venv uv pip install --no-cache -r requirements.txt
ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV="/app/.venv"

# ---- Application code -------------------------------------------------------
COPY app/ ./app/

# ---- Non-root user -----------------------------------------------------------
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
