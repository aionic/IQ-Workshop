# Architecture — IQ Foundry Agent Lab

## Overview

The IQ Foundry Agent Lab demonstrates a production-shaped pattern for AI agent-assisted
network operations triage. A **Prompt Agent** in Azure AI Foundry uses gpt-4.1-mini with
Responses API compatible **function tools**. The tool service is **self-hosted on Azure
Container Apps** — a client program intercepts the agent’s `requires_action` events,
calls the FastAPI endpoints, and submits results back.

**Key architectural decisions**:
- The agent is a Foundry *Prompt Agent* (LLM-backed), not a hosted/containerized agent
- Tool calling uses **function tools** (Responses API compatible), not OpenAPI tools
- The FastAPI tool service runs independently on **Azure Container Apps** (self-hosted)
- A client-side loop (`chat_agent.py`) bridges the agent and tool service via HTTP

## Components

| Component | Technology | Purpose |
|---|---|---|
| Foundry Prompt Agent | Azure AI Foundry + gpt-4.1-mini | LLM orchestration, function tool definitions |
| AI Services + Project | Microsoft.CognitiveServices/accounts | Hosts model deployment + Foundry project |
| Tool Service | Python FastAPI on Azure Container Apps | Exposes tool endpoints (query, approve, execute) |
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
    end
    SQL[(Azure SQL<br/>sqldb-iq)]
    ACR[Azure Container Registry]
    AI[Application Insights]
    LA[Log Analytics Workspace]
  end

  U --> PA
  AIS --> PA
  PA -->|function tool calls| CA
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
  PA -->|function tool calls| CA
  CA -->|private endpoint| PE_SQL --> SQL
  CA -->|private endpoint| PE_ACR
  ACR --> PE_ACR
  CA -->|private endpoint| PE_MON --> AMPLS
  AMPLS --> AI --> LA
```

## Identity Boundaries

Two managed identities enforce the principle of least privilege:

| Identity | Resource | Permissions |
|---|---|---|
| `id-iq-tools` | Tool Service (Container App) | **Read**: `iq_tickets`, `iq_anomalies`, `iq_devices`. **Write**: `iq_remediation_log`, `iq_tickets.status` only |
| `id-iq-agent` | Foundry Prompt Agent | **No direct DB access.** Agent identity for Cognitive Services OpenAI User role. Client-side tool calls bridge to the tool service. |

Key rules:
- The agent identity **cannot** write to the database directly
- The tool service identity **cannot** modify core data tables (devices, anomalies)
- Azure SQL uses **AAD-only authentication** — no SQL admin passwords
- Managed identity tokens are cached with 5-minute proactive refresh

## Data Flow

A full triage → remediation cycle follows these steps:

```mermaid
sequenceDiagram
  participant User
  participant Agent as Foundry Agent
  participant API as Tool Service
  participant DB as Azure SQL
  participant AI as App Insights

  User->>Agent: "Summarize ticket TKT-0042"
  Agent->>API: POST /tools/query-ticket-context
  API->>DB: SELECT (3-table JOIN)
  DB-->>API: ticket + anomaly + device data
  API-->>Agent: QueryTicketContextResponse
  Agent-->>User: Triage summary (3 bullets)

  User->>Agent: "Execute remediation"
  Agent->>API: POST /tools/request-approval
  API->>DB: INSERT iq_remediation_log (PENDING)
  API-->>Agent: approval_token

  Note over User: Human approves via admin endpoint
  User->>API: POST /admin/approvals/{id}/decide
  API->>DB: UPDATE status=APPROVED

  Agent->>API: POST /tools/execute-remediation
  API->>DB: Validate APPROVED → INSERT outcome
  API->>DB: UPDATE iq_tickets.status
  API->>AI: Log with correlation_id
  API-->>Agent: ExecuteRemediationResponse
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
