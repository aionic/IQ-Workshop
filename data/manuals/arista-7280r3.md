# Arista 7280R3 — IQ Operations Manual

> **Vendor:** Arista  
> **Family:** 7280R3 Series  
> **Role:** Data center spine / border leaf  
> **Operating System:** Arista EOS  
> **CLI Prompt:** `arista#`

---

## Overview

The Arista 7280R3 is a data center spine / border leaf running Arista EOS. 
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
| Warning | ms: 20 |
| Critical | ms: 75 |

#### Diagnostic Commands

Run these commands on the Arista 7280R3 CLI (`arista#`):

```
arista# show ip sla results | include jitter
arista# show qos interface <int> | include jitter
arista# show interfaces <int> counters errors
```

#### Recommended Remediation

Verify DANZ monitoring; check ECMP hashing entropy; apply traffic shaping on egress.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 75 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Packet Loss

**Packet Loss — percentage of packets dropped between endpoints.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 0.5 |
| Critical | pct: 3.0 |

#### Diagnostic Commands

Run these commands on the Arista 7280R3 CLI (`arista#`):

```
arista# show interfaces <int> counters errors
arista# show interfaces <int> hardware counters | include drop
arista# show interfaces <int> transceiver | include power
```

#### Recommended Remediation

Check hardware drop counters (MEMORY/FABRIC); verify optic Rx levels; check buffer utilization.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 3.0 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Latency Spike

**Latency Spike — round-trip or one-way delay exceeding normal baselines.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | ms: 30 |
| Critical | ms: 150 |

#### Diagnostic Commands

Run these commands on the Arista 7280R3 CLI (`arista#`):

```
arista# show ip sla results | include latency
arista# traceroute <dest> source <src>
arista# show ip route <prefix> detail
```

#### Recommended Remediation

Check ECMP path utilization; verify underlay OSPF/IS-IS stability; check for microbursts.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 150 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Throughput Drop

**Throughput Drop — sustained decrease in data transfer rate below expected capacity.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 15 |
| Critical | pct: 40 |

#### Diagnostic Commands

Run these commands on the Arista 7280R3 CLI (`arista#`):

```
arista# show interfaces <int> counters rates
arista# show qos interface <int>
arista# show platform sand counters | include drop
```

#### Recommended Remediation

Check per-chip bandwidth; verify ECMP spray across uplinks; check for traffic polarization.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 40 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Link Flap

**Link Flap — interface toggling between up and down states repeatedly.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | count_1h: 2 |
| Critical | count_1h: 8 |

#### Diagnostic Commands

Run these commands on the Arista 7280R3 CLI (`arista#`):

```
arista# show interfaces <int> | include resets
arista# show logging | include LINEPROTO|LINK
arista# show interfaces <int> transceiver detail
```

#### Recommended Remediation

Check transceiver DOM readings; verify cable integrity; apply error-disable recovery.

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

Run these commands on the Arista 7280R3 CLI (`arista#`):

```
arista# show ip bgp summary | include Active|Idle
arista# show ip bgp neighbors <peer> | include state|reset
arista# show logging | include BGP
```

#### Recommended Remediation

Verify EVPN route-type 5; check BFD timers; validate BGP community filters.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 5 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Arista 7280R3 and require 
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
It provides representative CLI commands and procedures for the Arista 7280R3 platform. 
In production, refer to official Arista documentation.*
