# SPDX-License-Identifier: MIT
"""Exceptions for the concurrency layer."""

from __future__ import annotations


class ConcurrencyError(Exception):
    """Raised when the concurrency limit is exceeded and the queue times out.

    Args:
        message: Human-readable description.
        tool_name: The tool that triggered the limit.
        limit: The concurrency limit that was hit.
    """

    def __init__(
        self,
        message: str,
        *,
        tool_name: str = "",
        limit: int = 0,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.limit = limit
        self.code = "CONCURRENCY_LIMIT_EXCEEDED"
