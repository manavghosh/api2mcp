# SPDX-License-Identifier: MIT
"""Size-limit enforcement for tool call arguments.

Protects the MCP server from memory exhaustion caused by oversized inputs.
Limits are applied per-field (string length) and globally (total serialised
payload size).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from api2mcp.validation.exceptions import SizeExceededError


@dataclass
class SizeLimits:
    """Configurable size constraints.

    Args:
        max_string_length: Maximum characters allowed in any single string value.
        max_payload_bytes: Maximum total JSON-serialised payload size in bytes.
        max_array_items: Maximum number of elements in any array value.
        max_object_keys: Maximum number of keys in any object value.
    """

    max_string_length: int = 65_536       # 64 KiB
    max_payload_bytes: int = 1_048_576    # 1 MiB
    max_array_items: int = 1_000
    max_object_keys: int = 256


_DEFAULT_LIMITS = SizeLimits()


def check_payload_size(
    arguments: dict[str, Any],
    limits: SizeLimits = _DEFAULT_LIMITS,
) -> None:
    """Raise :class:`SizeExceededError` if the serialised payload is too large."""
    try:
        size = len(json.dumps(arguments, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        size = len(str(arguments).encode())

    if size > limits.max_payload_bytes:
        raise SizeExceededError(
            field="<payload>",
            actual=size,
            limit=limits.max_payload_bytes,
        )


def check_field_sizes(
    arguments: dict[str, Any],
    limits: SizeLimits = _DEFAULT_LIMITS,
) -> None:
    """Recursively check all string / array / object fields within *arguments*."""
    _check_value(arguments, path="<root>", limits=limits)


def _check_value(value: Any, path: str, limits: SizeLimits) -> None:
    if isinstance(value, str):
        if len(value) > limits.max_string_length:
            raise SizeExceededError(
                field=path,
                actual=len(value),
                limit=limits.max_string_length,
            )
    elif isinstance(value, list):
        if len(value) > limits.max_array_items:
            raise SizeExceededError(
                field=path,
                actual=len(value),
                limit=limits.max_array_items,
            )
        for i, item in enumerate(value):
            _check_value(item, f"{path}[{i}]", limits)
    elif isinstance(value, dict):
        if len(value) > limits.max_object_keys:
            raise SizeExceededError(
                field=path,
                actual=len(value),
                limit=limits.max_object_keys,
            )
        for k, v in value.items():
            _check_value(v, f"{path}.{k}", limits)
