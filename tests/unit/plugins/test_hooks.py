"""Unit tests for F7.2 HookManager."""

from __future__ import annotations

import pytest

from api2mcp.plugins.hooks import (
    KNOWN_HOOKS,
    ON_TOOL_CALL,
    POST_GENERATE,
    POST_PARSE,
    PRE_GENERATE,
    PRE_PARSE,
    PRE_SERVE,
    HookManager,
    HookRegistration,
)

# ---------------------------------------------------------------------------
# Known hooks constants
# ---------------------------------------------------------------------------


def test_known_hooks_contains_all_extension_points() -> None:
    expected = {PRE_PARSE, POST_PARSE, PRE_GENERATE, POST_GENERATE, PRE_SERVE, ON_TOOL_CALL}
    assert expected <= KNOWN_HOOKS


# ---------------------------------------------------------------------------
# HookRegistration
# ---------------------------------------------------------------------------


def test_hook_registration_repr() -> None:
    reg = HookRegistration(hook="post_parse", callback=lambda: None, plugin_id="p1", priority=50)
    assert "post_parse" in repr(reg)
    assert "p1" in repr(reg)


# ---------------------------------------------------------------------------
# register_hook
# ---------------------------------------------------------------------------


def test_register_hook_records_callback() -> None:
    manager = HookManager()
    def cb(**kw: object) -> None:
        pass
    manager.register_hook(POST_PARSE, cb, plugin_id="p1")
    assert manager.hook_count(POST_PARSE) == 1


def test_register_multiple_hooks_same_event() -> None:
    manager = HookManager()
    manager.register_hook(POST_PARSE, lambda **kw: None)
    manager.register_hook(POST_PARSE, lambda **kw: None)
    assert manager.hook_count(POST_PARSE) == 2


def test_register_hooks_sorted_by_priority() -> None:
    manager = HookManager()
    results: list[int] = []
    manager.register_hook(POST_PARSE, lambda **kw: results.append(200), priority=200)
    manager.register_hook(POST_PARSE, lambda **kw: results.append(10), priority=10)
    manager.register_hook(POST_PARSE, lambda **kw: results.append(50), priority=50)
    regs = manager.registered_hooks(POST_PARSE)
    priorities = [r.priority for r in regs]
    assert priorities == sorted(priorities)


def test_register_hook_returns_registration() -> None:
    manager = HookManager()
    reg = manager.register_hook(PRE_PARSE, lambda **kw: None, plugin_id="x")
    assert isinstance(reg, HookRegistration)
    assert reg.plugin_id == "x"


# ---------------------------------------------------------------------------
# unregister_hook
# ---------------------------------------------------------------------------


def test_unregister_hook_removes_callback() -> None:
    manager = HookManager()
    reg = manager.register_hook(POST_PARSE, lambda **kw: None)
    removed = manager.unregister_hook(reg)
    assert removed is True
    assert manager.hook_count(POST_PARSE) == 0


def test_unregister_unknown_returns_false() -> None:
    manager = HookManager()
    reg = HookRegistration(hook=POST_PARSE, callback=lambda: None)
    assert manager.unregister_hook(reg) is False


# ---------------------------------------------------------------------------
# emit — async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_calls_async_callback() -> None:
    manager = HookManager()
    called: list[str] = []

    async def cb(**kw: object) -> None:
        called.append("yes")

    manager.register_hook(POST_PARSE, cb)
    await manager.emit(POST_PARSE)
    assert called == ["yes"]


@pytest.mark.asyncio
async def test_emit_calls_sync_callback() -> None:
    manager = HookManager()
    called: list[int] = []

    def cb(**kw: object) -> None:
        called.append(1)

    manager.register_hook(PRE_PARSE, cb)
    await manager.emit(PRE_PARSE)
    assert called == [1]


@pytest.mark.asyncio
async def test_emit_forwards_kwargs() -> None:
    manager = HookManager()
    received: dict = {}

    def cb(**kw: object) -> None:
        received.update(kw)

    manager.register_hook(POST_PARSE, cb)
    await manager.emit(POST_PARSE, api_spec="spec", source="file.yaml")
    assert received == {"api_spec": "spec", "source": "file.yaml"}


@pytest.mark.asyncio
async def test_emit_collects_return_values() -> None:
    manager = HookManager()
    manager.register_hook(POST_PARSE, lambda **kw: 42)
    manager.register_hook(POST_PARSE, lambda **kw: "hello")
    results = await manager.emit(POST_PARSE)
    assert results == [42, "hello"]


@pytest.mark.asyncio
async def test_emit_continues_after_exception() -> None:
    manager = HookManager()
    called: list[int] = []

    def bad(**kw: object) -> None:
        raise RuntimeError("boom")

    def good(**kw: object) -> None:
        called.append(1)

    manager.register_hook(POST_PARSE, bad, priority=1)
    manager.register_hook(POST_PARSE, good, priority=2)
    results = await manager.emit(POST_PARSE)
    # bad callback: exception swallowed → None; good callback: returns None implicitly
    assert results == [None, None]
    assert called == [1]


@pytest.mark.asyncio
async def test_emit_no_hooks_returns_empty_list() -> None:
    manager = HookManager()
    results = await manager.emit("unknown_event")
    assert results == []


@pytest.mark.asyncio
async def test_emit_priority_order() -> None:
    manager = HookManager()
    order: list[int] = []

    manager.register_hook(ON_TOOL_CALL, lambda **kw: order.append(3), priority=300)
    manager.register_hook(ON_TOOL_CALL, lambda **kw: order.append(1), priority=10)
    manager.register_hook(ON_TOOL_CALL, lambda **kw: order.append(2), priority=50)

    await manager.emit(ON_TOOL_CALL)
    assert order == [1, 2, 3]


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_all() -> None:
    manager = HookManager()
    manager.register_hook(PRE_PARSE, lambda **kw: None)
    manager.register_hook(POST_PARSE, lambda **kw: None)
    manager.clear()
    assert manager.hook_count(PRE_PARSE) == 0
    assert manager.hook_count(POST_PARSE) == 0


@pytest.mark.asyncio
async def test_clear_specific_event() -> None:
    manager = HookManager()
    manager.register_hook(PRE_PARSE, lambda **kw: None)
    manager.register_hook(POST_PARSE, lambda **kw: None)
    manager.clear(PRE_PARSE)
    assert manager.hook_count(PRE_PARSE) == 0
    assert manager.hook_count(POST_PARSE) == 1


# ---------------------------------------------------------------------------
# registered_hooks
# ---------------------------------------------------------------------------


def test_registered_hooks_all() -> None:
    manager = HookManager()
    manager.register_hook(PRE_PARSE, lambda **kw: None, plugin_id="a")
    manager.register_hook(POST_PARSE, lambda **kw: None, plugin_id="b")
    all_regs = manager.registered_hooks()
    assert len(all_regs) == 2


def test_registered_hooks_filtered() -> None:
    manager = HookManager()
    manager.register_hook(PRE_PARSE, lambda **kw: None)
    manager.register_hook(POST_PARSE, lambda **kw: None)
    regs = manager.registered_hooks(PRE_PARSE)
    assert len(regs) == 1
    assert regs[0].hook == PRE_PARSE
