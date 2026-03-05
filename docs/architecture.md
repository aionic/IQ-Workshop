# Architecture — IQ Foundry Agent Lab

## Overview

The IQ Foundry Agent Lab demonstrates a production-shaped pattern for AI agent-assisted
network operations triage. A **Prompt Agent** in Azure AI Foundry uses gpt-4.1-mini with
Responses API and **MCP tools**. The tool service is **self-hosted on Azure
Container Apps** — the Foundry Agent Service connects directly to the MCP server
for tool discovery and execution, with human-in-the-loop approval via the Responses API.

The tool service also exposes an **MCP (Model Context Protocol) server** at `/mcp` via
Streamable HTTP transport, which is the **primary integration path** for the Foundry Agent
Service. Foundry agents connect directly to the MCP server — no client-side tool loop
needed for tool execution.

**Key architectural decisions**:
- The agent is a Foundry *Prompt Agent* (LLM-backed), not a hosted/containerized agent
- Tool calling uses **MCP (Streamable HTTP)** as the primary path; legacy function tools are deprecated
- The FastAPI tool service runs independently on **Azure Container Apps** (self-hosted)
- Foundry Agent Service connects directly to the MCP server at `/mcp` — no client-side tool loop needed
- MCP Server co-hosted on the same Container App provides tool discovery and execution
- `chat_agent.py` uses Responses API with MCP approval flow (approve/reject tool calls)
- All deployment scripts ship in both PowerShell and Bash for cross-platform support (Windows/macOS/Linux)

## Components

| Component | Technology | Purpose |
|---|---|---|
| Foundry Prompt Agent | Azure AI Foundry + gpt-4.1-mini | LLM orchestration, MCP tool definitions |
| AI Services + Project | Microsoft.CognitiveServices/accounts | Hosts model deployment + Foundry project |
| Tool Service | Python FastAPI on Azure Container Apps | Exposes REST (deprecated) + MCP tool endpoints |
| MCP Server | FastMCP co-hosted on Tool Service at `/mcp` | Streamable HTTP tool discovery/execution (primary) |
| Database | Azure SQL (deployed) / SQL Server 2022 (local) | Stores tickets, anomalies, devices, remediation log |
| Observability | Application Insights + OpenTelemetry | Structured logging with correlation_id |
| Identity | Entra ID + Managed Identity | Token-based auth, no passwords in Azure |

## Architecture Diagram — Public Mode

```mermaid
flowchart LR
  subgraph Internet
    U[User in Foundry Playground]
  end

  subgraph Azure["Azure Resource Group"]
    subgraph Foundry["AI Foundry"]
      AIS[AI Services<br/>ai-iq-lab-dev]
      PROJ[Foundry Project<br/>iq-lab-project]
      PA[Prompt Agent<br/>gpt-4.1-mini]
    end
    subgraph CAE["Container Apps Environment"]
      CA[Tool Service<br/>FastAPI :8000]
      MCP[MCP Server<br/>Streamable HTTP at /mcp]
    end
    SQL[(Azure SQL<br/>sqldb-iq)]
    ACR[Azure Container Registry]
    AI[Application Insights]
    LA[Log Analytics Workspace]
  end

  U --> PA
  AIS --> PA
  PA -->|MCP Streamable HTTP| MCP
  MCP --> CA
  CA -->|token auth<br/>id-iq-tools MI| SQL
  CA -->|telemetry| AI
  AI --> LA
  ACR -->|image pull| CA
```

## Architecture Diagram — Private Mode

```mermaid
flowchart LR
  subgraph Internet
    U[User in Foundry Playground]
  end

  subgraph Azure["Azure Resource Group"]
    subgraph Foundry["AI Foundry"]
      PA[Prompt Agent<br/>gpt-4.1-mini]
    end
    subgraph VNet["vnet-iq-lab"]
      subgraph sn_app["sn-container-apps"]
        CA[Tool Service<br/>FastAPI :8000]
      end
      subgraph sn_data["sn-data"]
        PE_SQL[Private Endpoint<br/>Azure SQL]
        PE_ACR[Private Endpoint<br/>ACR]
      end
      subgraph sn_mon["sn-monitor"]
        PE_MON[Private Endpoint<br/>AMPLS]
      end
    end
    SQL[(Azure SQL<br/>publicNetworkAccess: Disabled)]
    ACR[ACR<br/>publicNetworkAccess: Disabled]
    AI[Application Insights]
    LA[Log Analytics]
    AMPLS[Azure Monitor<br/>Private Link Scope]
  end

  U --> PA
  PA -->|MCP Streamable HTTP| CA
  CA -->|private endpoint| PE_SQL --> SQL
  CA -->|private endpoint| PE_ACR
  ACR --> PE_ACR
  CA -->|private endpoint| PE_MON --> AMPLS
  AMPLS --> AI --> LA
```

