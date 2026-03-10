"""Integration tests for F6.3 Testing Framework — full generate→test→report flow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from api2mcp.testing import (
    CoverageReporter,
    MCPTestClient,
    MockResponseGenerator,
    SnapshotStore,
)

# ---------------------------------------------------------------------------
# Shared spec fixtures
# ---------------------------------------------------------------------------

_SPEC_WITH_CRUD: dict = {
    "openapi": "3.0.3",
    "info": {"title": "CRUD API", "version": "1.0.0"},
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "summary": "List all items",
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createItem",
                "summary": "Create item",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/items/{id}": {
            "get": {
                "operationId": "getItem",
                "summary": "Get item by ID",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "OK"}, "404": {"description": "Not found"}},
            },
            "delete": {
                "operationId": "deleteItem",
                "summary": "Delete item",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"204": {"description": "Deleted"}},
            },
        },
    },
}


@pytest.fixture()
def spec_dir(tmp_path: Path) -> Path:
    (tmp_path / "openapi.yaml").write_text(yaml.dump(_SPEC_WITH_CRUD), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# MCPTestClient
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_lists_all_tools(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir) as client:
        tools = await client.list_tools()
    assert len(tools) == 4
    names = {t["name"] for t in tools}
    assert len(names) == 4  # all unique


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_call_tool_success(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir, seed=42) as client:
        tools = await client.list_tools()
        list_tool = next(t for t in tools if "list" in t["name"].lower() or "items" in t["name"])
        result = await client.call_tool(list_tool["name"])
    assert result.status == "success"
    assert result.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_call_tool_records_to_log(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir) as client:
        tools = await client.list_tools()
        # Pick a tool with no required arguments
        tool_name = next(
            t["name"] for t in tools
            if not t.get("inputSchema", {}).get("required")
        )
        await client.call_tool(tool_name)
        await client.call_tool(tool_name)
        log = client.call_log
    assert len(log) == 2
    assert all(r.tool_name == tool_name for r in log)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_call_unknown_tool_raises(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir) as client:
        with pytest.raises(KeyError, match="no_such_tool"):
            await client.call_tool("no_such_tool")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_call_error_scenario(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir) as client:
        tools = await client.list_tools()
        # Use "unauthorized" scenario for a tool with no required args
        no_required = next(
            t["name"] for t in tools
            if not t.get("inputSchema", {}).get("required")
        )
        result = await client.call_tool(no_required, scenario="unauthorized")
    assert result.status == "error"
    assert result.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_validates_required_arguments(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir) as client:
        tools = await client.list_tools()
        # Find a tool with a required path param
        path_tool = next(
            (t for t in tools if "id" in str(t.get("inputSchema", {}).get("required", []))),
            None,
        )
        if path_tool:
            with pytest.raises(ValueError, match="id"):
                await client.call_tool(path_tool["name"], {})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_missing_spec_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        async with MCPTestClient(server_dir=tmp_path) as _client:
            pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_client_without_context_manager_raises(spec_dir: Path) -> None:
    client = MCPTestClient(server_dir=spec_dir)
    with pytest.raises(RuntimeError, match="async with"):
        await client.list_tools()


# ---------------------------------------------------------------------------
# Full flow: generate → test → coverage report
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_flow_generate_test_report(spec_dir: Path) -> None:
    """Exercise every tool and verify 100% coverage."""
    async with MCPTestClient(server_dir=spec_dir, seed=0) as client:
        tools = await client.list_tools()
        for tool in tools:
            args: dict = {}
            required = tool.get("inputSchema", {}).get("required", [])
            for req in required:
                args[req] = 1  # placeholder value
            await client.call_tool(tool["name"], args)

        reporter = CoverageReporter.from_client(client)

    report = reporter.report()
    assert report.percentage == 100.0
    report.assert_minimum(100.0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coverage_partial_flow(spec_dir: Path) -> None:
    """Calling only some tools produces partial coverage."""
    async with MCPTestClient(server_dir=spec_dir) as client:
        tools = await client.list_tools()
        # Call only a tool with no required args
        no_required = next(
            t["name"] for t in tools
            if not t.get("inputSchema", {}).get("required")
        )
        await client.call_tool(no_required)
        reporter = CoverageReporter.from_client(client)

    report = reporter.report()
    assert 0 < report.percentage < 100.0
    assert len(report.uncalled_tools) > 0


# ---------------------------------------------------------------------------
# Snapshot testing
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshot_first_run_creates_file(spec_dir: Path, tmp_path: Path) -> None:
    snap_dir = tmp_path / "snapshots"
    store = SnapshotStore(snapshot_dir=snap_dir)

    async with MCPTestClient(server_dir=spec_dir) as client:
        _tools_raw = await client.list_tools()
        tools = client.tools

    store.assert_match("crud_api", tools)
    assert store.exists("crud_api")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshot_stable_across_runs(spec_dir: Path, tmp_path: Path) -> None:
    store = SnapshotStore(snapshot_dir=tmp_path / "snapshots")

    async with MCPTestClient(server_dir=spec_dir) as client:
        tools = client.tools

    store.assert_match("stable", tools)   # create
    store.assert_match("stable", tools)   # compare — should pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshot_detects_change(spec_dir: Path, tmp_path: Path) -> None:
    from api2mcp.testing.snapshot import SnapshotMismatch

    store = SnapshotStore(snapshot_dir=tmp_path / "snapshots")

    async with MCPTestClient(server_dir=spec_dir) as client:
        tools_v1 = client.tools

    # Mutate tool description to simulate a change
    import dataclasses

    tools_v2 = [
        dataclasses.replace(t, description="Changed description")
        for t in tools_v1
    ]

    store.assert_match("detect_change", tools_v1)
    with pytest.raises(SnapshotMismatch):
        store.assert_match("detect_change", tools_v2)


# ---------------------------------------------------------------------------
# MockResponseGenerator via client
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mock_generator_all_scenarios(spec_dir: Path) -> None:
    async with MCPTestClient(server_dir=spec_dir) as client:
        spec = client.api_spec
    gen = MockResponseGenerator(spec, seed=1)
    all_s = gen.all_scenarios()
    assert len(all_s) == 4  # 4 endpoints
    for _tool_name, scenarios in all_s.items():
        assert len(scenarios) >= 2  # at least success + unauthorized
        assert any(s.status_code == 200 for s in scenarios)
