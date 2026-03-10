"""Integration tests for the full IR → generator → MCP tool pipeline (TASK-019).

Tests the complete flow: parse a real spec file → generate tools → verify
tool definitions are valid and complete.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api2mcp.generators.tool import MCPToolDef, ToolGenerator
from api2mcp.parsers.openapi import OpenAPIParser

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


@pytest.mark.integration
class TestFullPipeline:
    """End-to-end: parse spec → generate tools → validate output."""

    @pytest.fixture
    def petstore_spec_path(self) -> Path:
        return FIXTURES_DIR / "petstore.yaml"

    @pytest.fixture
    def petstore_31_spec_path(self) -> Path:
        return FIXTURES_DIR / "petstore-3.1.yaml"

    async def test_petstore_full_pipeline(self, petstore_spec_path: Path) -> None:
        """Parse petstore.yaml → generate tools → verify all 4 endpoints."""
        parser = OpenAPIParser()
        ir = await parser.parse(petstore_spec_path)

        gen = ToolGenerator()
        tools = gen.generate(ir)

        assert len(tools) == 4
        names = {t.name for t in tools}
        assert "listpets" in names
        assert "createpet" in names
        assert "showpetbyid" in names
        assert "deletepet" in names

        # Verify all tools produce valid MCP dicts
        for tool in tools:
            mcp_dict = tool.to_mcp_dict()
            assert "name" in mcp_dict
            assert "description" in mcp_dict
            assert "inputSchema" in mcp_dict
            assert mcp_dict["inputSchema"]["type"] == "object"
            # Must be JSON-serializable
            json.dumps(mcp_dict)

    async def test_petstore_tool_schemas(self, petstore_spec_path: Path) -> None:
        """Verify parameter schemas are correctly mapped."""
        parser = OpenAPIParser()
        ir = await parser.parse(petstore_spec_path)

        gen = ToolGenerator()
        tools = gen.generate(ir)
        tool_map = {t.name: t for t in tools}

        # listPets: optional limit and offset query params
        list_schema = tool_map["listpets"].input_schema
        assert "limit" in list_schema["properties"]
        assert list_schema["properties"]["limit"]["type"] == "integer"

        # createPet: required name, optional tag from request body
        create_schema = tool_map["createpet"].input_schema
        assert "name" in create_schema["properties"]
        assert "name" in create_schema.get("required", [])

        # showPetById: required petId path param
        show_schema = tool_map["showpetbyid"].input_schema
        assert "petId" in show_schema["properties"]
        assert "petId" in show_schema["required"]

    async def test_petstore_server_code_generation(
        self, petstore_spec_path: Path, tmp_path: Path
    ) -> None:
        """Generate server code and verify it's syntactically valid Python."""
        parser = OpenAPIParser()
        ir = await parser.parse(petstore_spec_path)

        gen = ToolGenerator()
        files = gen.generate_server_code(ir, tmp_path)

        assert len(files) == 1
        server_code = files[0].read_text()

        # Verify it's valid Python syntax
        compile(server_code, files[0].name, "exec")

        # Verify key elements present
        assert "petstore" in server_code.lower()
        assert "TOOLS" in server_code
        assert "list_tools" in server_code
        assert "call_tool" in server_code

    async def test_31_spec_pipeline(self, petstore_31_spec_path: Path) -> None:
        """Verify pipeline works with OpenAPI 3.1 spec too."""
        if not petstore_31_spec_path.exists():
            pytest.skip("petstore-3.1.yaml fixture not available")

        parser = OpenAPIParser()
        ir = await parser.parse(petstore_31_spec_path)

        gen = ToolGenerator()
        tools = gen.generate(ir)

        # Should produce tools regardless of OpenAPI version
        assert len(tools) > 0
        for tool in tools:
            mcp_dict = tool.to_mcp_dict()
            json.dumps(mcp_dict)  # Must be serializable


@pytest.mark.integration
class TestToolOutputValidity:
    """Verify generated tool output conforms to MCP protocol expectations."""

    async def test_input_schema_is_valid_json_schema(self) -> None:
        """Generated input_schema should be valid JSON Schema."""
        from api2mcp.core.ir_schema import (
            APISpec,
            Endpoint,
            HttpMethod,
            Parameter,
            ParameterLocation,
            SchemaRef,
            SchemaType,
        )

        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/users/{userId}",
                    method=HttpMethod.GET,
                    operation_id="getUser",
                    parameters=[
                        Parameter(
                            name="userId",
                            location=ParameterLocation.PATH,
                            schema=SchemaRef(type=SchemaType.STRING),
                            required=True,
                        ),
                        Parameter(
                            name="fields",
                            location=ParameterLocation.QUERY,
                            schema=SchemaRef(
                                type=SchemaType.ARRAY,
                                items=SchemaRef(type=SchemaType.STRING),
                            ),
                            required=False,
                        ),
                    ],
                ),
            ],
        )

        gen = ToolGenerator()
        tools = gen.generate(spec)
        schema = tools[0].input_schema

        # Validate structure
        assert schema["type"] == "object"
        assert "userId" in schema["properties"]
        assert "fields" in schema["properties"]
        assert schema["properties"]["fields"]["type"] == "array"
        assert schema["properties"]["fields"]["items"]["type"] == "string"
        assert "userId" in schema["required"]
