#!/bin/bash
# ============================================================================
# local-init.sh — Initialize local SQL Server container with schema + seed data
# Used by docker-compose.yml as the SQL Server entrypoint wrapper
# ============================================================================
set -e

SQLCMD="/opt/mssql-tools18/bin/sqlcmd"
DB_NAME="sqldb-iq"
INIT_DIR="/docker-entrypoint-initdb.d"
MAX_RETRIES=30
RETRY_INTERVAL=2

echo "[init] Starting SQL Server in the background..."
/opt/mssql/bin/sqlservr &
SQL_PID=$!

# -----------------------------------------------------------------------
# Wait for SQL Server to become ready
# -----------------------------------------------------------------------
echo "[init] Waiting for SQL Server to accept connections..."
retries=0
until $SQLCMD -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -Q "SELECT 1" -b -o /dev/null 2>/dev/null; do
    retries=$((retries + 1))
    if [ $retries -ge $MAX_RETRIES ]; then
        echo "[init] ERROR: SQL Server did not start within $((MAX_RETRIES * RETRY_INTERVAL))s"
        exit 1
    fi
    echo "[init]   ...retry $retries/$MAX_RETRIES"
    sleep $RETRY_INTERVAL
done
echo "[init] SQL Server is ready."

# -----------------------------------------------------------------------
# Create database if it doesn't exist
# -----------------------------------------------------------------------
echo "[init] Creating database [$DB_NAME] if not exists..."
$SQLCMD -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -Q \
    "IF DB_ID('$DB_NAME') IS NULL CREATE DATABASE [$DB_NAME];" -b

# -----------------------------------------------------------------------
# Run schema
# -----------------------------------------------------------------------
if [ -f "$INIT_DIR/schema.sql" ]; then
    echo "[init] Applying schema.sql..."
    $SQLCMD -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -d "$DB_NAME" -i "$INIT_DIR/schema.sql" -b
    echo "[init] schema.sql applied."
else
    echo "[init] WARNING: schema.sql not found at $INIT_DIR/schema.sql"
fi

# -----------------------------------------------------------------------
# Run seed data
# -----------------------------------------------------------------------
if [ -f "$INIT_DIR/seed.sql" ]; then
    echo "[init] Applying seed.sql..."
    $SQLCMD -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -d "$DB_NAME" -i "$INIT_DIR/seed.sql" -b
    echo "[init] seed.sql applied."
else
    echo "[init] WARNING: seed.sql not found at $INIT_DIR/seed.sql"
fi

echo "[init] ============================================"
echo "[init] Local SQL Server initialization complete."
echo "[init] Database: $DB_NAME"
echo "[init] Connection: localhost,1433 / sa / (SA_PASSWORD)"
echo "[init] ============================================"

# -----------------------------------------------------------------------
# Keep SQL Server running in the foreground
# -----------------------------------------------------------------------
wait $SQL_PID
