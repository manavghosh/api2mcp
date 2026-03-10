# SPDX-License-Identifier: MIT
"""API spec diff — compare two sets of generated tools for breaking changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiffResult:
    """Result of comparing two API specs via their generated tools."""

    added: list[str] = field(default_factory=list)
    """Tool names present in the new spec but not the old."""

    removed: list[str] = field(default_factory=list)
    """Tool names present in the old spec but not the new — always breaking."""

    changed: list[str] = field(default_factory=list)
    """Tool names where parameters changed — potentially breaking."""

    @property
    def has_breaking_changes(self) -> bool:
        """True if any tools were removed or had parameter changes."""
        return bool(self.removed or self.changed)

    @property
    def exit_code(self) -> int:
        """Shell exit code: 1 if breaking changes found, 0 otherwise."""
        return 1 if self.has_breaking_changes else 0


def diff_specs(tools_a: list[Any], tools_b: list[Any]) -> DiffResult:
    """Compare two lists of tool definitions and return a DiffResult.

    Args:
        tools_a: Tools from the old/original spec.
        tools_b: Tools from the new/updated spec.

    Returns:
        :class:`DiffResult` describing added, removed, and changed tools.
    """
    map_a: dict[str, Any] = {t.name: t for t in tools_a}
    map_b: dict[str, Any] = {t.name: t for t in tools_b}

    added = sorted(n for n in map_b if n not in map_a)
    removed = sorted(n for n in map_a if n not in map_b)
    changed: list[str] = []

    for name in map_a:
        if name not in map_b:
            continue
        params_a = set(_get_params(map_a[name]))
        params_b = set(_get_params(map_b[name]))
        if params_a != params_b:
            changed.append(name)

    return DiffResult(added=added, removed=removed, changed=sorted(changed))


def _get_params(tool: Any) -> list[tuple[str, str, bool]]:
    """Extract (name, type, required) tuples from a tool definition."""
    params = getattr(tool, "parameters", None)
    if isinstance(params, dict):
        return [
            (
                name,
                str(info.get("type", "any") if isinstance(info, dict) else "any"),
                bool(info.get("required", False) if isinstance(info, dict) else False),
            )
            for name, info in params.items()
        ]
    if isinstance(params, list):
        result = []
        for p in params:
            if isinstance(p, dict):
                result.append((
                    p.get("name", str(p)),
                    str(p.get("type", "any")),
                    bool(p.get("required", False)),
                ))
            else:
                result.append((str(p), "any", False))
        return result
    return []
