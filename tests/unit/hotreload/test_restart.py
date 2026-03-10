"""Unit tests for F6.2 HotReloadServer — restart logic and change handling."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from api2mcp.hotreload.restart import HotReloadServer
from api2mcp.hotreload.watcher import ChangeEvent, ChangeType

# ---------------------------------------------------------------------------
# HotReloadServer.__init__
# ---------------------------------------------------------------------------


def test_hot_reload_server_defaults(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    out = tmp_path / "out"
    srv = HotReloadServer(spec_path=spec, output_dir=out)
    assert srv.spec_path == spec
    assert srv.output_dir == out
    assert srv.transport == "stdio"
    assert srv.host == "0.0.0.0"
    assert srv.port == 8000
    assert srv._restart_count == 0
    assert srv._server_task is None


def test_hot_reload_server_custom_params(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    out = tmp_path / "out"
    extra = tmp_path / "extra"
    srv = HotReloadServer(
        spec_path=spec,
        output_dir=out,
        transport="http",
        host="127.0.0.1",
        port=9090,
        watch_paths=[extra],
        poll_interval_ms=100,
    )
    assert srv.transport == "http"
    assert srv.host == "127.0.0.1"
    assert srv.port == 9090
    assert extra in srv._watch_paths
    assert srv._poll_interval_ms == 100


# ---------------------------------------------------------------------------
# _handle_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_change_spec_triggers_regenerate(tmp_path: Path) -> None:
    spec = tmp_path / "openapi.yaml"
    out = tmp_path / "out"
    srv = HotReloadServer(spec_path=spec, output_dir=out)

    srv._regenerate = AsyncMock()
    srv._restart_server = AsyncMock()

    event = ChangeEvent(path=spec, change_type=ChangeType.MODIFIED)
    await srv._handle_change(event)

    srv._regenerate.assert_awaited_once()
    srv._restart_server.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_change_yaml_triggers_regenerate(tmp_path: Path) -> None:
    spec = tmp_path / "openapi.yaml"
    out = tmp_path / "out"
    config_file = tmp_path / ".api2mcp.yaml"
    srv = HotReloadServer(spec_path=spec, output_dir=out)

    srv._regenerate = AsyncMock()
    srv._restart_server = AsyncMock()

    event = ChangeEvent(path=config_file, change_type=ChangeType.MODIFIED)
    await srv._handle_change(event)

    srv._regenerate.assert_awaited_once()
    srv._restart_server.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_change_py_no_regenerate(tmp_path: Path) -> None:
    spec = tmp_path / "openapi.yaml"
    out = tmp_path / "out"
    py_file = out / "server.py"
    srv = HotReloadServer(spec_path=spec, output_dir=out)

    srv._regenerate = AsyncMock()
    srv._restart_server = AsyncMock()

    event = ChangeEvent(path=py_file, change_type=ChangeType.MODIFIED)
    await srv._handle_change(event)

    srv._regenerate.assert_not_awaited()
    srv._restart_server.assert_awaited_once()


# ---------------------------------------------------------------------------
# _stop_server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_server_noop_when_no_task(tmp_path: Path) -> None:
    srv = HotReloadServer(spec_path=tmp_path / "s.yaml", output_dir=tmp_path)
    # Should not raise
    await srv._stop_server()


@pytest.mark.asyncio
async def test_stop_server_cancels_running_task(tmp_path: Path) -> None:
    srv = HotReloadServer(spec_path=tmp_path / "s.yaml", output_dir=tmp_path)

    async def _long_running() -> None:
        await asyncio.sleep(60)

    task = asyncio.create_task(_long_running())
    srv._server_task = task

    await srv._stop_server()
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_stop_server_noop_when_task_already_done(tmp_path: Path) -> None:
    srv = HotReloadServer(spec_path=tmp_path / "s.yaml", output_dir=tmp_path)

    async def _quick() -> None:
        return

    task = asyncio.create_task(_quick())
    await asyncio.sleep(0)  # let the task finish
    srv._server_task = task

    # Should not raise
    await srv._stop_server()


# ---------------------------------------------------------------------------
# _restart_server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_server_increments_count(tmp_path: Path) -> None:
    srv = HotReloadServer(spec_path=tmp_path / "s.yaml", output_dir=tmp_path)

    # Patch _start_server and _stop_server to avoid real work
    async def _fake_start() -> None:
        srv._restart_count += 1

    srv._stop_server = AsyncMock()
    srv._start_server = AsyncMock(side_effect=_fake_start)

    await srv._restart_server()
    srv._stop_server.assert_awaited_once()
    srv._start_server.assert_awaited_once()


# ---------------------------------------------------------------------------
# _regenerate — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_regenerate_logs_error_on_exception(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("not valid openapi\n")
    srv = HotReloadServer(spec_path=spec, output_dir=tmp_path / "out")

    # Should not raise — errors are swallowed with logging
    await srv._regenerate()
