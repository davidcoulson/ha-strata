"""Shared fixtures."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.strata.const import DOMAIN

HOST = "10.0.0.5"
PORT = 8095
BASE = f"http://{HOST}:{PORT}"
API_KEY = "super-secret-key"

HEALTH = {"status": "ok", "service": "strata", "loaded": True, "model": "m1"}
STATUS = {
    "service": "strata",
    "model": "qwen-test",
    "loaded": True,
    "engine": "0.1.45",
    "started": 1792429874,
    "context": {"native": 131072},
    "activity": {"requests": 11, "in_flight": 0},
    "last_timings": {
        "cache_n": 900,
        "prompt_n": 100,
        "predicted_per_second": 88.2,
        "prompt_per_second": 445.2,
        "draft_n": 150,
        "draft_n_accepted": 96,
    },
    "machine": {"gpu": {"temp_c": 34, "util_pct": 7, "used_mib": 21141.0}},
}
SLOTS = [{"id": 0, "n_ctx": 131072, "is_processing": False, "n_prompt_tokens": 6103}]
METRICS = {"engine": {"kv": "int8", "version": "0.1.45"}, "live": {"state": "idle", "queued": 0}}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""


@pytest.fixture
def entry() -> MockConfigEntry:
    """Return a config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Strata",
        unique_id=f"{HOST}:{PORT}",
        data={
            "host": HOST,
            "port": PORT,
            "api_key": API_KEY,
            "ssl": False,
            "verify_ssl": False,
        },
    )


def mock_server(aioclient_mock, *, status=STATUS, slots=SLOTS, metrics=METRICS):
    """Register a healthy server."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/health", json=HEALTH)
    aioclient_mock.get(f"{BASE}/v1/status", json=status)
    aioclient_mock.get(f"{BASE}/slots", json=slots)
    aioclient_mock.get(f"{BASE}/metrics", json=metrics)
