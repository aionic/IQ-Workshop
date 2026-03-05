# Nokia 7750 SR — IQ Operations Manual

> **Vendor:** Nokia  
> **Family:** 7750 SR Series  
> **Role:** Service edge router / PE  
> **Operating System:** SR OS (TiMOS)  
> **CLI Prompt:** `A:sr7750#`

---

## Overview

The Nokia 7750 SR is a service edge router / pe running SR OS (TiMOS). 
In the IQ lab environment, devices in this family are deployed across 
multiple sites and monitored for anomalies including jitter, packet loss, 
latency, throughput, link flaps, and BGP instability.

### Health States

| State | Meaning |
|-------|---------|
| Healthy | All metrics within normal thresholds |
| Degraded | One or more metrics exceeding warning thresholds |
| Offline | Device unreachable / no heartbeat |

---

## Troubleshooting by Signal Type

### Jitter Spike

**Jitter Spike — variation in packet inter-arrival times exceeding normal thresholds.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | ms: 25 |
| Critical | ms: 85 |

#### Diagnostic Commands

Run these commands on the Nokia 7750 SR CLI (`A:sr7750#`):

```
A:sr7750# show service sap-using | match jitter
A:sr7750# show router mpls lsp detail | match delay
A:sr7750# show port <port> optical | match power
```

#### Recommended Remediation

Check SAP ingress QoS; verify MPLS LSP delay metrics; apply egress shaping.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 85 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Packet Loss

**Packet Loss — percentage of packets dropped between endpoints.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 0.8 |
| Critical | pct: 4.0 |

#### Diagnostic Commands

Run these commands on the Nokia 7750 SR CLI (`A:sr7750#`):

```
A:sr7750# show port <port> statistics detail | match drop|error
A:sr7750# show router interface detail | match discard
A:sr7750# show port <port> optical | match ber
```

#### Recommended Remediation

Check port error/discard counters; verify optical BER; reseat SFP if power out of range.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 4.0 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Latency Spike

**Latency Spike — round-trip or one-way delay exceeding normal baselines.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | ms: 35 |
| Critical | ms: 160 |

#### Diagnostic Commands

Run these commands on the Nokia 7750 SR CLI (`A:sr7750#`):

```
A:sr7750# oam lsp-ping <lsp-name>
A:sr7750# oam lsp-trace <lsp-name>
A:sr7750# show router mpls lsp <name> path detail | match delay
```

#### Recommended Remediation

Verify RSVP-TE path; check for IGP metric changes; use LSP-ping for path validation.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 160 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Throughput Drop

**Throughput Drop — sustained decrease in data transfer rate below expected capacity.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 20 |
| Critical | pct: 45 |

#### Diagnostic Commands

Run these commands on the Nokia 7750 SR CLI (`A:sr7750#`):

```
A:sr7750# show port <port> statistics detail | match rate
A:sr7750# show qos sap-ingress <id> detail | match drop
A:sr7750# show card <slot> detail | match throughput
```

#### Recommended Remediation

Check card throughput limits; verify SAP QoS scheduling; scale LAG/ECMP.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 45 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Link Flap

**Link Flap — interface toggling between up and down states repeatedly.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | count_1h: 3 |
| Critical | count_1h: 10 |

#### Diagnostic Commands

Run these commands on the Nokia 7750 SR CLI (`A:sr7750#`):

```
A:sr7750# show port <port> | match Oper|Last
A:sr7750# show log event-control | match linkUp|linkDown
A:sr7750# show port <port> optical | match power
```

#### Recommended Remediation

Check optic power; verify connector/fiber path; apply port dampening timer.

#### Escalation Criteria

- Escalate to Tier 2 if count_1h exceeds 10 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Bgp Instability

**BGP Instability — BGP session state changes, route withdrawals, or convergence events.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | flap_count: 2 |
| Critical | flap_count: 5 |

#### Diagnostic Commands

Run these commands on the Nokia 7750 SR CLI (`A:sr7750#`):

```
A:sr7750# show router bgp summary
A:sr7750# show router bgp neighbor <peer> detail | match State|Last
A:sr7750# show log event-control | match bgp
```

#### Recommended Remediation

Check BGP hold/keepalive timers; verify route-policy; restart neighbor if stuck in Active.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 5 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Nokia 7750 SR and require 
human approval via the IQ approval workflow before execution:

| Action | Description | Pre-Check | Post-Check |
|--------|-------------|-----------|------------|
| `restart_bgp_sessions` | Clear and restart BGP sessions on the device | Verify peer state | Confirm sessions re-establish |
| `enable_enhanced_monitoring` | Increase polling interval and enable debug counters | Verify CPU headroom | Confirm counters incrementing |
| `apply_qos_shaping` | Apply or adjust egress QoS shaping profile | Verify current policy | Confirm drop counters stabilize |
| `reseat_optics` | Administratively bounce interface for optic re-init | Verify maintenance window | Confirm optic levels normal |
| `escalate_to_investigate` | Update ticket to Investigate and assign Tier 2 | Verify ticket status | Confirm assignment |

---

## SLA Reference

Response time and escalation targets based on ticket priority and anomaly severity:

| Priority | Severity | Response Time | Escalation Window | Resolution Target |
|----------|----------|---------------|-------------------|-------------------|
| P1 | Critical | 15 min | 30 min | 4 hours |
| P2 | High | 30 min | 1 hour | 8 hours |
| P3 | Medium | 2 hours | 4 hours | 24 hours |
| P4 | Low | 4 hours | 8 hours | 72 hours |

---

*This manual is a simulated reference for the IQ Foundry Agent Lab workshop. 
It provides representative CLI commands and procedures for the Nokia 7750 SR platform. 
In production, refer to official Nokia documentation.*
