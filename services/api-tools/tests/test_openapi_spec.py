"""
test_openapi_spec.py — Validates the OpenAPI spec is well-formed and matches the app.

Tests:
  - JSON is parseable
  - Required paths exist
  - Schema references resolve
  - FastAPI-generated spec matches expected endpoints
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app

SPEC_PATH = Path(__file__).resolve().parents[3] / "foundry" / "tools.openapi.json"


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def mock_init_db():
    with patch("app.db.init_db_pool"), patch("app.db.close_db_pool"):
        yield


@pytest_asyncio.fixture
async def client(mock_init_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# -----------------------------------------------------------------------
# Static spec file tests
# -----------------------------------------------------------------------


class TestStaticOpenAPISpec:
    """Validate the hand-authored foundry/tools.openapi.json."""

    def test_spec_is_valid_json(self):
        """Spec file is parseable JSON."""
        text = SPEC_PATH.read_text(encoding="utf-8")
        spec = json.loads(text)
        assert isinstance(spec, dict)

    def test_spec_has_openapi_version(self):
        """Spec declares openapi version."""
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        assert spec.get("openapi", "").startswith("3.")

    def test_spec_required_paths(self):
        """All tool paths are present."""
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        paths = spec.get("paths", {})
        expected = [
            "/tools/query-ticket-context",
            "/tools/request-approval",
            "/tools/execute-remediation",
            "/tools/post-teams-summary",
        ]
        for p in expected:
            assert p in paths, f"Missing path: {p}"

    def test_spec_schemas_not_empty(self):
        """Components/schemas section is populated."""
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        schemas = spec.get("components", {}).get("schemas", {})
        assert len(schemas) >= 6, f"Expected ≥6 schemas, got {len(schemas)}"

    def test_spec_schema_refs_resolve(self):
        """All $ref pointers in paths resolve to existing schema names."""
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        schemas = set(spec.get("components", {}).get("schemas", {}).keys())

        unresolved: list[str] = []
        _collect_refs(spec.get("paths", {}), schemas, unresolved)
        assert not unresolved, f"Unresolved $ref(s): {unresolved}"


def _collect_refs(obj: object, schemas: set[str], unresolved: list[str]) -> None:
    """Recursively find $ref values and check they resolve."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "$ref" and isinstance(v, str):
                # e.g. "#/components/schemas/ErrorResponse"
                parts = v.split("/")
                if len(parts) == 4 and parts[-1] not in schemas:
                    unresolved.append(v)
            else:
                _collect_refs(v, schemas, unresolved)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, schemas, unresolved)


# -----------------------------------------------------------------------
# FastAPI auto-generated spec tests
# -----------------------------------------------------------------------


class TestFastAPIGeneratedSpec:
    """Validate the FastAPI-generated /openapi.json."""

    @pytest.mark.asyncio
    async def test_openapi_endpoint_returns_200(self, client: AsyncClient):
        """GET /openapi.json returns 200."""
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_endpoint_has_paths(self, client: AsyncClient):
        """Auto-generated spec contains all endpoints."""
        resp = await client.get("/openapi.json")
        spec = resp.json()
        expected_paths = [
            "/health",
            "/tools/query-ticket-context",
            "/tools/request-approval",
            "/tools/execute-remediation",
            "/tools/post-teams-summary",
            "/admin/approvals",
            "/admin/approvals/{remediation_id}/decide",
        ]
        for p in expected_paths:
            assert p in spec["paths"], f"Missing path in generated spec: {p}"

    @pytest.mark.asyncio
    async def test_openapi_title_matches(self, client: AsyncClient):
        """Generated spec title matches app config."""
        resp = await client.get("/openapi.json")
        spec = resp.json()
        assert spec["info"]["title"] == "IQ Foundry Agent Lab — Tool Service"
