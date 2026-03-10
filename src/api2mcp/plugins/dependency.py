# SPDX-License-Identifier: MIT
"""Dependency resolver for the plugin system (F7.2).

Topologically sorts plugins so that a plugin's dependencies are always
loaded before the plugin itself.

Usage::

    from api2mcp.plugins.dependency import resolve_load_order
    ordered = resolve_load_order(plugin_instances)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api2mcp.plugins.base import BasePlugin


class PluginDependencyError(Exception):
    """Raised when plugin dependencies cannot be satisfied."""


def resolve_load_order(plugins: list[BasePlugin]) -> list[BasePlugin]:
    """Return *plugins* sorted so dependencies come before dependents.

    Uses Kahn's algorithm (BFS topological sort).

    Args:
        plugins: List of :class:`~api2mcp.plugins.base.BasePlugin` instances.

    Returns:
        A new list with the same plugins in dependency-safe order.

    Raises:
        :class:`PluginDependencyError`:
            - If a plugin lists a dependency that is not in *plugins*.
            - If a circular dependency is detected.
    """
    id_to_plugin = {p.id: p for p in plugins}

    # Validate all dependencies are present
    for plugin in plugins:
        for dep_id in plugin.requires:
            if dep_id not in id_to_plugin:
                raise PluginDependencyError(
                    f"Plugin {plugin.id!r} requires {dep_id!r} which is not loaded."
                )

    # Build adjacency + in-degree
    in_degree: dict[str, int] = {p.id: 0 for p in plugins}
    dependents: dict[str, list[str]] = {p.id: [] for p in plugins}

    for plugin in plugins:
        for dep_id in plugin.requires:
            # dep_id must come before plugin.id
            dependents[dep_id].append(plugin.id)
            in_degree[plugin.id] += 1

    # Kahn's BFS
    queue = [pid for pid, deg in in_degree.items() if deg == 0]
    queue.sort()  # deterministic order for equal-priority plugins
    result: list[str] = []

    while queue:
        current = queue.pop(0)
        result.append(current)
        for dependent in sorted(dependents[current]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(plugins):
        # Cycle detected
        cycle_ids = {p.id for p in plugins} - set(result)
        raise PluginDependencyError(
            f"Circular dependency detected among plugins: {sorted(cycle_ids)}"
        )

    return [id_to_plugin[pid] for pid in result]
