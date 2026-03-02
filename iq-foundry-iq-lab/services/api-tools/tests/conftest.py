"""conftest.py — shared pytest fixtures for api-tools tests."""

import sys
from pathlib import Path

# Ensure the app package is importable from tests/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
