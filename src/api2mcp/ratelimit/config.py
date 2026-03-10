# SPDX-License-Identifier: MIT
"""Per-endpoint rate limit configuration.

:class:`RateLimitConfig` is the top-level configuration object.  It holds a
*global* :class:`BucketConfig` (used as a fallback for all tool calls) and an
optional per-endpoint mapping that overrides the global default for specific
tools or endpoints.

Example::

    config = RateLimitConfig(
        global_bucket=BucketConfig(capacity=20, refill_rate=5),
        endpoint_buckets={
            "github:create_issue": BucketConfig(capacity=5, refill_rate=1),
        },
        max_retries=3,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BucketConfig:
    """Parameters for a single token bucket.

    Args:
        capacity: Maximum burst — the number of requests allowed immediately.
        refill_rate: Sustained request rate in tokens (requests) per second.
    """

    capacity: float = 10.0
    refill_rate: float = 1.0  # tokens / second

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError(f"BucketConfig.capacity must be > 0, got {self.capacity}")
        if self.refill_rate <= 0:
            raise ValueError(
                f"BucketConfig.refill_rate must be > 0, got {self.refill_rate}"
            )


@dataclass
class RateLimitConfig:
    """Master configuration for the rate limiting layer.

    Args:
        enabled: Master switch — set ``False`` to bypass rate limiting entirely.
        global_bucket: Fallback bucket applied to every tool unless overridden.
        endpoint_buckets: Per-tool overrides keyed by tool name (e.g.
            ``"github:list_issues"``).
        max_retries: How many times to retry a rate-limited request using
            exponential backoff before raising :class:`~.exceptions.RateLimitError`.
        raise_on_limit: If ``True``, raise on rate limit; if ``False``, return
            an error :class:`~mcp.types.TextContent` (MCP-friendly default).
    """

    enabled: bool = True
    global_bucket: BucketConfig = field(default_factory=BucketConfig)
    endpoint_buckets: dict[str, BucketConfig] = field(default_factory=dict)
    max_retries: int = 3
    raise_on_limit: bool = False

    def bucket_for(self, tool_name: str) -> BucketConfig:
        """Return the :class:`BucketConfig` applicable to *tool_name*.

        Looks up *tool_name* in :attr:`endpoint_buckets` first; falls back to
        :attr:`global_bucket`.
        """
        return self.endpoint_buckets.get(tool_name, self.global_bucket)
