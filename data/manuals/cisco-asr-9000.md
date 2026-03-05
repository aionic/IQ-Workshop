# Cisco ASR-9000 — IQ Operations Manual

> **Vendor:** Cisco  
> **Family:** ASR-9000 Series  
> **Role:** Core / edge aggregation router  
> **Operating System:** IOS-XR  
> **CLI Prompt:** `RP/0/RSP0/CPU0:`

---

## Overview

The Cisco ASR-9000 is a core / edge aggregation router running IOS-XR. 
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
| Warning | ms: 30 |
| Critical | ms: 100 |

#### Diagnostic Commands

Run these commands on the Cisco ASR-9000 CLI (`RP/0/RSP0/CPU0:`):

```
RP/0/RSP0/CPU0: show performance-measurement interface detail
RP/0/RSP0/CPU0: show policy-map interface <int> input | include jitter
RP/0/RSP0/CPU0: show controllers optics <int> | include OFP
```

#### Recommended Remediation

Apply QoS shaping on egress; check optic levels; escalate if jitter > 100ms.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 100 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Packet Loss

**Packet Loss — percentage of packets dropped between endpoints.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 1.0 |
| Critical | pct: 5.0 |

#### Diagnostic Commands

Run these commands on the Cisco ASR-9000 CLI (`RP/0/RSP0/CPU0:`):

```
RP/0/RSP0/CPU0: show interface <int> | include drops|errors|CRC
RP/0/RSP0/CPU0: show policy-map interface <int> | include drop
RP/0/RSP0/CPU0: show controllers optics <int> | include FEC
```

#### Recommended Remediation

Check FEC counters; reseat optics; if CRC errors persist, replace transceiver.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 5.0 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Latency Spike

**Latency Spike — round-trip or one-way delay exceeding normal baselines.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | ms: 50 |
| Critical | ms: 200 |

#### Diagnostic Commands

Run these commands on the Cisco ASR-9000 CLI (`RP/0/RSP0/CPU0:`):

```
RP/0/RSP0/CPU0: show performance-measurement delay detail
RP/0/RSP0/CPU0: show route <prefix> detail | include delay
RP/0/RSP0/CPU0: traceroute sr-mpls <prefix> fec-type igp
```

#### Recommended Remediation

Verify SR policy path; check for congested ECMP members; reroute via TE tunnel.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 200 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Throughput Drop

**Throughput Drop — sustained decrease in data transfer rate below expected capacity.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 20 |
| Critical | pct: 50 |

#### Diagnostic Commands

Run these commands on the Cisco ASR-9000 CLI (`RP/0/RSP0/CPU0:`):

```
RP/0/RSP0/CPU0: show interface <int> | include rate
RP/0/RSP0/CPU0: show policy-map interface <int> output
RP/0/RSP0/CPU0: show controllers fabric plane all
```

#### Recommended Remediation

Check fabric plane health; verify no policing drops; scale interface bundle.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 50 for > 15 minutes
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

Run these commands on the Cisco ASR-9000 CLI (`RP/0/RSP0/CPU0:`):

```
RP/0/RSP0/CPU0: show interface <int> | include resets|flap
RP/0/RSP0/CPU0: show logging | include UPDOWN
RP/0/RSP0/CPU0: show controllers optics <int> | include power
```

#### Recommended Remediation

Check optic power levels; verify cabling; dampening may be needed if flaps > 10/hr.

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

Run these commands on the Cisco ASR-9000 CLI (`RP/0/RSP0/CPU0:`):

```
RP/0/RSP0/CPU0: show bgp summary | include Active|Idle
RP/0/RSP0/CPU0: show bgp neighbors <peer> | include state|reset
RP/0/RSP0/CPU0: show bgp process | include restart
```

#### Recommended Remediation

Check BGP hold timers; verify route-policy changes; restart BGP session if peer stuck in Active.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 5 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Cisco ASR-9000 and require 
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
It provides representative CLI commands and procedures for the Cisco ASR-9000 platform. 
In production, refer to official Cisco documentation.*
