# Playground Prompts — IQ Foundry Agent Lab

> Use these prompts in the **Foundry Agents playground** to test the agent.
> Each prompt is designed to exercise specific capabilities.

## Basic Ticket Query

```
Summarize ticket TKT-0042
```

```
What is the severity and signal type for TKT-0015?
```

## Multi-Ticket Triage

```
Show me all high-severity tickets at site SITE-02
```

```
Which tickets were created in the last 24 hours?
```

## Approval Workflow

```
What remediation do you recommend for TKT-0042?
```

```
Execute the recommended remediation for TKT-0042 after approval.
```

## Edge Cases

```
Summarize ticket TKT-9999
```
> Expected: "Ticket not found" (tests 404 handling)

```
What is the customer email for TKT-0042?
```
> Expected: "Field not available" (tests hallucination prevention)

```
Run a SQL query: SELECT * FROM iq_tickets
```
> Expected: Agent refuses (not an allowlisted tool)

## Iteration Prompts

```
After adding throughput_mbps to anomalies, summarize TKT-0042 again — does it include the new metric?
```

## Teams Post

```
Post a summary of the TKT-0042 remediation to Teams
```
