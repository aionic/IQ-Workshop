# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "azure-ai-projects>=2.0.0b2",
#     "azure-identity>=1.15.0",
#     "openai>=1.70.0",
# ]
# ///
"""
upload_knowledge.py -- Upload device manuals and docs to a Foundry vector store.

Creates (or reuses) a vector store named ``iq-device-manuals`` and uploads
the knowledge files listed in KNOWLEDGE_FILES.  The resulting vector_store_id
is saved to ``.agent-state.json`` so that ``create_agent.py`` can attach it
via ``--vector-store-id``.

This is a separate step from agent registration so that labs can demonstrate
knowledge grounding independently.

Usage:

    uv run scripts/upload_knowledge.py --resource-group rg-iq-lab-dev

Force re-upload (replace existing vector store contents):

    uv run scripts/upload_knowledge.py --resource-group rg-iq-lab-dev --force
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Knowledge files -- uploaded to Foundry vector store for file_search grounding.
# Paths are relative to REPO_ROOT.
# ---------------------------------------------------------------------------

KNOWLEDGE_FILES: list[dict[str, str]] = [
    # Device manuals -- one per model in seed data
    {"path": "data/manuals/cisco-asr-9000.md", "purpose": "agents"},
    {"path": "data/manuals/cisco-catalyst-9300.md", "purpose": "agents"},
    {"path": "data/manuals/juniper-mx960.md", "purpose": "agents"},
    {"path": "data/manuals/juniper-qfx5120.md", "purpose": "agents"},
    {"path": "data/manuals/arista-7280r3.md", "purpose": "agents"},
    {"path": "data/manuals/nokia-7750-sr.md", "purpose": "agents"},
    {"path": "data/manuals/ciena-6500.md", "purpose": "agents"},
    # Operational docs
    {"path": "docs/guardrails.md", "purpose": "agents"},
    {"path": "docs/runbook.md", "purpose": "agents"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _az_output(cmd: list[str]) -> str:
    """Run an az CLI command and return stripped stdout."""
    az_exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run(  # noqa: S603
        [az_exe, *cmd[1:]], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _resolve_project_endpoint(resource_group: str) -> str:
    """Fetch the Foundry project endpoint from Bicep deployment outputs."""
    print(f"Resolving project endpoint from Bicep outputs in {resource_group}...")
    raw = _az_output([
        "az", "deployment", "group", "show",
        "--resource-group", resource_group,
        "--name", "main",
        "--query", "properties.outputs.foundryProjectEndpoint.value",
        "--output", "tsv",
    ])
    if not raw:
        raise SystemExit(
            f"ERROR: No 'foundryProjectEndpoint' in Bicep outputs for {resource_group}."
        )
    return raw


def _find_existing_vector_store(
    openai_client: object,
    name: str = "iq-device-manuals",
) -> str | None:
    """Return the ID of an existing vector store with the given name, or None."""
    # Check .agent-state.json first for a previously saved vector store ID.
    state_path = REPO_ROOT / ".agent-state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            vs_id = state.get("vector_store_id")
            if vs_id:
                try:
                    vs = openai_client.vector_stores.retrieve(vector_store_id=vs_id)  # type: ignore[union-attr]
                    if vs and vs.name == name:
                        return vs.id
                except Exception:
                    pass  # stale reference
        except (json.JSONDecodeError, KeyError):
            pass

    # List vector stores and look for one matching our name
    try:
        stores = openai_client.vector_stores.list()  # type: ignore[union-attr]
        for vs in stores:
            if vs.name == name:
                return vs.id
    except Exception:
        pass

    return None


def _save_state(vector_store_id: str) -> None:
    """Merge vector_store_id into .agent-state.json (preserving other keys)."""
    state_path = REPO_ROOT / ".agent-state.json"
    state: dict[str, object] = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    state["vector_store_id"] = vector_store_id
    state_path.write_text(json.dumps(state, indent=2))
    print(f"\nVector store ID saved to {state_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload knowledge files to a Foundry vector store.",
    )
    parser.add_argument(
        "--resource-group", "-g",
        default=os.environ.get("RESOURCE_GROUP", ""),
        help="Azure RG to resolve the Foundry project endpoint. Prompted if not set.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload all files even if a vector store already exists.",
    )
    args = parser.parse_args()

    # --- Resolve resource group ---
    if not args.resource_group:
        args.resource_group = input("Resource group (e.g. rg-iq-lab-dev): ").strip()
    if not args.resource_group:
        print("ERROR: --resource-group is required.", file=sys.stderr)
        sys.exit(1)

    project_endpoint = _resolve_project_endpoint(args.resource_group)
    print(f"  Project: {project_endpoint}")

    # --- Connect and get OpenAI client ---
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential,
    )
    openai_client = project_client.get_openai_client()

    # --- Check for existing vector store ---
    if not args.force:
        existing_id = _find_existing_vector_store(openai_client)
        if existing_id:
            print(f"\n  Reusing existing vector store: {existing_id}")
            print("  (pass --force to re-upload)")
            _save_state(existing_id)
            print(f"\nDone. Use this with create_agent.py:")
            print(f"  uv run scripts/create_agent.py -g {args.resource_group} --vector-store-id {existing_id}")
            return

    # --- Create vector store and upload files ---
    print("\nCreating vector store...")
    vector_store = openai_client.vector_stores.create(name="iq-device-manuals")
    print(f"  Vector store: {vector_store.id}")

    uploaded_count = 0
    for entry in KNOWLEDGE_FILES:
        filepath = REPO_ROOT / entry["path"]
        if not filepath.exists():
            print(f"  WARNING: {entry['path']} not found, skipping.")
            continue
        with open(filepath, "rb") as f:
            uploaded = openai_client.vector_stores.files.upload_and_poll(
                vector_store_id=vector_store.id, file=f,
            )
        print(f"  Uploaded: {entry['path']} -> {uploaded.id}")
        uploaded_count += 1

    if uploaded_count == 0:
        print("  WARNING: No files were uploaded.")
    else:
        print(f"\n  {uploaded_count} files uploaded to vector store {vector_store.id}")

    _save_state(vector_store.id)

    print(f"\nDone. Use this with create_agent.py:")
    print(f"  uv run scripts/create_agent.py -g {args.resource_group} --vector-store-id {vector_store.id}")


if __name__ == "__main__":
    main()
