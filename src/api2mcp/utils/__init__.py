# SPDX-License-Identifier: MIT
"""Shared utility helpers for API2MCP."""
from __future__ import annotations

from api2mcp.utils.merge import deep_merge
from api2mcp.utils.serialization import (
    safe_json_load,
    safe_yaml_load,
    safe_yaml_load_path,
)
from api2mcp.utils.timestamps import utcnow, utcnow_iso

__all__ = [
    "utcnow_iso",
    "utcnow",
    "deep_merge",
    "safe_yaml_load",
    "safe_yaml_load_path",
    "safe_json_load",
]
