"""Constants for the Strata integration."""

from __future__ import annotations

DOMAIN = "strata"

CONF_SSL = "ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 8095
DEFAULT_SSL = False
DEFAULT_VERIFY_SSL = True
DEFAULT_SCAN_INTERVAL = 15
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300

REQUEST_TIMEOUT = 10
OPTIONAL_TIMEOUT = 3  # slots and metrics are extras; do not let them stall a poll


def build_base_url(host: str, port: int, ssl: bool) -> str:
    """Build the server base URL."""
    if ":" in host and not host.startswith("["):  # bare IPv6 literal
        host = f"[{host}]"
    return f"{'https' if ssl else 'http'}://{host}:{port}"
