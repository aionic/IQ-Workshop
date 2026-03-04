# Juniper QFX5120 — IQ Operations Manual

> **Vendor:** Juniper  
> **Family:** QFX5120 Series  
> **Role:** Data center leaf / spine switch  
> **Operating System:** Junos OS  
> **CLI Prompt:** `user@qfx5120>`

---

## Overview

The Juniper QFX5120 is a data center leaf / spine switch running Junos OS. 
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
| Warning | ms: 15 |
| Critical | ms: 60 |

#### Diagnostic Commands

Run these commands on the Juniper QFX5120 CLI (`user@qfx5120>`):

```
user@qfx5120> show services rpm probe-results
user@qfx5120> show class-of-service interface <int>
user@qfx5120> show interfaces <int> detail | match errors
```

#### Recommended Remediation

Check leaf-spine fabric load; verify CoS priority queues; check ECMP hashing.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 60 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Packet Loss

**Packet Loss — percentage of packets dropped between endpoints.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | pct: 0.5 |
| Critical | pct: 2.5 |

#### Diagnostic Commands

Run these commands on the Juniper QFX5120 CLI (`user@qfx5120>`):

```
user@qfx5120> show interfaces <int> extensive | match errors|drops
user@qfx5120> show pfe statistics traffic
user@qfx5120> show interfaces diagnostics optics <int>
```

#### Recommended Remediation

Verify buffer allocation; check for microburst drops; reseat DAC/optics.

#### Escalation Criteria

- Escalate to Tier 2 if pct exceeds 2.5 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

### Latency Spike

**Latency Spike — round-trip or one-way delay exceeding normal baselines.**

#### Thresholds

| Level | Threshold |
|-------|-----------|
| Warning | ms: 20 |
| Critical | ms: 100 |

#### Diagnostic Commands

Run these commands on the Juniper QFX5120 CLI (`user@qfx5120>`):

```
user@qfx5120> show services rpm probe-results | match round-trip
user@qfx5120> traceroute <dest> source <src>
user@qfx5120> show route <prefix> extensive
```

#### Recommended Remediation

Check ECMP path symmetry; verify underlay IGP metric; check spine congestion.

#### Escalation Criteria

- Escalate to Tier 2 if ms exceeds 100 for > 15 minutes
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

Run these commands on the Juniper QFX5120 CLI (`user@qfx5120>`):

```
user@qfx5120> show interfaces <int> | match rate
user@qfx5120> show class-of-service interface <int>
user@qfx5120> show virtual-chassis status
```

#### Recommended Remediation

Check virtual-chassis bandwidth; verify no port over-subscription; scale uplinks.

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
| Critical | count_1h: 6 |

#### Diagnostic Commands

Run these commands on the Juniper QFX5120 CLI (`user@qfx5120>`):

```
user@qfx5120> show interfaces <int> | match flaps
user@qfx5120> show log messages | match SNMP_TRAP_LINK
user@qfx5120> show interfaces diagnostics optics <int>
```

#### Recommended Remediation

Check DAC/optic seating; verify no auto-negotiation mismatches; apply dampening.

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
| Warning | flap_count: 2 |
| Critical | flap_count: 4 |

#### Diagnostic Commands

Run these commands on the Juniper QFX5120 CLI (`user@qfx5120>`):

```
user@qfx5120> show bgp summary
user@qfx5120> show bgp neighbor <peer> | match State
user@qfx5120> show log messages | match rpd|BGP
```

#### Recommended Remediation

Verify EVPN-VXLAN underlay; check BGP timers; validate route-policy.

#### Escalation Criteria

- Escalate to Tier 2 if flap_count exceeds 4 for > 15 minutes
- Escalate immediately if the device transitions to **Offline** state
- Escalate if remediation does not resolve within the SLA resolution target

---

## Allowlisted Remediation Actions

The following actions are pre-approved for the Juniper QFX5120 and require 
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
It provides representative CLI commands and procedures for the Juniper QFX5120 platform. 
In production, refer to official Juniper documentation.*
