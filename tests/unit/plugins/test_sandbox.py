"""Unit tests for F7.2 PluginSandbox."""

from __future__ import annotations

import asyncio

import pytest

from api2mcp.plugins.sandbox import (
    _BLOCKED_BUILTINS,
    PluginSandbox,
    SandboxViolation,
    make_restricted_builtins,
)

# ---------------------------------------------------------------------------
# PluginSandbox.call — basic invocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_calls_async_callback() -> None:
    sandbox = PluginSandbox()
    called: list[bool] = []

    async def cb(**kw: object) -> str:
        called.append(True)
        return "result"

    result = await sandbox.call(cb)
    assert result == "result"
    assert called == [True]


@pytest.mark.asyncio
async def test_sandbox_calls_sync_callback() -> None:
    sandbox = PluginSandbox()

    def cb(**kw: object) -> int:
        return 42

    result = await sandbox.call(cb)
    assert result == 42


@pytest.mark.asyncio
async def test_sandbox_forwards_kwargs() -> None:
    sandbox = PluginSandbox()
    received: dict = {}

    def cb(**kw: object) -> None:
        received.update(kw)

    await sandbox.call(cb, api_spec="spec", x=1)
    assert received == {"api_spec": "spec", "x": 1}


# ---------------------------------------------------------------------------
# Exception isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_swallows_exception_by_default() -> None:
    sandbox = PluginSandbox()

    async def bad(**kw: object) -> None:
        raise ValueError("oops")

    result = await sandbox.call(bad)
    assert result is None


@pytest.mark.asyncio
async def test_sandbox_reraises_when_configured() -> None:
    sandbox = PluginSandbox(reraise=True)

    async def bad(**kw: object) -> None:
        raise ValueError("oops")

    with pytest.raises(ValueError, match="oops"):
        await sandbox.call(bad)


@pytest.mark.asyncio
async def test_sandbox_swallows_sandbox_violation() -> None:
    sandbox = PluginSandbox()

    def blocked(**kw: object) -> None:
        raise SandboxViolation("blocked")

    result = await sandbox.call(blocked)
    assert result is None


@pytest.mark.asyncio
async def test_sandbox_reraises_sandbox_violation_when_configured() -> None:
    sandbox = PluginSandbox(reraise=True)

    def blocked(**kw: object) -> None:
        raise SandboxViolation("blocked")

    with pytest.raises(SandboxViolation):
        await sandbox.call(blocked)


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_timeout_async() -> None:
    sandbox = PluginSandbox(timeout=0.05)

    async def slow(**kw: object) -> None:
        await asyncio.sleep(10)

    result = await sandbox.call(slow)
    assert result is None  # timed out, swallowed


@pytest.mark.asyncio
async def test_sandbox_timeout_reraises_when_configured() -> None:
    sandbox = PluginSandbox(timeout=0.05, reraise=True)

    async def slow(**kw: object) -> None:
        await asyncio.sleep(10)

    with pytest.raises(asyncio.TimeoutError):
        await sandbox.call(slow)


@pytest.mark.asyncio
async def test_sandbox_no_timeout_when_none() -> None:
    sandbox = PluginSandbox(timeout=None)
    called: list[bool] = []

    async def fast(**kw: object) -> None:
        called.append(True)

    await sandbox.call(fast)
    assert called == [True]


# ---------------------------------------------------------------------------
# make_restricted_builtins
# ---------------------------------------------------------------------------


def test_restricted_builtins_blocks_dangerous() -> None:
    builtins = make_restricted_builtins()
    for name in _BLOCKED_BUILTINS:
        stub = builtins.get(name)
        if stub is not None:
            with pytest.raises(SandboxViolation):
                stub()


def test_restricted_builtins_allows_safe_builtins() -> None:
    builtins = make_restricted_builtins()
    # These should still be callable
    assert callable(builtins.get("print"))
    assert callable(builtins.get("len"))
    assert callable(builtins.get("range"))
