# SPDX-License-Identifier: MIT
"""Shared utility helpers for API2MCP."""
from __future__ import annotations

from api2mcp.utils.timestamps import utcnow_iso, utcnow
from api2mcp.utils.merge import deep_merge
from api2mcp.utils.serialization import safe_yaml_load, safe_yaml_load_path, safe_json_load

__all__ = [
    "utcnow_iso",
    "utcnow",
    "deep_merge",
    "safe_yaml_load",
    "safe_yaml_load_path",
    "safe_json_load",
]
