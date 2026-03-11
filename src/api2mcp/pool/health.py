# SPDX-License-Identifier: MIT
"""Connection pool health checker.

:class:`PoolHealthChecker` sends lightweight HTTP probe requests to each
registered host and records the outcome.  Probes are throttled by
:attr:`~.config.HealthCheckConfig.interval` to avoid hammering the upstream
APIs with health-check traffic.

Health status is reported per-host and aggregated into an overall pool status
that callers can query at any time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from api2mcp.pool.config import HealthCheckConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class HostHealth:
    """Health record for a single host.

    Args:
        base_url: The host base URL (e.g. ``https://api.github.com``).
        healthy: Whether the last probe succeeded.
        last_checked: Monotonic timestamp of the last probe attempt.
        last_error: Error message from the last failed probe, or ``None``.
        probe_count: Total number of probes performed.
        fail_count: Number of consecutive failures.
    """

    base_url: str
    healthy: bool = True
    last_checked: float = float("-inf")  # sentinel: never probed
    last_error: str | None = None
    probe_count: int = 0
    fail_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "healthy": self.healthy,
            "last_checked": self.last_checked,
            "last_error": self.last_error,
            "probe_count": self.probe_count,
            "fail_count": self.fail_count,
        }


@dataclass
class PoolHealthStatus:
    """Aggregated health status for the entire pool.

    Args:
        overall_healthy: ``True`` if all hosts are healthy.
        hosts: Per-host health records.
        total_hosts: Number of registered hosts.
        healthy_hosts: Number of currently healthy hosts.
    """

    overall_healthy: bool
    hosts: dict[str, HostHealth] = field(default_factory=dict)
    total_hosts: int = 0
    healthy_hosts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_healthy": self.overall_healthy,
            "total_hosts": self.total_hosts,
            "healthy_hosts": self.healthy_hosts,
            "hosts": {url: h.to_dict() for url, h in self.hosts.items()},
        }


# ---------------------------------------------------------------------------
# Health checker
# ---------------------------------------------------------------------------


class PoolHealthChecker:
    """Manages health-check probes for all pooled hosts.

    Args:
        config: Health check configuration.
        clock: Monotonic clock function (injectable for tests).
    """

    def __init__(
        self,
        config: HealthCheckConfig | None = None,
        clock: Any = None,
    ) -> None:
        self._config = config or HealthCheckConfig()
        self._clock: Any = clock or time.monotonic
        self._records: dict[str, HostHealth] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, base_url: str) -> None:
        """Register a host for health monitoring."""
        if base_url not in self._records:
            self._records[base_url] = HostHealth(base_url=base_url)

    def unregister(self, base_url: str) -> None:
        """Remove a host from health monitoring."""
        self._records.pop(base_url, None)

    def status(self) -> PoolHealthStatus:
        """Return a snapshot of current pool health."""
        hosts = dict(self._records)
        healthy_count = sum(1 for h in hosts.values() if h.healthy)
        return PoolHealthStatus(
            overall_healthy=all(h.healthy for h in hosts.values()),
            hosts=hosts,
            total_hosts=len(hosts),
            healthy_hosts=healthy_count,
        )

    def is_healthy(self, base_url: str) -> bool:
        """Return ``True`` if *base_url* is currently considered healthy."""
        record = self._records.get(base_url)
        return record.healthy if record is not None else True

    async def probe(self, base_url: str, client: httpx.AsyncClient) -> bool:
        """Probe *base_url* if the check interval has elapsed.

        Uses *client* (from the pool) so no extra connection is opened.

        Args:
            base_url: Host base URL to probe.
            client: The pooled :class:`httpx.AsyncClient` for that host.

        Returns:
            ``True`` if the host is healthy, ``False`` otherwise.
        """
        if not self._config.enabled:
            return True

        async with self._lock:
            record = self._records.setdefault(base_url, HostHealth(base_url=base_url))
            now = self._clock()
            if now - record.last_checked < self._config.interval:
                return record.healthy

        # Probe outside the lock (may take time)
        probe_url = base_url.rstrip("/") + self._config.path
        healthy = False
        error_msg: str | None = None

        try:
            response = await asyncio.wait_for(
                client.get(probe_url, follow_redirects=True),
                timeout=self._config.timeout,
            )
            healthy = response.status_code in self._config.expected_status_codes
            if not healthy:
                error_msg = f"Unexpected status {response.status_code}"
        except TimeoutError:
            error_msg = f"Probe timed out after {self._config.timeout}s"
        except httpx.RequestError as exc:
            error_msg = str(exc)
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)

        async with self._lock:
            record = self._records.setdefault(base_url, HostHealth(base_url=base_url))
            record.probe_count += 1
            record.last_checked = self._clock()
            if healthy:
                record.healthy = True
                record.fail_count = 0
                record.last_error = None
                logger.debug("Health check OK for %s", base_url)
            else:
                record.fail_count += 1
                record.healthy = False
                record.last_error = error_msg
                logger.warning(
                    "Health check FAILED for %s: %s (fail_count=%d)",
                    base_url, error_msg, record.fail_count,
                )

        return healthy

    async def probe_all(self, clients: dict[str, httpx.AsyncClient]) -> PoolHealthStatus:
        """Probe all registered hosts using their pooled clients.

        Args:
            clients: Mapping of base_url → :class:`httpx.AsyncClient`.

        Returns:
            Aggregated :class:`PoolHealthStatus`.
        """
        tasks = [
            self.probe(url, client)
            for url, client in clients.items()
            if url in self._records
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return self.status()
