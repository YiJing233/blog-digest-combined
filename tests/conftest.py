"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def today_iso() -> str:
    return "2026-09-23"
