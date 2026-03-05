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

## Knowledge Grounding — Device Manuals

> These prompts test the agent's ability to use device operations manuals
> (uploaded as Foundry knowledge sources) to ground triage recommendations.

### Threshold Lookups

```
What is the critical jitter threshold for a Cisco ASR-9000?
```
> Expected: Agent cites 100 ms from the device manual

```
What are the warning and critical packet loss thresholds for the Nokia 7750 SR?
```
> Expected: Agent cites warning 1.0% and critical 5.0% from the manual

### CLI Command Lookups

```
What CLI command should I use to check BGP neighbor status on a Juniper MX960?
```
> Expected: Agent provides Junos command from the manual (e.g., `show bgp neighbor`)

```
How do I check interface error counters on an Arista 7280R3?
```
> Expected: Agent provides EOS-specific commands from the manual

### Hybrid Grounding (Tools + Knowledge)

```
Summarize ticket TKT-0042 and include the recommended diagnostic commands from the device manual.
```
> Expected: Combines ticket data (tool) with CLI commands (manual)

```
Triage TKT-0015 and compare the anomaly metrics against the device manual thresholds.
```
> Expected: Cites both actual metric values and manual threshold levels

```
What remediation steps does the operations manual recommend for the anomaly in TKT-0042?
```
> Expected: Ordered steps from the specific device model's manual

### Cross-Model Comparison

```
Compare the latency spike thresholds across Cisco ASR-9000 and Juniper MX960.
```
> Expected: Agent retrieves both manuals and compares threshold values

### Escalation Criteria

```
When should I escalate a link flap issue on a Nokia 7750 SR to the vendor?
```
> Expected: Agent cites escalation criteria from the Nokia manual

### Knowledge Boundary Testing

```
What are the jitter thresholds for a Huawei NE40E?
```
> Expected: Agent says "operations manual not available for this model" (not in knowledge)
