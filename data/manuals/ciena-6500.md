# Ciena 6500 — IQ Operations Manual

> **Vendor:** Ciena  
> **Family:** 6500 Packet-Optical Platform  
> **Role:** Optical transport / WDM edge  
> **Operating System:** SAOS (Ciena)  
> **CLI Prompt:** `ciena6500>`

---

## Overview

The Ciena 6500 is a optical transport / wdm edge running SAOS (Ciena). 
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
| Critical | ms: 70 |

#### Diagnostic Commands

Run these commands on the Ciena 6500 CLI (`ciena6500>`):

```
ciena6500> pm show interface <int> current-15min | include jitter
ciena6500> cfm show mep <id> delay-stats
ciena6500> port show port <port> | include Rx|Tx
```

#### Recommended Remediation

Check optical performance monitoring (PM); verify coherent DSP lock; adjust OADM channel power.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 70 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Packet Loss

**Packet Loss — percentage of packets dropped between endpoints.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 0.5 |
| Critical | pct: 2.0 |

#### Diagnostic Commands

Run these commands on the Ciena 6500 CLI (`ciena6500>`):

```
ciena6500> port show port <port> statistics | include drop|error
ciena6500> pm show interface <int> current-15min | include loss
ciena6500> port show port <port> | include FEC
```

#### Recommended Remediation

Check FEC correction rate; verify optical OSNR; reseat client optic if pre-FEC BER rising.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 2.0 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Latency Spike

**Latency Spike — round-trip or one-way delay exceeding normal baselines.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | ms: 30 |
| Critical | ms: 120 |

#### Diagnostic Commands

Run these commands on the Ciena 6500 CLI (`ciena6500>`):

```
ciena6500> cfm show mep <id> delay-stats | include round-trip
ciena6500> oam twamp-sender show results
ciena6500> pm show interface <int> current-15min | include latency
```

#### Recommended Remediation

Verify CFM loopback delay; check for optical protection switching; review TWAMP baselines.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 120 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Throughput Drop

**Throughput Drop — sustained decrease in data transfer rate below expected capacity.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 15 |
| Critical | pct: 35 |

#### Diagnostic Commands

Run these commands on the Ciena 6500 CLI (`ciena6500>`):

```
ciena6500> port show port <port> statistics | include rate
ciena6500> traffic-profiling show profile <id>
ciena6500> pm show interface <int> current-15min | include throughput
```

#### Recommended Remediation

Check traffic profiling drops; verify wavelength capacity; consider flex-grid reallocation.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 35 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Link Flap

**Link Flap — interface toggling between up and down states repeatedly.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | count_1h: 2 |
| Critical | count_1h: 6 |

#### Diagnostic Commands

Run these commands on the Ciena 6500 CLI (`ciena6500>`):

```
ciena6500> port show port <port> | include status|last-change
ciena6500> log show | include link-state
ciena6500> port show port <port> | include power
```

#### Recommended Remediation

Check optical power budget; verify amplifier gain; check for fiber micro-bends.

#### Escalation Criteria

- Escalate to Tier 2 if count_1h exceeds 6 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Bgp Instability

**BGP Instability — BGP session state changes, route withdrawals, or convergence events.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | flap_count: 1 |
| Critical | flap_count: 3 |

#### Diagnostic Commands

Run these commands on the Ciena 6500 CLI (`ciena6500>`):

```
ciena6500> ip show bgp summary
ciena6500> ip show bgp neighbor <peer> | include state
ciena6500> log show | include BGP
```

#### Recommended Remediation

Verify L3 VPN service; check OAM CFM state; confirm BGP peer not behind flapping optical path.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 3 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Ciena 6500 and require 
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
It provides representative CLI commands and procedures for the Ciena 6500 platform. 
In production, refer to official Ciena documentation.*
