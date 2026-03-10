# SPDX-License-Identifier: MIT
"""File watcher for hot reload — F6.2.

Uses the ``watchfiles`` library to monitor spec files, generated server code,
and configuration files for changes.  Emits :class:`ChangeEvent` objects on
the async generator returned by :meth:`FileWatcher.watch`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ChangeType(str, Enum):
    """Kind of filesystem change detected."""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class ChangeEvent:
    """A single filesystem change notification.

    Attributes:
        path:        The file that changed.
        change_type: The kind of change (:class:`ChangeType`).
    """
    path: Path
    change_type: ChangeType


# ---------------------------------------------------------------------------
# Default patterns
# ---------------------------------------------------------------------------

#: File extensions watched by default.
DEFAULT_EXTENSIONS: frozenset[str] = frozenset({
    ".yaml", ".yml", ".json",  # spec / config
    ".py",                      # generated / user code
    ".toml",                    # pyproject.toml
})

#: Config file names always watched.
CONFIG_FILENAMES: frozenset[str] = frozenset({
    ".api2mcp.yaml",
    ".api2mcp.yml",
})


# ---------------------------------------------------------------------------
# FileWatcher
# ---------------------------------------------------------------------------


class FileWatcher:
    """Asynchronous file watcher for hot reload.

    Wraps ``watchfiles.awatch`` to provide a unified stream of
    :class:`ChangeEvent` objects.  The watcher filters events to only report
    files matching :attr:`extensions` or :attr:`extra_paths`.

    Args:
        paths:      Directories or files to watch.  Defaults to the current
                    working directory.
        extensions: File extensions to report (include the dot).  Defaults
                    to :data:`DEFAULT_EXTENSIONS`.
        extra_paths: Additional specific file paths to always report changes
                     for (e.g. ``".api2mcp.yaml"``).
        poll_interval_ms: How often the underlying watcher checks for changes,
                          in milliseconds.  Defaults to 300 ms.

    Usage::

        watcher = FileWatcher(paths=["./generated", "."])
        async for event in watcher.watch():
            logger.debug("Change event: %s %s", event.change_type, event.path)
            if event.path.suffix == ".yaml":
                await restart_server()
    """

    def __init__(
        self,
        paths: Iterable[str | Path] | None = None,
        *,
        extensions: frozenset[str] | None = None,
        extra_paths: Iterable[str | Path] | None = None,
        poll_interval_ms: int = 300,
    ) -> None:
        self._paths: list[Path] = [
            Path(p) for p in (paths or [Path.cwd()])
        ]
        self._extensions: frozenset[str] = extensions or DEFAULT_EXTENSIONS
        self._extra_paths: set[Path] = {
            Path(p) for p in (extra_paths or [])
        }
        self._poll_interval_ms = poll_interval_ms
        self._stop_event: asyncio.Event = asyncio.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the watcher to stop on next iteration."""
        self._stop_event.set()

    async def watch(self) -> AsyncIterator[ChangeEvent]:
        """Yield :class:`ChangeEvent` objects as files change.

        The generator runs until :meth:`stop` is called or the task is
        cancelled.

        Yields:
            :class:`ChangeEvent` for each relevant file change.
        """
        try:
            from watchfiles import awatch  # type: ignore[import-not-found]
        except ImportError as err:  # pragma: no cover
            raise ImportError(
                "The 'watchfiles' package is required for hot reload. "
                "Install it with: pip install watchfiles"
            ) from err

        watch_targets = [str(p) for p in self._paths]
        logger.info("FileWatcher: watching %s (extensions=%s)", watch_targets, self._extensions)

        async for changes in awatch(
            *watch_targets,
            poll_delay_ms=self._poll_interval_ms,
            stop_event=self._stop_event,
        ):
            for change, raw_path in changes:
                path = Path(raw_path)
                if not self._should_report(path):
                    continue
                change_type = self._map_change(change)
                event = ChangeEvent(path=path, change_type=change_type)
                logger.debug("FileWatcher: %s %s", change_type, path)
                yield event

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_report(self, path: Path) -> bool:
        """Return ``True`` if *path* should trigger a reload notification."""
        if path in self._extra_paths:
            return True
        if path.name in CONFIG_FILENAMES:
            return True
        return path.suffix.lower() in self._extensions

    @staticmethod
    def _map_change(change: object) -> ChangeType:
        """Map a ``watchfiles.Change`` enum value to :class:`ChangeType`."""
        try:
            from watchfiles import Change  # type: ignore[import-not-found]
            if change == Change.added:
                return ChangeType.ADDED
            if change == Change.deleted:
                return ChangeType.DELETED
        except ImportError as exc:
            logger.debug("Watcher change map error: %s", exc)
        return ChangeType.MODIFIED
