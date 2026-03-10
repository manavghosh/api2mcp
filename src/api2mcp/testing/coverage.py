# SPDX-License-Identifier: MIT
"""Coverage reporting for MCP tool tests — F6.3.

Tracks which tools were called during a test session and reports coverage
as a percentage.  Integrates with :class:`~api2mcp.testing.client.MCPTestClient`
via the ``call_log``.

Usage::

    from api2mcp.testing.coverage import CoverageReporter

    reporter = CoverageReporter(tools)
    reporter.record_call("list_items")
    reporter.record_call("get_item")

    report = reporter.report()
    logger.info("%s", report.summary())
    assert report.percentage >= 80.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api2mcp.generators.tool import MCPToolDef
from api2mcp.testing.client import ToolResult

# ---------------------------------------------------------------------------
# CoverageReport
# ---------------------------------------------------------------------------


@dataclass
class CoverageReport:
    """Immutable snapshot of coverage at a point in time.

    Attributes:
        total_tools:   Total number of tools in the server.
        called_tools:  Set of tool names that were called at least once.
        uncalled_tools: Tools not yet covered.
        call_counts:   How many times each tool was called.
        percentage:    Coverage percentage (0–100).
    """

    total_tools: int
    called_tools: set[str]
    uncalled_tools: set[str]
    call_counts: dict[str, int]
    percentage: float

    def summary(self) -> str:
        """Return a human-readable one-line summary."""
        return (
            f"Tool coverage: {len(self.called_tools)}/{self.total_tools} "
            f"({self.percentage:.1f}%)"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (suitable for JSON output)."""
        return {
            "total_tools": self.total_tools,
            "called_tools": sorted(self.called_tools),
            "uncalled_tools": sorted(self.uncalled_tools),
            "call_counts": dict(sorted(self.call_counts.items())),
            "percentage": round(self.percentage, 2),
        }

    def assert_minimum(self, minimum: float) -> None:
        """Assert that coverage meets a minimum threshold.

        Args:
            minimum: Minimum required percentage (0–100).

        Raises:
            AssertionError: If coverage is below *minimum*.
        """
        if self.percentage < minimum:
            raise AssertionError(
                f"Coverage {self.percentage:.1f}% is below minimum {minimum:.1f}%.\n"
                f"Uncalled tools: {sorted(self.uncalled_tools)}"
            )


# ---------------------------------------------------------------------------
# CoverageReporter
# ---------------------------------------------------------------------------


class CoverageReporter:
    """Tracks and reports tool execution coverage.

    Args:
        tools: List of :class:`~api2mcp.generators.tool.MCPToolDef` objects
               from the server under test.
    """

    def __init__(self, tools: list[MCPToolDef]) -> None:
        self._all_tools: set[str] = {t.name for t in tools}
        self._call_counts: dict[str, int] = {t.name: 0 for t in tools}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_call(self, tool_name: str) -> None:
        """Record a single call to *tool_name*.

        Unknown tool names are silently ignored so the reporter can be used
        with partial tool sets.
        """
        if tool_name in self._call_counts:
            self._call_counts[tool_name] += 1

    def record_results(self, results: list[ToolResult]) -> None:
        """Bulk-record calls from a :attr:`~api2mcp.testing.client.MCPTestClient.call_log`.

        Args:
            results: List of :class:`~api2mcp.testing.client.ToolResult` objects.
        """
        for r in results:
            self.record_call(r.tool_name)

    def reset(self) -> None:
        """Reset all call counts to zero."""
        for name in self._call_counts:
            self._call_counts[name] = 0

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def report(self) -> CoverageReport:
        """Build and return a :class:`CoverageReport`.

        Returns:
            Snapshot of coverage at the time of the call.
        """
        called = {name for name, count in self._call_counts.items() if count > 0}
        uncalled = self._all_tools - called
        total = len(self._all_tools)
        pct = (len(called) / total * 100.0) if total > 0 else 100.0
        return CoverageReport(
            total_tools=total,
            called_tools=called,
            uncalled_tools=uncalled,
            call_counts=dict(self._call_counts),
            percentage=pct,
        )

    @classmethod
    def from_client(cls, client: Any) -> CoverageReporter:
        """Create a reporter pre-populated from a :class:`~api2mcp.testing.client.MCPTestClient`.

        Args:
            client: A loaded :class:`MCPTestClient` instance.

        Returns:
            :class:`CoverageReporter` with all calls already recorded.
        """
        reporter = cls(client.tools)
        reporter.record_results(client.call_log)
        return reporter
