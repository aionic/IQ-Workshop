#!/usr/bin/env python3
"""
generate_seed.py — Programmatic seed data generator for IQ Foundry Agent Lab.

Generates seed.sql with configurable counts for devices, anomalies, and tickets.
Output is written to stdout (redirect to file as needed).

Usage:
    python generate_seed.py --devices 30 --anomalies 80 --tickets 50
    python generate_seed.py --devices 30 --anomalies 80 --tickets 50 > ../seed.sql
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone

# --- Configuration ---

DEVICE_MODELS = [
    "Cisco ASR-9000",
    "Cisco Catalyst 9300",
    "Juniper MX960",
    "Juniper QFX5120",
    "Arista 7280R3",
    "Nokia 7750 SR",
    "Ciena 6500",
]

HEALTH_STATES = ["Healthy", "Degraded", "Offline"]
HEALTH_WEIGHTS = [0.6, 0.3, 0.1]

SEVERITIES = ["Critical", "High", "Medium", "Low"]
SEVERITY_WEIGHTS = [0.1, 0.25, 0.35, 0.3]

SIGNAL_TYPES = [
    "jitter_spike",
    "packet_loss",
    "latency_spike",
    "throughput_drop",
    "link_flap",
    "bgp_instability",
]

TICKET_STATUSES = ["New", "Investigate", "Monitor", "Closed"]
TICKET_STATUS_WEIGHTS = [0.3, 0.25, 0.25, 0.2]

PRIORITIES = ["P1", "P2", "P3", "P4"]
PRIORITY_WEIGHTS = [0.1, 0.25, 0.35, 0.3]

OWNERS = [
    "alice.chen@contoso.com",
    "bob.martinez@contoso.com",
    "carol.williams@contoso.com",
    "dave.johnson@contoso.com",
    None,  # unassigned
]

CUSTOMERS = ["CUST-001", "CUST-002", "CUST-003", "CUST-004", "CUST-005",
             "CUST-006", "CUST-007", "CUST-008"]

REMEDIATION_ACTIONS = [
    "Escalate to Investigate and enable enhanced monitoring",
    "Set ticket to Monitor and schedule follow-up review",
    "Restart edge monitoring on affected site devices",
]

REMEDIATION_OUTCOMES = [
    "Ticket status updated to Investigate. Enhanced monitoring enabled.",
    "Ticket status updated to Monitor. Follow-up review scheduled.",
    "Edge monitoring restarted. Metrics stabilizing.",
]


def sql_str(val: str | None) -> str:
    """Wrap a value in SQL-safe single quotes, or return NULL."""
    if val is None:
        return "NULL"
    return f"N'{val.replace(chr(39), chr(39)+chr(39))}'"


def sql_dt(dt: datetime) -> str:
    """Format a datetime as SQL DATETIME2 literal."""
    return f"'{dt.strftime('%Y-%m-%dT%H:%M:%S')}'"


def generate_devices(n_devices: int, n_sites: int, now: datetime) -> list[dict]:
    """Generate device rows."""
    devices = []
    for i in range(1, n_devices + 1):
        site_num = ((i - 1) % n_sites) + 1
        health = random.choices(HEALTH_STATES, weights=HEALTH_WEIGHTS, k=1)[0]
        last_seen = now - timedelta(hours=random.randint(0, 48))
        devices.append({
            "device_id": f"DEV-{i:04d}",
            "site_id": f"SITE-{site_num:02d}",
            "model": random.choice(DEVICE_MODELS),
            "last_seen_utc": last_seen,
            "health_state": health,
        })
    return devices


def generate_anomalies(n_anomalies: int, devices: list[dict], days_back: int, now: datetime) -> list[dict]:
    """Generate anomaly rows linked to random devices."""
    anomalies = []
    for i in range(1, n_anomalies + 1):
        device = random.choice(devices)
        severity = random.choices(SEVERITIES, weights=SEVERITY_WEIGHTS, k=1)[0]
        signal = random.choice(SIGNAL_TYPES)
        detected = now - timedelta(
            days=random.randint(0, days_back),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        jitter = round(random.uniform(5, 200), 2) if signal in ("jitter_spike", "link_flap") else round(random.uniform(1, 20), 2)
        loss = round(random.uniform(0.5, 15), 2) if signal == "packet_loss" else round(random.uniform(0, 1), 2)
        latency = round(random.uniform(50, 500), 2) if signal == "latency_spike" else round(random.uniform(5, 50), 2)

        anomalies.append({
            "anomaly_id": f"ANM-{i:04d}",
            "device_id": device["device_id"],
            "detected_utc": detected,
            "severity": severity,
            "signal_type": signal,
            "metric_jitter_ms": jitter,
            "metric_loss_pct": loss,
            "metric_latency_ms": latency,
        })
    return anomalies


def generate_tickets(n_tickets: int, anomalies: list[dict]) -> list[dict]:
    """Generate ticket rows linked to anomalies (1:1 for simplicity, first N anomalies)."""
    tickets = []
    used_anomalies = anomalies[:n_tickets] if n_tickets <= len(anomalies) else anomalies
    for i, anomaly in enumerate(used_anomalies, start=1):
        status = random.choices(TICKET_STATUSES, weights=TICKET_STATUS_WEIGHTS, k=1)[0]
        priority = random.choices(PRIORITIES, weights=PRIORITY_WEIGHTS, k=1)[0]
        owner = random.choice(OWNERS)
        customer = random.choice(CUSTOMERS)
        summary = (
            f"{anomaly['severity']} {anomaly['signal_type'].replace('_', ' ')} "
            f"on {anomaly['device_id']} — "
            f"jitter={anomaly['metric_jitter_ms']}ms, "
            f"loss={anomaly['metric_loss_pct']}%, "
            f"latency={anomaly['metric_latency_ms']}ms"
        )
        tickets.append({
            "ticket_id": f"TKT-{i:04d}",
            "anomaly_id": anomaly["anomaly_id"],
            "status": status,
            "owner": owner,
            "created_utc": anomaly["detected_utc"] + timedelta(minutes=random.randint(1, 30)),
            "summary": summary[:500],
            "customer_id": customer,
            "priority": priority,
        })
    return tickets


def generate_remediations(tickets: list[dict], now: datetime) -> list[dict]:
    """Generate 3 pre-existing remediation log entries for demo continuity."""
    rems = []
    # Pick 3 tickets that are Investigate or Monitor
    candidates = [t for t in tickets if t["status"] in ("Investigate", "Monitor")]
    if len(candidates) < 3:
        candidates = tickets[:3]
    else:
        candidates = candidates[:3]

    for i, ticket in enumerate(candidates):
        action = REMEDIATION_ACTIONS[i % len(REMEDIATION_ACTIONS)]
        outcome = REMEDIATION_OUTCOMES[i % len(REMEDIATION_OUTCOMES)]
        approved_utc = ticket["created_utc"] + timedelta(minutes=random.randint(5, 60))
        executed_utc = approved_utc + timedelta(minutes=random.randint(1, 10))
        rems.append({
            "ticket_id": ticket["ticket_id"],
            "proposed_action": action,
            "rationale": f"Auto-generated seed remediation for {ticket['ticket_id']}",
            "status": "EXECUTED",
            "approved_by": "seed-admin@contoso.com",
            "approved_utc": approved_utc,
            "executed_utc": executed_utc,
            "outcome": outcome,
            "correlation_id": f"seed-{i+1:04d}-0000-0000-000000000000",
        })
    return rems


def emit_sql(devices, anomalies, tickets, remediations):
    """Print complete seed.sql to stdout."""
    print("-- ============================================================================")
    print("-- seed.sql — IQ Foundry Agent Lab Seed Data (auto-generated)")
    print(f"-- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"-- Counts: {len(devices)} devices, {len(anomalies)} anomalies, "
          f"{len(tickets)} tickets, {len(remediations)} remediations")
    print("-- ============================================================================")
    print()

    # Devices
    print("-- -----------------------------------------------------------------------")
    print(f"-- Devices: {len(devices)} across {len(set(d['site_id'] for d in devices))} sites")
    print("-- -----------------------------------------------------------------------")
    for d in devices:
        print(
            f"INSERT INTO dbo.iq_devices (device_id, site_id, model, last_seen_utc, health_state) "
            f"VALUES ({sql_str(d['device_id'])}, {sql_str(d['site_id'])}, {sql_str(d['model'])}, "
            f"{sql_dt(d['last_seen_utc'])}, {sql_str(d['health_state'])});"
        )
    print("GO")
    print()

    # Anomalies
    print("-- -----------------------------------------------------------------------")
    print(f"-- Anomalies: {len(anomalies)} over last 14 days")
    print("-- -----------------------------------------------------------------------")
    for a in anomalies:
        print(
            f"INSERT INTO dbo.iq_anomalies (anomaly_id, device_id, detected_utc, severity, "
            f"signal_type, metric_jitter_ms, metric_loss_pct, metric_latency_ms) "
            f"VALUES ({sql_str(a['anomaly_id'])}, {sql_str(a['device_id'])}, "
            f"{sql_dt(a['detected_utc'])}, {sql_str(a['severity'])}, "
            f"{sql_str(a['signal_type'])}, {a['metric_jitter_ms']}, "
            f"{a['metric_loss_pct']}, {a['metric_latency_ms']});"
        )
    print("GO")
    print()

    # Tickets
    print("-- -----------------------------------------------------------------------")
    print(f"-- Tickets: {len(tickets)} with varied statuses")
    print("-- -----------------------------------------------------------------------")
    for t in tickets:
        print(
            f"INSERT INTO dbo.iq_tickets (ticket_id, anomaly_id, status, owner, "
            f"created_utc, summary, customer_id, priority) "
            f"VALUES ({sql_str(t['ticket_id'])}, {sql_str(t['anomaly_id'])}, "
            f"{sql_str(t['status'])}, {sql_str(t['owner'])}, "
            f"{sql_dt(t['created_utc'])}, {sql_str(t['summary'])}, "
            f"{sql_str(t['customer_id'])}, {sql_str(t['priority'])});"
        )
    print("GO")
    print()

    # Remediations
    print("-- -----------------------------------------------------------------------")
    print(f"-- Remediation Log: {len(remediations)} pre-existing entries")
    print("-- -----------------------------------------------------------------------")
    print("SET IDENTITY_INSERT dbo.iq_remediation_log OFF;")
    for r in remediations:
        print(
            f"INSERT INTO dbo.iq_remediation_log (ticket_id, proposed_action, rationale, "
            f"status, approved_by, approved_utc, executed_utc, outcome, correlation_id) "
            f"VALUES ({sql_str(r['ticket_id'])}, {sql_str(r['proposed_action'])}, "
            f"{sql_str(r['rationale'])}, {sql_str(r['status'])}, "
            f"{sql_str(r['approved_by'])}, {sql_dt(r['approved_utc'])}, "
            f"{sql_dt(r['executed_utc'])}, {sql_str(r['outcome'])}, "
            f"{sql_str(r['correlation_id'])});"
        )
    print("GO")
    print()
    print("PRINT 'Seed data loaded successfully.';")
    print("GO")


def main():
    parser = argparse.ArgumentParser(description="Generate seed SQL for IQ Lab")
    parser.add_argument("--devices", type=int, default=30, help="Number of devices")
    parser.add_argument("--anomalies", type=int, default=80, help="Number of anomalies")
    parser.add_argument("--tickets", type=int, default=50, help="Number of tickets")
    parser.add_argument("--sites", type=int, default=4, help="Number of sites")
    parser.add_argument("--days-back", type=int, default=14, help="Anomaly date range in days")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    random.seed(args.seed)
    now = datetime(2026, 2, 28, 15, 0, 0)  # Fixed "now" for reproducible seed data

    devices = generate_devices(args.devices, args.sites, now)
    anomalies = generate_anomalies(args.anomalies, devices, args.days_back, now)
    tickets = generate_tickets(args.tickets, anomalies)
    remediations = generate_remediations(tickets, now)

    emit_sql(devices, anomalies, tickets, remediations)


if __name__ == "__main__":
    main()
