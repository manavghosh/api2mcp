"""Unit tests for ConcurrencyConfig."""

from __future__ import annotations

import pytest

from api2mcp.concurrency.config import ConcurrencyConfig


class TestConcurrencyConfig:
    def test_defaults(self) -> None:
        c = ConcurrencyConfig()
        assert c.enabled is True
        assert c.max_concurrent == 50
        assert c.queue_timeout == pytest.approx(30.0)
        assert c.drain_timeout == pytest.approx(60.0)

    def test_invalid_max_concurrent(self) -> None:
        with pytest.raises(ValueError, match="max_concurrent"):
            ConcurrencyConfig(max_concurrent=0)

    def test_invalid_per_tool_limit(self) -> None:
        with pytest.raises(ValueError, match="per_tool_limits"):
            ConcurrencyConfig(per_tool_limits={"tool": 0})

    def test_limit_for_known_tool(self) -> None:
        c = ConcurrencyConfig(per_tool_limits={"write_tool": 3})
        assert c.limit_for("write_tool") == 3

    def test_limit_for_unknown_tool_falls_back(self) -> None:
        c = ConcurrencyConfig(max_concurrent=20)
        assert c.limit_for("unknown_tool") == 20

    def test_none_timeouts_allowed(self) -> None:
        c = ConcurrencyConfig(queue_timeout=None, drain_timeout=None)
        assert c.queue_timeout is None
        assert c.drain_timeout is None

    def test_disabled(self) -> None:
        c = ConcurrencyConfig(enabled=False)
        assert c.enabled is False
