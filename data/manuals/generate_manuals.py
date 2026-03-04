#!/usr/bin/env python3
"""
generate_manuals.py — Generate simulated device manuals for IQ Foundry Agent Lab.

Produces one Markdown manual per device model, covering all 6 anomaly signal types
with model-specific CLI commands, thresholds, and remediation procedures.

These manuals are uploaded to Foundry as knowledge files so the agent can ground
triage recommendations in vendor-specific troubleshooting procedures.

Usage:
    python generate_manuals.py                    # writes to data/manuals/
    python generate_manuals.py --output-dir ./out # writes to ./out/
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Device model metadata — matches DEVICE_MODELS in generate_seed.py
# ---------------------------------------------------------------------------

MODELS: dict[str, dict] = {
    "Cisco ASR-9000": {
        "slug": "cisco-asr-9000",
        "vendor": "Cisco",
        "family": "ASR-9000 Series",
        "role": "Core / edge aggregation router",
        "os": "IOS-XR",
        "cli_prefix": "RP/0/RSP0/CPU0:",
        "signal_commands": {
            "jitter_spike": [
                "show performance-measurement interface detail",
                "show policy-map interface <int> input | include jitter",
                "show controllers optics <int> | include OFP",
            ],
            "packet_loss": [
                "show interface <int> | include drops|errors|CRC",
                "show policy-map interface <int> | include drop",
                "show controllers optics <int> | include FEC",
            ],
            "latency_spike": [
                "show performance-measurement delay detail",
                "show route <prefix> detail | include delay",
                "traceroute sr-mpls <prefix> fec-type igp",
            ],
            "throughput_drop": [
                "show interface <int> | include rate",
                "show policy-map interface <int> output",
                "show controllers fabric plane all",
            ],
            "link_flap": [
                "show interface <int> | include resets|flap",
                "show logging | include UPDOWN",
                "show controllers optics <int> | include power",
            ],
            "bgp_instability": [
                "show bgp summary | include Active|Idle",
                "show bgp neighbors <peer> | include state|reset",
                "show bgp process | include restart",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 30, "critical_ms": 100},
            "packet_loss": {"warning_pct": 1.0, "critical_pct": 5.0},
            "latency_spike": {"warning_ms": 50, "critical_ms": 200},
            "throughput_drop": {"warning_pct": 20, "critical_pct": 50},
            "link_flap": {"warning_count_1h": 3, "critical_count_1h": 10},
            "bgp_instability": {"warning_flap_count": 2, "critical_flap_count": 5},
        },
        "remediations": {
            "jitter_spike": "Apply QoS shaping on egress; check optic levels; escalate if jitter > 100ms.",
            "packet_loss": "Check FEC counters; reseat optics; if CRC errors persist, replace transceiver.",
            "latency_spike": "Verify SR policy path; check for congested ECMP members; reroute via TE tunnel.",
            "throughput_drop": "Check fabric plane health; verify no policing drops; scale interface bundle.",
            "link_flap": "Check optic power levels; verify cabling; dampening may be needed if flaps > 10/hr.",
            "bgp_instability": "Check BGP hold timers; verify route-policy changes; restart BGP session if peer stuck in Active.",
        },
    },
    "Cisco Catalyst 9300": {
        "slug": "cisco-catalyst-9300",
        "vendor": "Cisco",
        "family": "Catalyst 9300 Series",
        "role": "Campus / access layer switch",
        "os": "IOS-XE",
        "cli_prefix": "Switch#",
        "signal_commands": {
            "jitter_spike": [
                "show ip sla statistics | include Jitter",
                "show platform software fed switch active qos interface <int>",
                "show interfaces <int> counters errors",
            ],
            "packet_loss": [
                "show interfaces <int> | include drops|errors|CRC",
                "show platform software fed switch active drop",
                "show interfaces <int> counters errors",
            ],
            "latency_spike": [
                "show ip sla statistics | include Latency",
                "traceroute <dest> source <src>",
                "show ip route <prefix> detail",
            ],
            "throughput_drop": [
                "show interfaces <int> | include rate",
                "show platform software fed switch active ifm mappings",
                "show stackwise-virtual bandwidth",
            ],
            "link_flap": [
                "show interfaces <int> | include resets|changes",
                "show logging | include UPDOWN",
                "show power inline <int>",
            ],
            "bgp_instability": [
                "show ip bgp summary | include Active|Idle",
                "show ip bgp neighbors <peer> | include state|reset",
                "show logging | include BGP",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 20, "critical_ms": 80},
            "packet_loss": {"warning_pct": 0.5, "critical_pct": 3.0},
            "latency_spike": {"warning_ms": 30, "critical_ms": 150},
            "throughput_drop": {"warning_pct": 15, "critical_pct": 40},
            "link_flap": {"warning_count_1h": 2, "critical_count_1h": 8},
            "bgp_instability": {"warning_flap_count": 2, "critical_flap_count": 4},
        },
        "remediations": {
            "jitter_spike": "Check PoE budget; verify QoS trust boundary on access ports; check uplink utilization.",
            "packet_loss": "Check CRC/input errors; replace patch cable; check PoE power draw on affected port.",
            "latency_spike": "Check uplink saturation; verify SVI routing; check for spanning-tree reconvergence.",
            "throughput_drop": "Verify stack bandwidth; check for microbursts on uplinks; enable jumbo frames if needed.",
            "link_flap": "Check cable/SFP seating; verify PoE negotiation; apply spanning-tree portfast if access port.",
            "bgp_instability": "Verify BGP keepalive timers; check route-map filters; confirm no CPU spikes during convergence.",
        },
    },
    "Juniper MX960": {
        "slug": "juniper-mx960",
        "vendor": "Juniper",
        "family": "MX960 Series",
        "role": "Core / edge aggregation router",
        "os": "Junos OS",
        "cli_prefix": "user@mx960>",
        "signal_commands": {
            "jitter_spike": [
                "show services rpm probe-results",
                "show class-of-service interface <int> | match jitter",
                "show interfaces <int> detail | match errors",
            ],
            "packet_loss": [
                "show interfaces <int> extensive | match errors|drops",
                "show pfe statistics traffic | match drop",
                "show interfaces diagnostics optics <int>",
            ],
            "latency_spike": [
                "show services rpm probe-results | match round-trip",
                "traceroute <dest> source <src> resolve",
                "show route <prefix> extensive | match metric",
            ],
            "throughput_drop": [
                "show interfaces <int> | match rate",
                "show class-of-service interface <int> | match queued|dropped",
                "show chassis fabric summary",
            ],
            "link_flap": [
                "show interfaces <int> | match flaps|Last",
                "show log messages | match SNMP_TRAP_LINK",
                "show interfaces diagnostics optics <int> | match power",
            ],
            "bgp_instability": [
                "show bgp summary | match Estab|Active|Idle",
                "show bgp neighbor <peer> | match State|Last",
                "show log messages | match BGP_CONNECT|rpd",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 25, "critical_ms": 90},
            "packet_loss": {"warning_pct": 0.8, "critical_pct": 4.0},
            "latency_spike": {"warning_ms": 40, "critical_ms": 180},
            "throughput_drop": {"warning_pct": 20, "critical_pct": 45},
            "link_flap": {"warning_count_1h": 3, "critical_count_1h": 8},
            "bgp_instability": {"warning_flap_count": 2, "critical_flap_count": 5},
        },
        "remediations": {
            "jitter_spike": "Apply hierarchical policer; verify optic Rx/Tx power; check CoS scheduler.",
            "packet_loss": "Check PFE drop counters; verify interface MTU; reseat optics if CRC errors present.",
            "latency_spike": "Verify ECMP load-balancing; check for IS-IS/OSPF metric changes; traceroute analysis.",
            "throughput_drop": "Check fabric utilization; verify CoS scheduling; scale LAG membership if needed.",
            "link_flap": "Check optic power levels; verify auto-negotiation; apply interface dampening.",
            "bgp_instability": "Verify hold-time and keepalive; check import/export policy; clear bgp neighbor if stuck.",
        },
    },
    "Juniper QFX5120": {
        "slug": "juniper-qfx5120",
        "vendor": "Juniper",
        "family": "QFX5120 Series",
        "role": "Data center leaf / spine switch",
        "os": "Junos OS",
        "cli_prefix": "user@qfx5120>",
        "signal_commands": {
            "jitter_spike": [
                "show services rpm probe-results",
                "show class-of-service interface <int>",
                "show interfaces <int> detail | match errors",
            ],
            "packet_loss": [
                "show interfaces <int> extensive | match errors|drops",
                "show pfe statistics traffic",
                "show interfaces diagnostics optics <int>",
            ],
            "latency_spike": [
                "show services rpm probe-results | match round-trip",
                "traceroute <dest> source <src>",
                "show route <prefix> extensive",
            ],
            "throughput_drop": [
                "show interfaces <int> | match rate",
                "show class-of-service interface <int>",
                "show virtual-chassis status",
            ],
            "link_flap": [
                "show interfaces <int> | match flaps",
                "show log messages | match SNMP_TRAP_LINK",
                "show interfaces diagnostics optics <int>",
            ],
            "bgp_instability": [
                "show bgp summary",
                "show bgp neighbor <peer> | match State",
                "show log messages | match rpd|BGP",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 15, "critical_ms": 60},
            "packet_loss": {"warning_pct": 0.5, "critical_pct": 2.5},
            "latency_spike": {"warning_ms": 20, "critical_ms": 100},
            "throughput_drop": {"warning_pct": 15, "critical_pct": 40},
            "link_flap": {"warning_count_1h": 2, "critical_count_1h": 6},
            "bgp_instability": {"warning_flap_count": 2, "critical_flap_count": 4},
        },
        "remediations": {
            "jitter_spike": "Check leaf-spine fabric load; verify CoS priority queues; check ECMP hashing.",
            "packet_loss": "Verify buffer allocation; check for microburst drops; reseat DAC/optics.",
            "latency_spike": "Check ECMP path symmetry; verify underlay IGP metric; check spine congestion.",
            "throughput_drop": "Check virtual-chassis bandwidth; verify no port over-subscription; scale uplinks.",
            "link_flap": "Check DAC/optic seating; verify no auto-negotiation mismatches; apply dampening.",
            "bgp_instability": "Verify EVPN-VXLAN underlay; check BGP timers; validate route-policy.",
        },
    },
    "Arista 7280R3": {
        "slug": "arista-7280r3",
        "vendor": "Arista",
        "family": "7280R3 Series",
        "role": "Data center spine / border leaf",
        "os": "Arista EOS",
        "cli_prefix": "arista#",
        "signal_commands": {
            "jitter_spike": [
                "show ip sla results | include jitter",
                "show qos interface <int> | include jitter",
                "show interfaces <int> counters errors",
            ],
            "packet_loss": [
                "show interfaces <int> counters errors",
                "show interfaces <int> hardware counters | include drop",
                "show interfaces <int> transceiver | include power",
            ],
            "latency_spike": [
                "show ip sla results | include latency",
                "traceroute <dest> source <src>",
                "show ip route <prefix> detail",
            ],
            "throughput_drop": [
                "show interfaces <int> counters rates",
                "show qos interface <int>",
                "show platform sand counters | include drop",
            ],
            "link_flap": [
                "show interfaces <int> | include resets",
                "show logging | include LINEPROTO|LINK",
                "show interfaces <int> transceiver detail",
            ],
            "bgp_instability": [
                "show ip bgp summary | include Active|Idle",
                "show ip bgp neighbors <peer> | include state|reset",
                "show logging | include BGP",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 20, "critical_ms": 75},
            "packet_loss": {"warning_pct": 0.5, "critical_pct": 3.0},
            "latency_spike": {"warning_ms": 30, "critical_ms": 150},
            "throughput_drop": {"warning_pct": 15, "critical_pct": 40},
            "link_flap": {"warning_count_1h": 2, "critical_count_1h": 8},
            "bgp_instability": {"warning_flap_count": 2, "critical_flap_count": 5},
        },
        "remediations": {
            "jitter_spike": "Verify DANZ monitoring; check ECMP hashing entropy; apply traffic shaping on egress.",
            "packet_loss": "Check hardware drop counters (MEMORY/FABRIC); verify optic Rx levels; check buffer utilization.",
            "latency_spike": "Check ECMP path utilization; verify underlay OSPF/IS-IS stability; check for microbursts.",
            "throughput_drop": "Check per-chip bandwidth; verify ECMP spray across uplinks; check for traffic polarization.",
            "link_flap": "Check transceiver DOM readings; verify cable integrity; apply error-disable recovery.",
            "bgp_instability": "Verify EVPN route-type 5; check BFD timers; validate BGP community filters.",
        },
    },
    "Nokia 7750 SR": {
        "slug": "nokia-7750-sr",
        "vendor": "Nokia",
        "family": "7750 SR Series",
        "role": "Service edge router / PE",
        "os": "SR OS (TiMOS)",
        "cli_prefix": "A:sr7750#",
        "signal_commands": {
            "jitter_spike": [
                "show service sap-using | match jitter",
                "show router mpls lsp detail | match delay",
                "show port <port> optical | match power",
            ],
            "packet_loss": [
                "show port <port> statistics detail | match drop|error",
                "show router interface detail | match discard",
                "show port <port> optical | match ber",
            ],
            "latency_spike": [
                "oam lsp-ping <lsp-name>",
                "oam lsp-trace <lsp-name>",
                "show router mpls lsp <name> path detail | match delay",
            ],
            "throughput_drop": [
                "show port <port> statistics detail | match rate",
                "show qos sap-ingress <id> detail | match drop",
                "show card <slot> detail | match throughput",
            ],
            "link_flap": [
                "show port <port> | match Oper|Last",
                "show log event-control | match linkUp|linkDown",
                "show port <port> optical | match power",
            ],
            "bgp_instability": [
                "show router bgp summary",
                "show router bgp neighbor <peer> detail | match State|Last",
                "show log event-control | match bgp",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 25, "critical_ms": 85},
            "packet_loss": {"warning_pct": 0.8, "critical_pct": 4.0},
            "latency_spike": {"warning_ms": 35, "critical_ms": 160},
            "throughput_drop": {"warning_pct": 20, "critical_pct": 45},
            "link_flap": {"warning_count_1h": 3, "critical_count_1h": 10},
            "bgp_instability": {"warning_flap_count": 2, "critical_flap_count": 5},
        },
        "remediations": {
            "jitter_spike": "Check SAP ingress QoS; verify MPLS LSP delay metrics; apply egress shaping.",
            "packet_loss": "Check port error/discard counters; verify optical BER; reseat SFP if power out of range.",
            "latency_spike": "Verify RSVP-TE path; check for IGP metric changes; use LSP-ping for path validation.",
            "throughput_drop": "Check card throughput limits; verify SAP QoS scheduling; scale LAG/ECMP.",
            "link_flap": "Check optic power; verify connector/fiber path; apply port dampening timer.",
            "bgp_instability": "Check BGP hold/keepalive timers; verify route-policy; restart neighbor if stuck in Active.",
        },
    },
    "Ciena 6500": {
        "slug": "ciena-6500",
        "vendor": "Ciena",
        "family": "6500 Packet-Optical Platform",
        "role": "Optical transport / WDM edge",
        "os": "SAOS (Ciena)",
        "cli_prefix": "ciena6500>",
        "signal_commands": {
            "jitter_spike": [
                "pm show interface <int> current-15min | include jitter",
                "cfm show mep <id> delay-stats",
                "port show port <port> | include Rx|Tx",
            ],
            "packet_loss": [
                "port show port <port> statistics | include drop|error",
                "pm show interface <int> current-15min | include loss",
                "port show port <port> | include FEC",
            ],
            "latency_spike": [
                "cfm show mep <id> delay-stats | include round-trip",
                "oam twamp-sender show results",
                "pm show interface <int> current-15min | include latency",
            ],
            "throughput_drop": [
                "port show port <port> statistics | include rate",
                "traffic-profiling show profile <id>",
                "pm show interface <int> current-15min | include throughput",
            ],
            "link_flap": [
                "port show port <port> | include status|last-change",
                "log show | include link-state",
                "port show port <port> | include power",
            ],
            "bgp_instability": [
                "ip show bgp summary",
                "ip show bgp neighbor <peer> | include state",
                "log show | include BGP",
            ],
        },
        "thresholds": {
            "jitter_spike": {"warning_ms": 20, "critical_ms": 70},
            "packet_loss": {"warning_pct": 0.5, "critical_pct": 2.0},
            "latency_spike": {"warning_ms": 30, "critical_ms": 120},
            "throughput_drop": {"warning_pct": 15, "critical_pct": 35},
            "link_flap": {"warning_count_1h": 2, "critical_count_1h": 6},
            "bgp_instability": {"warning_flap_count": 1, "critical_flap_count": 3},
        },
        "remediations": {
            "jitter_spike": "Check optical performance monitoring (PM); verify coherent DSP lock; adjust OADM channel power.",
            "packet_loss": "Check FEC correction rate; verify optical OSNR; reseat client optic if pre-FEC BER rising.",
            "latency_spike": "Verify CFM loopback delay; check for optical protection switching; review TWAMP baselines.",
            "throughput_drop": "Check traffic profiling drops; verify wavelength capacity; consider flex-grid reallocation.",
            "link_flap": "Check optical power budget; verify amplifier gain; check for fiber micro-bends.",
            "bgp_instability": "Verify L3 VPN service; check OAM CFM state; confirm BGP peer not behind flapping optical path.",
        },
    },
}

SIGNAL_DESCRIPTIONS = {
    "jitter_spike": "Jitter Spike — variation in packet inter-arrival times exceeding normal thresholds.",
    "packet_loss": "Packet Loss — percentage of packets dropped between endpoints.",
    "latency_spike": "Latency Spike — round-trip or one-way delay exceeding normal baselines.",
    "throughput_drop": "Throughput Drop — sustained decrease in data transfer rate below expected capacity.",
    "link_flap": "Link Flap — interface toggling between up and down states repeatedly.",
    "bgp_instability": "BGP Instability — BGP session state changes, route withdrawals, or convergence events.",
}

SLA_TABLE = """
| Priority | Severity | Response Time | Escalation Window | Resolution Target |
|----------|----------|---------------|-------------------|-------------------|
| P1 | Critical | 15 min | 30 min | 4 hours |
| P2 | High | 30 min | 1 hour | 8 hours |
| P3 | Medium | 2 hours | 4 hours | 24 hours |
| P4 | Low | 4 hours | 8 hours | 72 hours |
"""


def generate_manual(model_name: str, model: dict) -> str:
    """Generate a Markdown manual for a single device model."""
    lines: list[str] = []

    # Header
    lines.append(f"# {model_name} — IQ Operations Manual")
    lines.append("")
    lines.append(f"> **Vendor:** {model['vendor']}  ")
    lines.append(f"> **Family:** {model['family']}  ")
    lines.append(f"> **Role:** {model['role']}  ")
    lines.append(f"> **Operating System:** {model['os']}  ")
    lines.append(f"> **CLI Prompt:** `{model['cli_prefix']}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    lines.append(f"The {model_name} is a {model['role'].lower()} running {model['os']}. ")
    lines.append(f"In the IQ lab environment, devices in this family are deployed across ")
    lines.append(f"multiple sites and monitored for anomalies including jitter, packet loss, ")
    lines.append(f"latency, throughput, link flaps, and BGP instability.")
    lines.append("")
    lines.append("### Health States")
    lines.append("")
    lines.append("| State | Meaning |")
    lines.append("|-------|---------|")
    lines.append("| Healthy | All metrics within normal thresholds |")
    lines.append("| Degraded | One or more metrics exceeding warning thresholds |")
    lines.append("| Offline | Device unreachable / no heartbeat |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Signal-type troubleshooting sections
    lines.append("## Troubleshooting by Signal Type")
    lines.append("")

    for signal_type, description in SIGNAL_DESCRIPTIONS.items():
        commands = model["signal_commands"][signal_type]
        thresholds = model["thresholds"][signal_type]
        remediation = model["remediations"][signal_type]

        lines.append(f"### {signal_type.replace('_', ' ').title()}")
        lines.append("")
        lines.append(f"**{description}**")
        lines.append("")

        # Thresholds
        lines.append("#### Thresholds")
        lines.append("")
        lines.append("| Level | Threshold |")
        lines.append("|-------|-----------|")
        for key, value in thresholds.items():
            level = key.split("_")[0].title()
            metric = "_".join(key.split("_")[1:])
            lines.append(f"| {level} | {metric}: {value} |")
        lines.append("")

        # Diagnostic commands
        lines.append("#### Diagnostic Commands")
        lines.append("")
        lines.append(f"Run these commands on the {model_name} CLI (`{model['cli_prefix']}`):")
        lines.append("")
        lines.append("```")
        for cmd in commands:
            lines.append(f"{model['cli_prefix']} {cmd}")
        lines.append("```")
        lines.append("")

        # Remediation
        lines.append("#### Recommended Remediation")
        lines.append("")
        lines.append(remediation)
        lines.append("")

        # Escalation
        lines.append("#### Escalation Criteria")
        lines.append("")
        critical_keys = [k for k in thresholds if k.startswith("critical")]
        if critical_keys:
            crit_val = thresholds[critical_keys[0]]
            crit_metric = "_".join(critical_keys[0].split("_")[1:])
            lines.append(f"- Escalate to Tier 2 if {crit_metric} exceeds {crit_val} for > 15 minutes")
        lines.append(f"- Escalate immediately if the device transitions to **Offline** state")
        lines.append(f"- Escalate if remediation does not resolve within the SLA resolution target")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Common remediations
    lines.append("## Allowlisted Remediation Actions")
    lines.append("")
    lines.append(f"The following actions are pre-approved for the {model_name} and require ")
    lines.append(f"human approval via the IQ approval workflow before execution:")
    lines.append("")
    lines.append("| Action | Description | Pre-Check | Post-Check |")
    lines.append("|--------|-------------|-----------|------------|")
    lines.append(f"| `restart_bgp_sessions` | Clear and restart BGP sessions on the device | Verify peer state | Confirm sessions re-establish |")
    lines.append(f"| `enable_enhanced_monitoring` | Increase polling interval and enable debug counters | Verify CPU headroom | Confirm counters incrementing |")
    lines.append(f"| `apply_qos_shaping` | Apply or adjust egress QoS shaping profile | Verify current policy | Confirm drop counters stabilize |")
    lines.append(f"| `reseat_optics` | Administratively bounce interface for optic re-init | Verify maintenance window | Confirm optic levels normal |")
    lines.append(f"| `escalate_to_investigate` | Update ticket to Investigate and assign Tier 2 | Verify ticket status | Confirm assignment |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # SLA reference
    lines.append("## SLA Reference")
    lines.append("")
    lines.append("Response time and escalation targets based on ticket priority and anomaly severity:")
    lines.append("")
    lines.append(SLA_TABLE.strip())
    lines.append("")
    lines.append("---")
    lines.append("")

    # Footer
    lines.append(f"*This manual is a simulated reference for the IQ Foundry Agent Lab workshop. ")
    lines.append(f"It provides representative CLI commands and procedures for the {model_name} platform. ")
    lines.append(f"In production, refer to official {model['vendor']} documentation.*")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate IQ device manuals")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "",
        help="Output directory for manual files (default: data/manuals/)",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for model_name, model_data in MODELS.items():
        filename = f"{model_data['slug']}.md"
        filepath = output_dir / filename
        content = generate_manual(model_name, model_data)
        filepath.write_text(content, encoding="utf-8")
        print(f"  {filepath}")

    print(f"\nGenerated {len(MODELS)} device manuals in {output_dir}")


if __name__ == "__main__":
    main()
