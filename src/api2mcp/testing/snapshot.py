# SPDX-License-Identifier: MIT
"""Snapshot testing utilities for generated MCP server output — F6.3.

Captures the text output of :class:`~api2mcp.generators.tool.ToolGenerator`
(tool names, descriptions, input schemas) as JSON snapshots and detects
unintended changes across versions.

Usage::

    from api2mcp.testing.snapshot import SnapshotStore

    store = SnapshotStore(snapshot_dir=Path("tests/snapshots"))

    # First run (or after explicit update): writes snapshot
    store.assert_match("my_api_tools", tools)

    # Subsequent runs: compares against stored snapshot
    store.assert_match("my_api_tools", tools)

    # Update snapshots explicitly
    store.update("my_api_tools", tools)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api2mcp.generators.tool import MCPToolDef


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _tools_to_snapshot(tools: list[MCPToolDef]) -> dict[str, Any]:
    """Serialise a list of :class:`MCPToolDef` to a stable dict for snapshotting."""
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in sorted(tools, key=lambda t: t.name)
        ]
    }


def _normalise(data: Any) -> str:
    """Stable JSON string for comparison (sorted keys, 2-space indent)."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SnapshotMismatch
# ---------------------------------------------------------------------------


class SnapshotMismatch(AssertionError):
    """Raised when a snapshot comparison fails.

    Attributes:
        snapshot_name: The snapshot key that failed.
        expected:      The stored snapshot content.
        actual:        The freshly generated content.
        diff_hint:     A short human-readable diff summary.
    """

    def __init__(
        self,
        snapshot_name: str,
        expected: str,
        actual: str,
    ) -> None:
        self.snapshot_name = snapshot_name
        self.expected = expected
        self.actual = actual
        self.diff_hint = _diff_hint(expected, actual)
        super().__init__(
            f"Snapshot {snapshot_name!r} does not match.\n"
            f"Run with update=True to refresh.\n\n"
            f"{self.diff_hint}"
        )


def _diff_hint(expected: str, actual: str) -> str:
    """Return a short summary of the first differing line."""
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
        if e != a:
            return (
                f"First difference at line {i + 1}:\n"
                f"  expected: {e!r}\n"
                f"  actual:   {a!r}"
            )
    if len(exp_lines) != len(act_lines):
        return (
            f"Length mismatch: expected {len(exp_lines)} lines, "
            f"got {len(act_lines)} lines"
        )
    return "Content differs (no line-level diff found)"


# ---------------------------------------------------------------------------
# SnapshotStore
# ---------------------------------------------------------------------------


class SnapshotStore:
    """Manages snapshot files for generated MCP server output.

    Each snapshot is stored as a ``<name>.json`` file inside *snapshot_dir*.

    Args:
        snapshot_dir: Directory to read/write snapshot files.
                      Created automatically if it does not exist.
        update:       When ``True`` every :meth:`assert_match` call writes
                      the current output instead of comparing it.  Equivalent
                      to running tests with ``--snapshot-update``.
    """

    def __init__(
        self,
        snapshot_dir: str | Path = "tests/snapshots/data",
        *,
        update: bool = False,
    ) -> None:
        self.snapshot_dir = Path(snapshot_dir)
        self.update = update
        self._snapshot_dir_created = False

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def assert_match(
        self,
        name: str,
        tools: list[MCPToolDef],
        *,
        update: bool | None = None,
    ) -> None:
        """Assert that *tools* matches the stored snapshot named *name*.

        If no snapshot exists yet (first run), it is created automatically
        and the assertion passes.

        Args:
            name:   Snapshot identifier (used as filename stem).
            tools:  Tool definitions to snapshot.
            update: Override :attr:`update` for this call only.

        Raises:
            :class:`SnapshotMismatch`: When the current output differs from
                the stored snapshot and *update* is ``False``.
        """
        do_update = update if update is not None else self.update
        current = _normalise(_tools_to_snapshot(tools))
        snapshot_path = self._path(name)

        if do_update or not snapshot_path.exists():
            self._write(snapshot_path, current)
            return

        stored = snapshot_path.read_text(encoding="utf-8")
        if stored != current:
            raise SnapshotMismatch(name, stored, current)

    def save(self, name: str, tools: list[MCPToolDef]) -> None:
        """Unconditionally overwrite the snapshot for *name*.

        Args:
            name:  Snapshot identifier.
            tools: Tool definitions to snapshot.
        """
        current = _normalise(_tools_to_snapshot(tools))
        self._write(self._path(name), current)

    def load(self, name: str) -> dict[str, Any]:
        """Load and return the stored snapshot dict for *name*.

        Args:
            name: Snapshot identifier.

        Returns:
            Parsed snapshot dict.

        Raises:
            FileNotFoundError: If the snapshot does not exist.
        """
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot {name!r} not found at {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, name: str) -> bool:
        """Return ``True`` if a snapshot file exists for *name*."""
        return self._path(name).exists()

    def delete(self, name: str) -> None:
        """Delete the snapshot file for *name* (no-op if missing)."""
        path = self._path(name)
        if path.exists():
            path.unlink()

    def list_snapshots(self) -> list[str]:
        """Return the names of all snapshots stored in :attr:`snapshot_dir`."""
        if not self.snapshot_dir.is_dir():
            return []
        return sorted(p.stem for p in self.snapshot_dir.glob("*.json"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.snapshot_dir / f"{name}.json"

    def _write(self, path: Path, content: str) -> None:
        if not self._snapshot_dir_created:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            self._snapshot_dir_created = True
        path.write_text(content, encoding="utf-8")
