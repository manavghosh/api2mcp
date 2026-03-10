# SPDX-License-Identifier: MIT
"""Tool naming convention for MCP tool generation (TASK-012).

Derives MCP tool names from IR endpoints:
- Prefers operation_id when available
- Falls back to {method}_{path_segments} pattern
- Ensures uniqueness via collision resolution
"""

from __future__ import annotations

import re

from api2mcp.core.ir_schema import Endpoint


def sanitize_name(raw: str) -> str:
    """Sanitize a string for use as an MCP tool name.

    Rules:
    - Lowercase
    - Replace non-alphanumeric with underscore
    - Collapse multiple underscores
    - Strip leading/trailing underscores
    """
    name = raw.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    return name


def _path_to_segments(path: str) -> str:
    """Convert URL path to underscore-separated segments.

    Strips braces from path parameters:
        /pets/{petId}/toys -> pets_petId_toys
    """
    # Remove leading slash
    path = path.lstrip("/")
    # Remove braces from path params but keep the name
    path = re.sub(r"\{(\w+)\}", r"\1", path)
    # Replace slashes with underscores
    return path.replace("/", "_")


def derive_tool_name(endpoint: Endpoint) -> str:
    """Derive a tool name from an endpoint.

    Prefers operation_id when present and non-empty.
    Falls back to {method}_{path_segments}.
    """
    if endpoint.operation_id:
        return sanitize_name(endpoint.operation_id)

    method = endpoint.method.value.lower()
    segments = _path_to_segments(endpoint.path)
    return sanitize_name(f"{method}_{segments}")


def resolve_collisions(endpoints: list[Endpoint]) -> dict[str, str]:
    """Generate unique tool names for a list of endpoints.

    Returns:
        Mapping of endpoint identifier (operation_id or method+path) -> unique tool name.
        Keys use the format "METHOD path" for endpoints without operation_id.
    """
    # First pass: derive candidate names
    candidates: list[tuple[str, str]] = []  # (endpoint_key, candidate_name)
    for ep in endpoints:
        name = derive_tool_name(ep)
        key = ep.operation_id or f"{ep.method.value} {ep.path}"
        candidates.append((key, name))

    # Second pass: detect collisions and resolve
    name_counts: dict[str, int] = {}
    for _, name in candidates:
        name_counts[name] = name_counts.get(name, 0) + 1

    result: dict[str, str] = {}
    seen: dict[str, int] = {}
    for key, name in candidates:
        if name_counts[name] > 1:
            seen[name] = seen.get(name, 0) + 1
            suffix = seen[name]
            unique_name = f"{name}_{suffix}" if suffix > 1 else name
            # Check if even the suffixed name collides (unlikely but safe)
            while unique_name in result.values():
                suffix += 1
                unique_name = f"{name}_{suffix}"
            result[key] = unique_name
        else:
            result[key] = name

    return result
