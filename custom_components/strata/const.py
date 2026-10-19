"""Constants for the Strata integration."""

from __future__ import annotations

DOMAIN = "strata"

CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 8095
DEFAULT_SSL = False
DEFAULT_VERIFY_SSL = False
DEFAULT_SCAN_INTERVAL = 15
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300

REQUEST_TIMEOUT = 10
