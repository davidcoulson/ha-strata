"""The dev-only reload_code action swaps in the Python files on disk."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.exceptions import HomeAssistantError

from custom_components.strata.const import DOMAIN

from .conftest import mock_server


async def test_reload_code_replaces_the_modules(hass, aioclient_mock, entry) -> None:
    mock_server(aioclient_mock)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old = {n: m for n, m in sys.modules.items() if n.startswith("custom_components.strata")}
    assert hass.services.has_service(DOMAIN, "reload_code")

    await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert sys.modules["custom_components.strata"] is not old["custom_components.strata"]
    assert sys.modules["custom_components.strata.const"] is not old["custom_components.strata.const"]
    assert hass.services.has_service(DOMAIN, "reload_code")


@pytest.mark.parametrize(
    ("target", "result"),
    [
        (ConfigEntries, "async_unload"),
        (importlib, "import_module"),
        (ConfigEntries, "async_setup"),
    ],
)
async def test_reload_code_reports_failures(hass, aioclient_mock, entry, target, result) -> None:
    mock_server(aioclient_mock)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    kwargs = {"return_value": False}
    if target is importlib:  # unload needs the old module; only the fresh import fails
        real = importlib.import_module

        def kwargs_wrapper(name, *a, **k):
            if name == "custom_components.strata" and name not in sys.modules:
                raise ImportError("boom")
            return real(name, *a, **k)

        kwargs = {"new": kwargs_wrapper}
    with patch.object(target, result, **kwargs), pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "reload_code", {}, blocking=True)
    # the action survives a failed reload, so it can be called again once the code is fixed
    assert hass.services.has_service(DOMAIN, "reload_code")


def test_marketplace_restart_cleanup_matches_only_the_running_version(hass, monkeypatch):
    """Only Marketplace's restart repairs for this version of this integration are dropped."""
    from homeassistant.helpers import issue_registry as ir

    import custom_components.strata as integration

    monkeypatch.setattr(integration, "_CODE_VERSION", "1.2.3")
    kept = {
        ("marketplace", "restart_required_1_tags/1.2.4"),
        ("marketplace", "restart_required_2_tags/1.2.3"),
        ("marketplace", "critical_x"),
        ("strata", "restart_required_x"),
    }
    for domain, issue_id, issue_domain in (
        ("marketplace", "restart_required_1_tags/1.2.3", "strata"),
        ("marketplace", "restart_required_1_tags/v1.2.3", "strata"),
        ("marketplace", "restart_required_1_tags/1.2.4", "strata"),
        ("marketplace", "restart_required_2_tags/1.2.3", "ssh"),
        ("marketplace", "critical_x", "strata"),
        ("strata", "restart_required_x", "strata"),
    ):
        ir.async_create_issue(
            hass,
            domain,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="x",
            issue_domain=issue_domain,
        )
    integration._clear_marketplace_restart(hass)
    assert set(ir.async_get(hass).issues) == kept


def test_code_version_is_the_manifest_version():
    import json
    from pathlib import Path

    import custom_components.strata as integration

    manifest = Path(integration.__file__).parent / "manifest.json"
    assert json.loads(manifest.read_text())["version"] == integration._CODE_VERSION