## Identity Boundaries

Two managed identities enforce the principle of least privilege.
Bicep names them with the environment suffix (e.g., `id-iq-tools-iq-lab-dev` for `dev`):

| Identity | Resource | Permissions |
|---|---|---|
| `id-iq-tools-{suffix}` | Tool Service (Container App) | **Read**: `iq_tickets`, `iq_anomalies`, `iq_devices`. **Write**: `iq_remediation_log`, `iq_tickets.status` only |
| `id-iq-agent-{suffix}` | Foundry Prompt Agent | **No direct DB access.** Agent identity for Cognitive Services OpenAI User role. Client-side tool calls bridge to the tool service. |

Key rules:
- The agent identity **cannot** write to the database directly
- The tool service identity **cannot** modify core data tables (devices, anomalies)
- Azure SQL uses **AAD-only authentication** — no SQL admin passwords
- Managed identity tokens are cached with 5-minute proactive refresh

## Data Flow

A full triage → remediation cycle follows these steps:

### MCP Flow (Primary)

```mermaid
sequenceDiagram
  participant User
  participant Agent as Foundry Agent
  participant MCP as MCP Server (/mcp)
  participant DB as Azure SQL
  participant AI as App Insights

  User->>Agent: "Summarize ticket TKT-0042"
  Agent->>MCP: tool_call: query_ticket_context
  Note over Agent,MCP: Streamable HTTP (auto-approved)
  MCP->>DB: SELECT (3-table JOIN)
  DB-->>MCP: ticket + anomaly + device data
  MCP-->>Agent: QueryTicketContextResponse
  Agent-->>User: Triage summary (≤6 bullets)

  User->>Agent: "Execute remediation"
  Agent->>MCP: tool_call: request_approval
  Note over Agent,MCP: Auto-approved (read-only)
  MCP->>DB: INSERT iq_remediation_log (PENDING)
  MCP-->>Agent: approval_token

  Note over User: Human approves via admin endpoint
  User->>MCP: POST /admin/approvals/{id}/decide
  MCP->>DB: UPDATE status=APPROVED

  Agent->>MCP: tool_call: execute_remediation
  Note over Agent,MCP: Requires human approval (governance)
  MCP->>DB: Validate APPROVED → INSERT outcome
  MCP->>DB: UPDATE iq_tickets.status
  MCP->>AI: Log with correlation_id
  MCP-->>Agent: ExecuteRemediationResponse
  Agent-->>User: "Remediation executed"
```

### Legacy REST Flow (Deprecated)

```mermaid
sequenceDiagram
  participant User
  participant Agent as Foundry Agent
  participant Client as chat_agent.py
  participant API as Tool Service (REST)
  participant DB as Azure SQL
  participant AI as App Insights

  User->>Agent: "Summarize ticket TKT-0042"
  Agent->>Client: requires_action: query_ticket_context
  Client->>API: POST /tools/query-ticket-context
  API->>DB: SELECT (3-table JOIN)
  DB-->>API: ticket + anomaly + device data
  API-->>Client: QueryTicketContextResponse
  Client->>Agent: submit_tool_outputs
  Agent-->>User: Triage summary (≤6 bullets)

  User->>Agent: "Execute remediation"
  Agent->>Client: requires_action: request_approval
  Client->>API: POST /tools/request-approval
  API->>DB: INSERT iq_remediation_log (PENDING)
  API-->>Client: approval_token
  Client->>Agent: submit_tool_outputs

  Note over User: Human approves via admin endpoint
  User->>API: POST /admin/approvals/{id}/decide
  API->>DB: UPDATE status=APPROVED

  Agent->>Client: requires_action: execute_remediation
  Client->>API: POST /tools/execute-remediation
  API->>DB: Validate APPROVED → INSERT outcome
  API->>DB: UPDATE iq_tickets.status
  API->>AI: Log with correlation_id
  API-->>Client: ExecuteRemediationResponse
  Client->>Agent: submit_tool_outputs
  Agent-->>User: "Remediation executed"
```

