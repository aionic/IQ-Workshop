-- ============================================================================
-- schema.sql — IQ Foundry Agent Lab Database Schema
-- Target: Azure SQL / SQL Server 2022 Developer Edition (local)
-- ============================================================================
-- Run this script against the sqldb-iq database.
-- For local dev: sqlcmd -S localhost -U sa -P <password> -d sqldb-iq -i schema.sql
-- For Azure SQL: connect as Entra admin via SSMS / Azure Data Studio / sqlcmd

-- Drop tables if they exist (for re-runs)
IF OBJECT_ID('dbo.iq_remediation_log', 'U') IS NOT NULL DROP TABLE dbo.iq_remediation_log;
IF OBJECT_ID('dbo.iq_tickets', 'U') IS NOT NULL DROP TABLE dbo.iq_tickets;
IF OBJECT_ID('dbo.iq_anomalies', 'U') IS NOT NULL DROP TABLE dbo.iq_anomalies;
IF OBJECT_ID('dbo.iq_devices', 'U') IS NOT NULL DROP TABLE dbo.iq_devices;
GO

-- -----------------------------------------------------------------------
-- Table: iq_devices
-- Simulated network devices across multiple sites
-- -----------------------------------------------------------------------
CREATE TABLE dbo.iq_devices (
    device_id       NVARCHAR(20)    NOT NULL,   -- e.g., DEV-0001
    site_id         NVARCHAR(20)    NOT NULL,   -- e.g., SITE-01
    model           NVARCHAR(100)   NOT NULL,   -- device model name
    last_seen_utc   DATETIME2(0)    NOT NULL,   -- last heartbeat timestamp
    health_state    NVARCHAR(20)    NOT NULL,   -- Healthy, Degraded, Offline

    CONSTRAINT PK_iq_devices PRIMARY KEY (device_id)
);
GO

CREATE INDEX IX_iq_devices_site ON dbo.iq_devices (site_id);
CREATE INDEX IX_iq_devices_health ON dbo.iq_devices (health_state);
GO

-- -----------------------------------------------------------------------
-- Table: iq_anomalies
-- Detected anomalies linked to devices
-- -----------------------------------------------------------------------
CREATE TABLE dbo.iq_anomalies (
    anomaly_id          NVARCHAR(20)    NOT NULL,   -- e.g., ANM-0001
    device_id           NVARCHAR(20)    NOT NULL,   -- FK to iq_devices
    detected_utc        DATETIME2(0)    NOT NULL,   -- when anomaly was detected
    severity            NVARCHAR(10)    NOT NULL,   -- Critical, High, Medium, Low
    signal_type         NVARCHAR(30)    NOT NULL,   -- jitter_spike, packet_loss, latency_spike, etc.
    metric_jitter_ms    DECIMAL(10,2)   NULL,       -- jitter in milliseconds
    metric_loss_pct     DECIMAL(5,2)    NULL,       -- packet loss percentage
    metric_latency_ms   DECIMAL(10,2)   NULL,       -- latency in milliseconds

    CONSTRAINT PK_iq_anomalies PRIMARY KEY (anomaly_id),
    CONSTRAINT FK_iq_anomalies_device FOREIGN KEY (device_id) REFERENCES dbo.iq_devices (device_id)
);
GO

CREATE INDEX IX_iq_anomalies_device ON dbo.iq_anomalies (device_id);
CREATE INDEX IX_iq_anomalies_severity ON dbo.iq_anomalies (severity);
CREATE INDEX IX_iq_anomalies_detected ON dbo.iq_anomalies (detected_utc);
GO

-- -----------------------------------------------------------------------
-- Table: iq_tickets
-- Triage tickets linked to anomalies
-- -----------------------------------------------------------------------
CREATE TABLE dbo.iq_tickets (
    ticket_id       NVARCHAR(20)    NOT NULL,   -- e.g., TKT-0001
    anomaly_id      NVARCHAR(20)    NOT NULL,   -- FK to iq_anomalies
    status          NVARCHAR(20)    NOT NULL,   -- New, Investigate, Monitor, Closed
    owner           NVARCHAR(100)   NULL,       -- assigned operator
    created_utc     DATETIME2(0)    NOT NULL,   -- ticket creation timestamp
    summary         NVARCHAR(500)   NOT NULL,   -- short description of the issue
    customer_id     NVARCHAR(20)    NOT NULL,   -- e.g., CUST-001
    priority        NVARCHAR(10)    NOT NULL,   -- P1, P2, P3, P4

    CONSTRAINT PK_iq_tickets PRIMARY KEY (ticket_id),
    CONSTRAINT FK_iq_tickets_anomaly FOREIGN KEY (anomaly_id) REFERENCES dbo.iq_anomalies (anomaly_id)
);
GO

CREATE INDEX IX_iq_tickets_anomaly ON dbo.iq_tickets (anomaly_id);
CREATE INDEX IX_iq_tickets_status ON dbo.iq_tickets (status);
CREATE INDEX IX_iq_tickets_priority ON dbo.iq_tickets (priority);
CREATE INDEX IX_iq_tickets_created ON dbo.iq_tickets (created_utc);
GO

-- -----------------------------------------------------------------------
-- Table: iq_remediation_log
-- Audit trail for all remediation actions (approval + execution)
-- -----------------------------------------------------------------------
CREATE TABLE dbo.iq_remediation_log (
    remediation_id  INT             NOT NULL IDENTITY(1,1),  -- auto-increment PK
    ticket_id       NVARCHAR(20)    NOT NULL,   -- FK to iq_tickets
    proposed_action NVARCHAR(500)   NOT NULL,   -- what was proposed
    rationale       NVARCHAR(500)   NULL,       -- why it was proposed
    status          NVARCHAR(20)    NOT NULL DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED, EXECUTED
    approved_by     NVARCHAR(100)   NULL,       -- who approved (operator email/name)
    approved_utc    DATETIME2(0)    NULL,       -- when approved
    executed_utc    DATETIME2(0)    NULL,       -- when executed
    outcome         NVARCHAR(500)   NULL,       -- result of execution
    correlation_id  NVARCHAR(50)    NOT NULL,   -- UUID for tracing the full chain
    created_utc     DATETIME2(0)    NOT NULL DEFAULT GETUTCDATE(), -- when the request was created

    CONSTRAINT PK_iq_remediation_log PRIMARY KEY (remediation_id),
    CONSTRAINT FK_iq_remediation_log_ticket FOREIGN KEY (ticket_id) REFERENCES dbo.iq_tickets (ticket_id)
);
GO

CREATE INDEX IX_iq_remediation_log_ticket ON dbo.iq_remediation_log (ticket_id);
CREATE INDEX IX_iq_remediation_log_status ON dbo.iq_remediation_log (status);
CREATE INDEX IX_iq_remediation_log_correlation ON dbo.iq_remediation_log (correlation_id);
GO

PRINT 'Schema created successfully.';
GO
