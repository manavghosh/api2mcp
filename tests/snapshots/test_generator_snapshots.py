"""Snapshot tests for generator output stability (TASK-020).

Ensures generated tool definitions and server code remain stable across
generator versions. If output changes intentionally, update snapshots
by running: pytest --snapshot-update
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api2mcp.core.ir_schema import (
    APISpec,
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    RequestBody,
    Response,
    SchemaRef,
    SchemaType,
    ServerInfo,
)
from api2mcp.generators.tool import ToolGenerator

SNAPSHOT_DIR = Path(__file__).parent / "data"


def _canonical_spec() -> APISpec:
    """A fixed API spec used for snapshot comparison."""
    return APISpec(
        title="SnapshotAPI",
        version="1.0.0",
        description="API used for snapshot testing",
        base_url="https://api.example.com/v1",
        servers=[ServerInfo(url="https://api.example.com/v1")],
        source_format="openapi3.0",
        endpoints=[
            Endpoint(
                path="/items",
                method=HttpMethod.GET,
                operation_id="listItems",
                summary="List items",
                parameters=[
                    Parameter(
                        name="page",
                        location=ParameterLocation.QUERY,
                        schema=SchemaRef(type=SchemaType.INTEGER, minimum=1),
                        required=False,
                        description="Page number",
                    ),
                    Parameter(
                        name="size",
                        location=ParameterLocation.QUERY,
                        schema=SchemaRef(type=SchemaType.INTEGER, minimum=1, maximum=100),
                        required=False,
                        description="Page size",
                    ),
                ],
                responses=[
                    Response(status_code="200", description="List of items"),
                ],
            ),
            Endpoint(
                path="/items",
                method=HttpMethod.POST,
                operation_id="createItem",
                summary="Create an item",
                request_body=RequestBody(
                    content_type="application/json",
                    schema=SchemaRef(
                        type=SchemaType.OBJECT,
                        properties={
                            "name": SchemaRef(type=SchemaType.STRING, description="Item name"),
                            "value": SchemaRef(type=SchemaType.NUMBER, description="Item value"),
                        },
                        required=["name"],
                    ),
                    required=True,
                ),
                responses=[
                    Response(status_code="201", description="Created"),
                ],
            ),
            Endpoint(
                path="/items/{itemId}",
                method=HttpMethod.GET,
                operation_id="getItem",
                summary="Get an item by ID",
                parameters=[
                    Parameter(
                        name="itemId",
                        location=ParameterLocation.PATH,
                        schema=SchemaRef(type=SchemaType.STRING),
                        required=True,
                        description="The item ID",
                    ),
                ],
                responses=[
                    Response(status_code="200", description="The item"),
                ],
            ),
        ],
    )


class TestToolDefinitionSnapshots:
    """Snapshot tests for generated tool definitions."""

    def test_tool_definitions_stable(self) -> None:
        """Tool definitions should remain stable across runs."""
        gen = ToolGenerator()
        tools = gen.generate(_canonical_spec())

        # Serialize to sorted JSON for deterministic comparison
        output = json.dumps(
            [t.to_mcp_dict() for t in tools],
            indent=2,
            sort_keys=True,
        )

        snapshot_path = SNAPSHOT_DIR / "tool_definitions.json"

        if not snapshot_path.exists():
            # First run: create the snapshot
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(output, encoding="utf-8")
            pytest.skip("Snapshot created — re-run to verify stability")

        expected = snapshot_path.read_text(encoding="utf-8")
        assert output == expected, (
            "Tool definition output changed! If intentional, delete "
            f"{snapshot_path} and re-run to update the snapshot."
        )

    def test_tool_count_stable(self) -> None:
        """Number of generated tools should match the endpoint count."""
        gen = ToolGenerator()
        tools = gen.generate(_canonical_spec())
        assert len(tools) == 3

    def test_tool_names_stable(self) -> None:
        """Tool names should be deterministic."""
        gen = ToolGenerator()
        tools = gen.generate(_canonical_spec())
        names = [t.name for t in tools]
        assert names == ["listitems", "createitem", "getitem"]


class TestServerCodeSnapshots:
    """Snapshot tests for generated server code."""

    def test_server_code_stable(self, tmp_path: Path) -> None:
        """Server code should remain stable across runs."""
        gen = ToolGenerator()
        files = gen.generate_server_code(_canonical_spec(), tmp_path)
        output = files[0].read_text(encoding="utf-8")

        snapshot_path = SNAPSHOT_DIR / "server_code.py"

        if not snapshot_path.exists():
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_text(output, encoding="utf-8")
            pytest.skip("Snapshot created — re-run to verify stability")

        expected = snapshot_path.read_text(encoding="utf-8")
        assert output == expected, (
            "Server code output changed! If intentional, delete "
            f"{snapshot_path} and re-run to update the snapshot."
        )