## Network Topology

The `networkMode` parameter in `main.bicep` controls the deployment topology:

| Feature | `public` (workshop default) | `private` (enterprise) |
|---|---|---|
| Azure SQL | Public endpoint + firewall | Private endpoint only, publicNetworkAccess disabled |
| ACR | Public pull | Private endpoint, `az acr build` from Cloud Shell |
| App Insights | Public ingestion | AMPLS (Azure Monitor Private Link Scope) |
| VNet | Not created | 3 subnets: container-apps, data, monitor |
| DNS | Default Azure DNS | 3 Private DNS Zones (SQL, ACR, Monitor) |
| Container Apps | Public ingress | VNet-injected, internal ingress available |

Both modes use managed identity for all authentication — no passwords in any Azure deployment.

## Knowledge Grounding — Device Manuals

The agent uses **hybrid grounding**: structured data from MCP tools (live ticket/anomaly/device
fields) combined with unstructured knowledge from device operations manuals indexed in a
Foundry vector store.

### Knowledge Sources

| Source | Type | Content |
|---|---|---|
| 7 device manuals (`data/manuals/*.md`) | Vector store (file_search) | Per-model thresholds, CLI commands, remediation steps, escalation criteria |
| `docs/guardrails.md` | Vector store (file_search) | Agent behavioral rules |
| `docs/runbook.md` | Vector store (file_search) | Standard operating procedures |

### Registration Flow

```mermaid
sequenceDiagram
  participant Script as create_agent.py
  participant Foundry as AI Foundry
  participant VS as Vector Store
  participant Agent as Prompt Agent

  Script->>Foundry: files.upload() × 9 files
  Foundry-->>Script: file_ids[]
  Script->>Foundry: vector_stores.create(file_ids)
  Foundry->>VS: Index files (chunking + embedding)
  Foundry-->>Script: vector_store_id
  Script->>Foundry: agents.create_version(tools=[MCPTool, FileSearchTool])
  Foundry-->>Script: agent_version
```

### Hybrid Grounding at Runtime

```mermaid
flowchart LR
  U[User: Triage TKT-0042] --> A[Foundry Agent]
  A -->|MCP tool call| T[query_ticket_context]
  T --> D[(Azure SQL)]
  D -->|model: Nokia 7750 SR\nsignal: bgp_instability| T
  T -->|structured data| A
  A -->|file_search| VS[(Vector Store\nDevice Manuals)]
  VS -->|Nokia 7750 SR manual\nBGP section| A
  A -->|Grounded response:\ndata + manual guidance| U
```

The agent cites both sources in triage summaries — metric values from tools and
thresholds/CLI commands from the device manual. The `--no-knowledge` flag on
`create_agent.py` disables knowledge upload for baseline comparison.

## Evaluation Architecture

The eval framework tests the agent end-to-end against the live tool service:

```mermaid
flowchart LR
  R[run_evals.py] -->|prompt via\nResponses API| A[Foundry Agent\ngpt-4.1-mini]
  A -->|MCP tool calls| T[Tool Service\nFastAPI :8000]
  T --> DB[(Azure SQL)]
  A -->|MCP approval\nrequests| R
  R -->|approve +\nprevious_response_id| A
  A -->|response| R
  R --> S[scorers.py\n6 scorers]
  S --> J[results/*.json\nJSON report]
```

| Scorer | What it checks |
|---|---|
| `score_tool_calls` | Expected tools called, no unexpected tools |
| `score_grounding` | Response contains required terms, excludes forbidden ones |
| `score_format` | Bullet count and structure compliance |
| `score_safety` | Refusals, hallucination prevention, approval mentions |
| `score_tool_call_args` | Correct function arguments (ticket_id, etc.) |
| `score_knowledge` | Device manual citations, threshold references, CLI commands |
