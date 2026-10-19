# Strata for Home Assistant

A custom integration that monitors a [Strata](https://github.com/Niko1221/Strata) local LLM
server: whether it is up, which model is loaded, whether it is busy, and how fast it is
running. Read-only: it only issues `GET` requests.

## Install with HACS

1. HACS, three-dot menu, **Custom repositories**.
2. Add `https://github.com/davidcoulson/ha-strata` (placeholder; use the real URL) as an
   **Integration**.
3. Install **Strata**, restart Home Assistant. Updates then arrive through HACS.

## Setup

**Settings, Devices & services, Add integration, Strata.**

| Field | Notes |
| --- | --- |
| Host | Address of the Strata server, e.g. `192.168.1.50` |
| Port | Default `8095` |
| API key | Sent as `Authorization: Bearer <key>` |
| Use HTTPS | Off by default |
| Verify SSL certificate | Off by default; only matters with HTTPS |

The host is checked against `/health` and the key against `/v1/status` (`/health` does not
require a key). A changed or wrong key triggers the re-authentication flow. The poll interval
(default 15 s, 5 to 300) is under the integration's **Configure** button.

While the server is off or unreachable, every entity except *Server reachable* is shown as
unavailable, and nothing is logged on each poll.

## Entities

One device per server.

Binary sensors: **Server reachable** (connectivity, diagnostic), **Model loaded**, **Busy**
(a request is being processed).

Sensors: **Model**, **Context size**\*, **KV cache type**\*, **Engine version**\*,
**Started**\*, **Prompt tokens in slot**, **Queued requests**, **Requests served**\*,
**Generation speed** (tok/s, last request), **Prompt processing speed** (tok/s, last request),
**Prompt cache hit ratio** (last request), **Draft acceptance**\* (speculative decoding, last
request), **GPU temperature**\*, **GPU utilization**\*, **GPU memory used**\*.

\* diagnostic entity category.

Data comes from `/v1/status`, `/slots` and `/metrics`. Fields the server does not report
show as unknown.

## Voice / conversation

This integration does not provide a conversation agent. For voice, add Home Assistant's
**OpenAI Conversation** integration (or an OpenAI-compatible custom conversation integration)
and point its base URL at `http://<host>:8095/v1` with the same API key.

## Possible future work

- Load / unload model controls (`/load`, `/unload`, POST).
- Prometheus counters as long-term statistics.
- Submit the brand images to the Home Assistant `brands` repository (they already ship in `custom_components/strata/brand/`, which current Home Assistant reads directly).

## Credits

The icon is the Strata app icon from [Niko1221/Strata](https://github.com/Niko1221/Strata) (MIT licence). This project is not affiliated with or endorsed by the Strata authors.

## Development

```
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/pytest
```

Tests require 100% coverage. `pycares<4.9` is pinned because newer releases leave a thread
that Home Assistant's test cleanup rejects.
