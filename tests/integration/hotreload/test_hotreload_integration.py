"""Integration tests for F6.2 hot reload — file change detection and reload cycle."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from api2mcp.hotreload.restart import HotReloadServer
from api2mcp.hotreload.watcher import ChangeEvent, ChangeType, FileWatcher

# ---------------------------------------------------------------------------
# Shared spec fixture
# ---------------------------------------------------------------------------

_MINIMAL_SPEC: dict = {
    "openapi": "3.0.3",
    "info": {"title": "HotReload API", "version": "1.0.0"},
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "summary": "List items",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


@pytest.fixture()
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "openapi.yaml"
    path.write_text(yaml.dump(_MINIMAL_SPEC), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# FileWatcher — real filesystem changes (requires watchfiles)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_watcher_detects_file_creation(tmp_path: Path) -> None:
    """FileWatcher yields an event when a new YAML file is created."""
    try:
        import watchfiles  # noqa: F401  type: ignore[import-not-found]
    except ImportError:
        pytest.skip("watchfiles not installed")

    fw = FileWatcher(paths=[tmp_path], poll_interval_ms=50)
    new_file = tmp_path / "new_spec.yaml"

    events: list[ChangeEvent] = []

    async def _create_file() -> None:
        await asyncio.sleep(0.2)
        new_file.write_text("openapi: 3.0.0\n", encoding="utf-8")
        await asyncio.sleep(0.3)
        fw.stop()

    async def _collect_events() -> None:
        async for event in fw.watch():
            events.append(event)

    await asyncio.gather(_create_file(), _collect_events())

    assert any(e.path == new_file for e in events)
    assert any(e.change_type in (ChangeType.ADDED, ChangeType.MODIFIED) for e in events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_watcher_detects_file_modification(tmp_path: Path) -> None:
    """FileWatcher yields an event when an existing file is modified."""
    try:
        import watchfiles  # noqa: F401  type: ignore[import-not-found]
    except ImportError:
        pytest.skip("watchfiles not installed")

    existing = tmp_path / "openapi.yaml"
    existing.write_text("openapi: 3.0.0\n", encoding="utf-8")

    fw = FileWatcher(paths=[tmp_path], poll_interval_ms=50)
    events: list[ChangeEvent] = []

    async def _modify_file() -> None:
        await asyncio.sleep(0.2)
        existing.write_text("openapi: 3.0.1\n", encoding="utf-8")
        await asyncio.sleep(0.3)
        fw.stop()

    async def _collect_events() -> None:
        async for event in fw.watch():
            events.append(event)

    await asyncio.gather(_modify_file(), _collect_events())

    assert any(e.path == existing for e in events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_watcher_ignores_non_matching_files(tmp_path: Path) -> None:
    """FileWatcher does not yield events for .png or .md files."""
    try:
        import watchfiles  # noqa: F401  type: ignore[import-not-found]
    except ImportError:
        pytest.skip("watchfiles not installed")

    fw = FileWatcher(paths=[tmp_path], poll_interval_ms=50)
    events: list[ChangeEvent] = []

    async def _create_noise() -> None:
        await asyncio.sleep(0.15)
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "README.md").write_text("# README\n")
        await asyncio.sleep(0.35)
        fw.stop()

    async def _collect_events() -> None:
        async for event in fw.watch():
            events.append(event)

    await asyncio.gather(_create_noise(), _collect_events())

    assert events == []


# ---------------------------------------------------------------------------
# HotReloadServer — reload cycle with mocked server
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hot_reload_server_restarts_on_spec_change(
    spec_file: Path, tmp_path: Path
) -> None:
    """HotReloadServer calls _handle_change when FileWatcher emits events."""
    srv = HotReloadServer(
        spec_path=spec_file,
        output_dir=tmp_path / "out",
        poll_interval_ms=50,
    )

    handled: list[ChangeEvent] = []

    async def _tracked_handle(event: ChangeEvent) -> None:
        handled.append(event)
        raise asyncio.CancelledError  # stop after first event

    srv._handle_change = _tracked_handle  # type: ignore[method-assign]

    modified_event = ChangeEvent(path=spec_file, change_type=ChangeType.MODIFIED)

    async def _fake_watch(self_: object) -> AsyncIterator[ChangeEvent]:
        await asyncio.sleep(0.05)
        yield modified_event
        await asyncio.sleep(60)

    with patch.object(FileWatcher, "watch", _fake_watch):
        with patch.object(srv, "_start_server", new_callable=AsyncMock):
            try:
                await asyncio.wait_for(srv.run(), timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

    assert len(handled) == 1
    assert handled[0].path == spec_file


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hot_reload_server_regenerate_on_spec_change(
    spec_file: Path, tmp_path: Path
) -> None:
    """_regenerate parses the spec and writes server files."""
    out = tmp_path / "out"
    srv = HotReloadServer(spec_path=spec_file, output_dir=out)

    await srv._regenerate()

    # After successful regeneration, output files should exist
    assert (out / "server.py").exists()
    assert (out / "spec.yaml").exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hot_reload_server_regenerate_tolerates_bad_spec(
    tmp_path: Path,
) -> None:
    """_regenerate logs an error but does not raise for invalid specs."""
    bad_spec = tmp_path / "bad.yaml"
    bad_spec.write_text("not: valid: openapi\n", encoding="utf-8")
    srv = HotReloadServer(spec_path=bad_spec, output_dir=tmp_path / "out")

    # Should not raise
    await srv._regenerate()


@pytest.mark.integration
def test_serve_cmd_watch_flag_help() -> None:
    """The --watch flag is exposed in the serve command help."""
    from click.testing import CliRunner

    from api2mcp.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--watch" in result.output or "-w" in result.output
