"""Unit tests for F6.3 CoverageReporter and CoverageReport."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.testing.coverage import CoverageReporter
from api2mcp.generators.tool import MCPToolDef
from api2mcp.testing.client import ToolResult
from api2mcp.testing.mock_generator import MockScenario


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str) -> MCPToolDef:
    from api2mcp.core.ir_schema import Endpoint, HttpMethod
    endpoint = Endpoint(path=f"/{name}", method=HttpMethod.GET, operation_id=name)
    return MCPToolDef(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object", "properties": {}},
        endpoint=endpoint,
    )


def _make_result(tool_name: str) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        status="success",
        content={},
        status_code=200,
        scenario=MockScenario(name="success"),
    )


# ---------------------------------------------------------------------------
# CoverageReporter basics
# ---------------------------------------------------------------------------


def test_reporter_zero_coverage_initially() -> None:
    tools = [_make_tool("list_items"), _make_tool("get_item")]
    reporter = CoverageReporter(tools)
    report = reporter.report()
    assert report.percentage == 0.0
    assert report.total_tools == 2
    assert report.called_tools == set()
    assert report.uncalled_tools == {"list_items", "get_item"}


def test_reporter_full_coverage() -> None:
    tools = [_make_tool("list_items"), _make_tool("get_item")]
    reporter = CoverageReporter(tools)
    reporter.record_call("list_items")
    reporter.record_call("get_item")
    report = reporter.report()
    assert report.percentage == 100.0
    assert report.uncalled_tools == set()


def test_reporter_partial_coverage() -> None:
    tools = [_make_tool("a"), _make_tool("b"), _make_tool("c"), _make_tool("d")]
    reporter = CoverageReporter(tools)
    reporter.record_call("a")
    reporter.record_call("b")
    report = reporter.report()
    assert report.percentage == 50.0
    assert report.called_tools == {"a", "b"}
    assert report.uncalled_tools == {"c", "d"}


def test_reporter_ignores_unknown_tools() -> None:
    tools = [_make_tool("list_items")]
    reporter = CoverageReporter(tools)
    reporter.record_call("nonexistent_tool")   # should not raise
    report = reporter.report()
    assert report.percentage == 0.0


def test_reporter_counts_multiple_calls() -> None:
    tools = [_make_tool("list_items")]
    reporter = CoverageReporter(tools)
    reporter.record_call("list_items")
    reporter.record_call("list_items")
    reporter.record_call("list_items")
    report = reporter.report()
    assert report.call_counts["list_items"] == 3


def test_reporter_reset_clears_counts() -> None:
    tools = [_make_tool("list_items")]
    reporter = CoverageReporter(tools)
    reporter.record_call("list_items")
    reporter.reset()
    report = reporter.report()
    assert report.percentage == 0.0


def test_reporter_record_results_bulk() -> None:
    tools = [_make_tool("a"), _make_tool("b")]
    reporter = CoverageReporter(tools)
    results = [_make_result("a"), _make_result("b"), _make_result("a")]
    reporter.record_results(results)
    report = reporter.report()
    assert report.percentage == 100.0
    assert report.call_counts["a"] == 2
    assert report.call_counts["b"] == 1


def test_reporter_empty_tools_returns_100_percent() -> None:
    reporter = CoverageReporter([])
    report = reporter.report()
    assert report.percentage == 100.0


# ---------------------------------------------------------------------------
# CoverageReport
# ---------------------------------------------------------------------------


def test_report_summary_format() -> None:
    tools = [_make_tool("a"), _make_tool("b")]
    reporter = CoverageReporter(tools)
    reporter.record_call("a")
    report = reporter.report()
    summary = report.summary()
    assert "1/2" in summary
    assert "50.0%" in summary


def test_report_to_dict() -> None:
    tools = [_make_tool("a"), _make_tool("b")]
    reporter = CoverageReporter(tools)
    reporter.record_call("a")
    report = reporter.report()
    d = report.to_dict()
    assert d["total_tools"] == 2
    assert "a" in d["called_tools"]
    assert "b" in d["uncalled_tools"]
    assert d["percentage"] == 50.0


def test_report_assert_minimum_passes() -> None:
    tools = [_make_tool("a"), _make_tool("b")]
    reporter = CoverageReporter(tools)
    reporter.record_call("a")
    reporter.record_call("b")
    report = reporter.report()
    report.assert_minimum(80.0)   # 100% >= 80%, should pass


def test_report_assert_minimum_fails() -> None:
    tools = [_make_tool("a"), _make_tool("b")]
    reporter = CoverageReporter(tools)
    reporter.record_call("a")
    report = reporter.report()
    with pytest.raises(AssertionError, match="50.0%"):
        report.assert_minimum(80.0)


# ---------------------------------------------------------------------------
# CoverageReporter.from_client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reporter_from_client(tmp_path: Path) -> None:
    import yaml

    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Cov API", "version": "1.0.0"},
        "paths": {
            "/items": {"get": {"operationId": "listItems", "summary": "List", "responses": {"200": {"description": "OK"}}}},
            "/items/{id}": {"get": {"operationId": "getItem", "summary": "Get", "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}], "responses": {"200": {"description": "OK"}}}},
        },
    }
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(yaml.dump(spec))

    from api2mcp.testing.client import MCPTestClient

    async with MCPTestClient(server_dir=tmp_path) as client:
        tools = await client.list_tools()
        # call one tool
        await client.call_tool(tools[0]["name"])
        reporter = CoverageReporter.from_client(client)

    report = reporter.report()
    assert report.total_tools == 2
    assert report.percentage == 50.0
