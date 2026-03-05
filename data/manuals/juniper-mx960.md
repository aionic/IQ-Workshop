# Juniper MX960 — IQ Operations Manual

> **Vendor:** Juniper  
> **Family:** MX960 Series  
> **Role:** Core / edge aggregation router  
> **Operating System:** Junos OS  
> **CLI Prompt:** `user@mx960>`

---

## Overview

The Juniper MX960 is a core / edge aggregation router running Junos OS. 
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
| Critical | ms: 90 |

#### Diagnostic Commands

Run these commands on the Juniper MX960 CLI (`user@mx960>`):

```
user@mx960> show services rpm probe-results
user@mx960> show class-of-service interface <int> | match jitter
user@mx960> show interfaces <int> detail | match errors
```

#### Recommended Remediation

Apply hierarchical policer; verify optic Rx/Tx power; check CoS scheduler.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 90 for > 15 minutes
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

Run these commands on the Juniper MX960 CLI (`user@mx960>`):

```
user@mx960> show interfaces <int> extensive | match errors|drops
user@mx960> show pfe statistics traffic | match drop
user@mx960> show interfaces diagnostics optics <int>
```

#### Recommended Remediation

Check PFE drop counters; verify interface MTU; reseat optics if CRC errors present.

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
| Warning | ms: 40 |
| Critical | ms: 180 |

#### Diagnostic Commands

Run these commands on the Juniper MX960 CLI (`user@mx960>`):

```
user@mx960> show services rpm probe-results | match round-trip
user@mx960> traceroute <dest> source <src> resolve
user@mx960> show route <prefix> extensive | match metric
```

#### Recommended Remediation

Verify ECMP load-balancing; check for IS-IS/OSPF metric changes; traceroute analysis.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 180 for > 15 minutes
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

Run these commands on the Juniper MX960 CLI (`user@mx960>`):

```
user@mx960> show interfaces <int> | match rate
user@mx960> show class-of-service interface <int> | match queued|dropped
user@mx960> show chassis fabric summary
```

#### Recommended Remediation

Check fabric utilization; verify CoS scheduling; scale LAG membership if needed.

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
| Critical | count_1h: 8 |

#### Diagnostic Commands

Run these commands on the Juniper MX960 CLI (`user@mx960>`):

```
user@mx960> show interfaces <int> | match flaps|Last
user@mx960> show log messages | match SNMP_TRAP_LINK
user@mx960> show interfaces diagnostics optics <int> | match power
```

#### Recommended Remediation

Check optic power levels; verify auto-negotiation; apply interface dampening.

#### Escalation Criteria

- Escalate to Tier 2 if count_1h exceeds 8 for > 15 minutes
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

Run these commands on the Juniper MX960 CLI (`user@mx960>`):

```
user@mx960> show bgp summary | match Estab|Active|Idle
user@mx960> show bgp neighbor <peer> | match State|Last
user@mx960> show log messages | match BGP_CONNECT|rpd
```

#### Recommended Remediation

Verify hold-time and keepalive; check import/export policy; clear bgp neighbor if stuck.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 5 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Juniper MX960 and require 
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
It provides representative CLI commands and procedures for the Juniper MX960 platform. 
In production, refer to official Juniper documentation.*
