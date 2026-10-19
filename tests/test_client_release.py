"""The client must release connections on HTTP error paths (real aiohttp, no mocks)."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.strata.client import (
    StrataAuthError,
    StrataClient,
    StrataConnectionError,
)


async def _big_error(request: web.Request) -> web.StreamResponse:
    status = int(request.match_info["code"])
    resp = web.StreamResponse(status=status)
    await resp.prepare(request)
    try:
        for _ in range(200):
            await resp.write(b"x" * 65536)
    except ConnectionResetError:
        pass
    return resp


@pytest.mark.enable_socket
@pytest.mark.parametrize(("code", "exc"), [(401, StrataAuthError), (500, StrataConnectionError)])
async def test_error_responses_release_the_connection(socket_enabled, code, exc) -> None:
    """With a one-connection pool, repeated failures must not exhaust it."""
    app = web.Application()
    app.router.add_get("/err/{code}", _big_error)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=1)) as session:
            client = StrataClient(session, str(server.make_url("")), "k")
            for _ in range(3):
                with pytest.raises(exc):
                    await asyncio.wait_for(client.get(f"/err/{code}"), 5)
    finally:
        await server.close()


async def _slow(request: web.Request) -> web.StreamResponse:
    await asyncio.sleep(30)
    return web.json_response({})


async def test_optional_endpoint_times_out_fast(socket_enabled, monkeypatch) -> None:
    """slots/metrics use the short timeout, so a stalled server cannot hold up a poll."""
    monkeypatch.setattr("custom_components.strata.client.OPTIONAL_TIMEOUT", 0.2)
    app = web.Application()
    app.router.add_get("/slots", _slow)
    server = TestServer(app)
    await server.start_server()
    try:
        async with aiohttp.ClientSession() as session:
            client = StrataClient(session, str(server.make_url("")), "k")
            with pytest.raises(StrataConnectionError):
                await asyncio.wait_for(client.slots(), 5)
    finally:
        await server.close()
