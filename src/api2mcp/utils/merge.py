# SPDX-License-Identifier: MIT
"""Deep-merge utility for nested dicts."""
from __future__ import annotations
from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with *override* recursively merged into *base*.

    Does not mutate either input dict.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result
