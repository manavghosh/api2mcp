# SPDX-License-Identifier: MIT
"""Circuit breaker configuration.

:class:`CircuitBreakerConfig` is the top-level configuration object.  It holds
a *global* :class:`EndpointConfig` (used as a fallback) and an optional
per-endpoint mapping that overrides the global default for specific tools.

Example::

    config = CircuitBreakerConfig(
        global_endpoint=EndpointConfig(failure_threshold=5, reset_timeout=30.0),
        endpoint_overrides={
            "github:create_issue": EndpointConfig(failure_threshold=3),
        },
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EndpointConfig:
    """Circuit breaker parameters for a single endpoint/tool.

    Args:
        failure_threshold: Number of consecutive failures before the circuit
            transitions from CLOSED to OPEN.
        reset_timeout: Seconds to remain OPEN before testing again (HALF_OPEN).
        half_open_max_calls: Maximum number of test calls allowed while
            HALF_OPEN before a decision is made.
    """

    failure_threshold: int = 5
    reset_timeout: float = 30.0  # seconds
    half_open_max_calls: int = 1

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError(
                f"EndpointConfig.failure_threshold must be >= 1, "
                f"got {self.failure_threshold}"
            )
        if self.reset_timeout <= 0:
            raise ValueError(
                f"EndpointConfig.reset_timeout must be > 0, got {self.reset_timeout}"
            )
        if self.half_open_max_calls < 1:
            raise ValueError(
                f"EndpointConfig.half_open_max_calls must be >= 1, "
                f"got {self.half_open_max_calls}"
            )


@dataclass
class CircuitBreakerConfig:
    """Master configuration for the circuit breaker layer.

    Args:
        enabled: Master switch — set ``False`` to bypass circuit breaking entirely.
        global_endpoint: Fallback config applied to every tool unless overridden.
        endpoint_overrides: Per-tool overrides keyed by tool name (e.g.
            ``"github:list_issues"``).
        raise_on_open: If ``True``, raise :class:`~.exceptions.CircuitBreakerError`
            when the circuit is open; if ``False``, return an MCP-friendly error
            TextContent (default).
    """

    enabled: bool = True
    global_endpoint: EndpointConfig = field(default_factory=EndpointConfig)
    endpoint_overrides: dict[str, EndpointConfig] = field(default_factory=dict)
    raise_on_open: bool = False

    def config_for(self, tool_name: str) -> EndpointConfig:
        """Return the :class:`EndpointConfig` applicable to *tool_name*.

        Looks up *tool_name* in :attr:`endpoint_overrides` first; falls back to
        :attr:`global_endpoint`.
        """
        return self.endpoint_overrides.get(tool_name, self.global_endpoint)
