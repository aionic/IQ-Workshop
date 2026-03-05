-- ============================================================================
-- grant-permissions.sql — Managed Identity SQL Permissions
-- Run AFTER Bicep deployment as an Entra admin connected to sqldb-iq
-- ============================================================================
--
-- Prerequisites:
--   1. Managed identities created by Bicep (id-iq-tools-*, id-iq-agent-*)
--   2. You are connected as the Entra admin specified in Bicep parameters
--   3. Connected to the sqldb-iq database (not master)
--
-- Connection methods:
--   - Public mode: SSMS / Azure Data Studio / sqlcmd with Entra auth
--   - Private mode: Azure Cloud Shell or jumpbox within VNet
-- ============================================================================

-- HOW TO USE:
--   1. Run `az deployment group show -g <rg> -n main --query properties.outputs`
--   2. Copy the `toolsIdentityName` and `agentIdentityName` values
--   3. Replace the placeholders below with those values
--   4. Connect to sqldb-iq as the Entra admin, then execute this script
--
-- Example (if your Bicep outputs say):
--   toolsIdentityName = "id-iq-tools-iq-lab-dev"
--   agentIdentityName = "id-iq-agent-iq-lab-dev"

-- -----------------------------------------------------------------------
-- Tool Service Identity: read all tables + write to remediation log + update ticket status
-- -----------------------------------------------------------------------
CREATE USER [id-iq-tools-iq-lab-dev] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [id-iq-tools-iq-lab-dev];
GRANT INSERT ON dbo.iq_remediation_log TO [id-iq-tools-iq-lab-dev];
GRANT UPDATE ON dbo.iq_remediation_log TO [id-iq-tools-iq-lab-dev];
GRANT UPDATE ON dbo.iq_tickets TO [id-iq-tools-iq-lab-dev];
GO

-- -----------------------------------------------------------------------
-- Agent Identity: read-only access to all tables
-- -----------------------------------------------------------------------
CREATE USER [id-iq-agent-iq-lab-dev] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [id-iq-agent-iq-lab-dev];
GO

-- -----------------------------------------------------------------------
-- Verification: confirm both users exist and have expected roles
-- -----------------------------------------------------------------------
SELECT dp.name, dp.type_desc, rm.role_principal_id
FROM sys.database_principals dp
LEFT JOIN sys.database_role_members rm ON dp.principal_id = rm.member_principal_id
WHERE dp.name IN ('id-iq-tools-iq-lab-dev', 'id-iq-agent-iq-lab-dev');
GO

PRINT 'Managed identity permissions granted successfully.';
GO
