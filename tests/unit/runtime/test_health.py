"""Unit tests for health check support (TASK-028)."""

from api2mcp.runtime.health import HealthChecker, HealthStatus


class TestHealthStatus:
    def test_to_dict(self) -> None:
        status = HealthStatus(
            status="healthy",
            server_name="test_server",
            uptime_seconds=42.5,
            tool_count=3,
        )
        d = status.to_dict()
        assert d["status"] == "healthy"
        assert d["server"] == "test_server"
        assert d["uptime_seconds"] == 42.5
        assert d["tool_count"] == 3

    def test_to_dict_with_extra(self) -> None:
        status = HealthStatus(
            status="unhealthy",
            server_name="test",
            uptime_seconds=0.0,
            tool_count=0,
            extra={"reason": "db down"},
        )
        d = status.to_dict()
        assert d["reason"] == "db down"

    def test_to_dict_without_extra(self) -> None:
        status = HealthStatus(
            status="healthy",
            server_name="test",
            uptime_seconds=1.0,
            tool_count=1,
        )
        d = status.to_dict()
        assert "reason" not in d


class TestHealthChecker:
    def test_starts_healthy(self) -> None:
        checker = HealthChecker("my_server", tool_count=5)
        status = checker.check()
        assert status.status == "healthy"
        assert status.server_name == "my_server"
        assert status.tool_count == 5

    def test_uptime_increases(self) -> None:
        checker = HealthChecker("test")
        s1 = checker.check()
        s2 = checker.check()
        assert s2.uptime_seconds >= s1.uptime_seconds

    def test_mark_unhealthy(self) -> None:
        checker = HealthChecker("test")
        checker.mark_unhealthy("something broke")
        status = checker.check()
        assert status.status == "unhealthy"
        assert status.extra is not None
        assert status.extra["reason"] == "something broke"

    def test_mark_healthy_again(self) -> None:
        checker = HealthChecker("test")
        checker.mark_unhealthy("err")
        checker.mark_healthy()
        status = checker.check()
        assert status.status == "healthy"
