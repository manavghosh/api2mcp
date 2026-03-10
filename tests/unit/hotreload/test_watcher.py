"""Unit tests for F6.2 FileWatcher — change detection and filtering."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api2mcp.hotreload.watcher import (
    DEFAULT_EXTENSIONS,
    ChangeEvent,
    ChangeType,
    FileWatcher,
)


# ---------------------------------------------------------------------------
# ChangeType / ChangeEvent
# ---------------------------------------------------------------------------


def test_change_type_values() -> None:
    assert ChangeType.ADDED.value == "added"
    assert ChangeType.MODIFIED.value == "modified"
    assert ChangeType.DELETED.value == "deleted"


def test_change_event_fields(tmp_path: Path) -> None:
    p = tmp_path / "spec.yaml"
    event = ChangeEvent(path=p, change_type=ChangeType.MODIFIED)
    assert event.path == p
    assert event.change_type == ChangeType.MODIFIED


# ---------------------------------------------------------------------------
# FileWatcher.__init__
# ---------------------------------------------------------------------------


def test_file_watcher_defaults() -> None:
    fw = FileWatcher()
    assert fw._extensions == DEFAULT_EXTENSIONS
    assert fw._extra_paths == set()
    assert fw._poll_interval_ms == 300


def test_file_watcher_custom_params(tmp_path: Path) -> None:
    fw = FileWatcher(
        paths=[tmp_path],
        extensions=frozenset({".yaml"}),
        extra_paths=[tmp_path / "extra.conf"],
        poll_interval_ms=100,
    )
    assert fw._poll_interval_ms == 100
    assert frozenset({".yaml"}) == fw._extensions
    assert (tmp_path / "extra.conf") in fw._extra_paths


def test_file_watcher_stop() -> None:
    fw = FileWatcher()
    assert not fw._stop_event.is_set()
    fw.stop()
    assert fw._stop_event.is_set()


# ---------------------------------------------------------------------------
# FileWatcher._should_report
# ---------------------------------------------------------------------------


def test_should_report_extension_match(tmp_path: Path) -> None:
    fw = FileWatcher()
    assert fw._should_report(tmp_path / "spec.yaml") is True
    assert fw._should_report(tmp_path / "server.py") is True
    assert fw._should_report(tmp_path / "data.json") is True


def test_should_report_extension_no_match(tmp_path: Path) -> None:
    fw = FileWatcher()
    assert fw._should_report(tmp_path / "image.png") is False
    assert fw._should_report(tmp_path / "readme.md") is False


def test_should_report_config_filename(tmp_path: Path) -> None:
    fw = FileWatcher()
    assert fw._should_report(tmp_path / ".api2mcp.yaml") is True
    assert fw._should_report(tmp_path / ".api2mcp.yml") is True


def test_should_report_extra_path(tmp_path: Path) -> None:
    extra = tmp_path / "custom.conf"
    fw = FileWatcher(extra_paths=[extra])
    # .conf is not in DEFAULT_EXTENSIONS, but it's in extra_paths
    assert fw._should_report(extra) is True


def test_should_report_case_insensitive_extension(tmp_path: Path) -> None:
    fw = FileWatcher()
    assert fw._should_report(tmp_path / "spec.YAML") is True
    assert fw._should_report(tmp_path / "spec.JSON") is True


# ---------------------------------------------------------------------------
# FileWatcher._map_change
# ---------------------------------------------------------------------------


def test_map_change_added() -> None:
    try:
        from watchfiles import Change  # type: ignore[import-not-found]
        assert FileWatcher._map_change(Change.added) == ChangeType.ADDED
    except ImportError:
        pytest.skip("watchfiles not installed")


def test_map_change_deleted() -> None:
    try:
        from watchfiles import Change  # type: ignore[import-not-found]
        assert FileWatcher._map_change(Change.deleted) == ChangeType.DELETED
    except ImportError:
        pytest.skip("watchfiles not installed")


def test_map_change_modified() -> None:
    try:
        from watchfiles import Change  # type: ignore[import-not-found]
        assert FileWatcher._map_change(Change.modified) == ChangeType.MODIFIED
    except ImportError:
        pytest.skip("watchfiles not installed")


def test_map_change_unknown_falls_back_to_modified() -> None:
    """Any unexpected value maps to MODIFIED."""
    result = FileWatcher._map_change("unknown_change_type")
    assert result == ChangeType.MODIFIED


# ---------------------------------------------------------------------------
# FileWatcher.watch — async generator with mocked awatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_yields_events_for_matching_files(tmp_path: Path) -> None:
    """Mock awatch to emit a YAML change and verify ChangeEvent is yielded."""
    spec_file = tmp_path / "openapi.yaml"

    try:
        from watchfiles import Change  # type: ignore[import-not-found]
        raw_change = Change.modified
    except ImportError:
        pytest.skip("watchfiles not installed")

    async def _fake_awatch(*args: object, **kwargs: object) -> AsyncIterator[set]:
        yield {(raw_change, str(spec_file))}

    fw = FileWatcher(paths=[tmp_path])

    with patch("watchfiles.awatch", _fake_awatch):
        events = []
        async for event in fw.watch():
            events.append(event)

    assert len(events) == 1
    assert events[0].path == spec_file
    assert events[0].change_type == ChangeType.MODIFIED


@pytest.mark.asyncio
async def test_watch_filters_irrelevant_files(tmp_path: Path) -> None:
    """Events for non-matching extensions are not yielded."""
    png_file = tmp_path / "image.png"

    try:
        from watchfiles import Change  # type: ignore[import-not-found]
        raw_change = Change.modified
    except ImportError:
        pytest.skip("watchfiles not installed")

    async def _fake_awatch(*args: object, **kwargs: object) -> AsyncIterator[set]:
        yield {(raw_change, str(png_file))}

    fw = FileWatcher(paths=[tmp_path])

    with patch("watchfiles.awatch", _fake_awatch):
        events = []
        async for event in fw.watch():
            events.append(event)

    assert events == []


@pytest.mark.asyncio
async def test_watch_raises_import_error_without_watchfiles() -> None:
    fw = FileWatcher()
    with patch.dict("sys.modules", {"watchfiles": None}):
        with pytest.raises(ImportError, match="watchfiles"):
            async for _ in fw.watch():
                pass


@pytest.mark.asyncio
async def test_watch_yields_multiple_events(tmp_path: Path) -> None:
    """Multiple file changes in one batch are all yielded."""
    file_a = tmp_path / "a.yaml"
    file_b = tmp_path / "b.py"

    try:
        from watchfiles import Change  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("watchfiles not installed")

    async def _fake_awatch(*args: object, **kwargs: object) -> AsyncIterator[set]:
        yield {(Change.modified, str(file_a)), (Change.added, str(file_b))}

    fw = FileWatcher(paths=[tmp_path])

    with patch("watchfiles.awatch", _fake_awatch):
        events = []
        async for event in fw.watch():
            events.append(event)

    assert len(events) == 2
    paths = {e.path for e in events}
    assert file_a in paths
    assert file_b in paths
