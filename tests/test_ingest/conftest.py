"""Shared fixtures for ingest tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
INPUTS_DIR = FIXTURES / "inputs"
AAPL_INPUTS = INPUTS_DIR / "AAPL"
