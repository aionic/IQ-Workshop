# Cisco Catalyst 9300 — IQ Operations Manual

> **Vendor:** Cisco  
> **Family:** Catalyst 9300 Series  
> **Role:** Campus / access layer switch  
> **Operating System:** IOS-XE  
> **CLI Prompt:** `Switch#`

---

## Overview

The Cisco Catalyst 9300 is a campus / access layer switch running IOS-XE. 
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
| Critical | ms: 80 |

#### Diagnostic Commands

Run these commands on the Cisco Catalyst 9300 CLI (`Switch#`):

```
Switch# show ip sla statistics | include Jitter
Switch# show platform software fed switch active qos interface <int>
Switch# show interfaces <int> counters errors
```

#### Recommended Remediation

Check PoE budget; verify QoS trust boundary on access ports; check uplink utilization.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 80 for > 15 minutes
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

Run these commands on the Cisco Catalyst 9300 CLI (`Switch#`):

```
Switch# show interfaces <int> | include drops|errors|CRC
Switch# show platform software fed switch active drop
Switch# show interfaces <int> counters errors
```

#### Recommended Remediation

Check CRC/input errors; replace patch cable; check PoE power draw on affected port.

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

Run these commands on the Cisco Catalyst 9300 CLI (`Switch#`):

```
Switch# show ip sla statistics | include Latency
Switch# traceroute <dest> source <src>
Switch# show ip route <prefix> detail
```

#### Recommended Remediation

Check uplink saturation; verify SVI routing; check for spanning-tree reconvergence.

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

Run these commands on the Cisco Catalyst 9300 CLI (`Switch#`):

```
Switch# show interfaces <int> | include rate
Switch# show platform software fed switch active ifm mappings
Switch# show stackwise-virtual bandwidth
```

#### Recommended Remediation

Verify stack bandwidth; check for microbursts on uplinks; enable jumbo frames if needed.

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

Run these commands on the Cisco Catalyst 9300 CLI (`Switch#`):

```
Switch# show interfaces <int> | include resets|changes
Switch# show logging | include UPDOWN
Switch# show power inline <int>
```

#### Recommended Remediation

Check cable/SFP seating; verify PoE negotiation; apply spanning-tree portfast if access port.

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
| Critical | flap_count: 4 |

#### Diagnostic Commands

Run these commands on the Cisco Catalyst 9300 CLI (`Switch#`):

```
Switch# show ip bgp summary | include Active|Idle
Switch# show ip bgp neighbors <peer> | include state|reset
Switch# show logging | include BGP
```

#### Recommended Remediation

Verify BGP keepalive timers; check route-map filters; confirm no CPU spikes during convergence.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 4 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Cisco Catalyst 9300 and require 
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
It provides representative CLI commands and procedures for the Cisco Catalyst 9300 platform. 
In production, refer to official Cisco documentation.*
