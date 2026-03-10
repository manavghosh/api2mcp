"""Unit tests for MCP tool generator (TASK-016, TASK-017, TASK-018)."""

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
from api2mcp.generators.tool import MCPToolDef, ToolGenerator


# --- Fixtures ---


def _petstore_spec() -> APISpec:
    """Create a minimal Petstore-like API spec for testing."""
    return APISpec(
        title="Petstore",
        version="1.0.0",
        description="A sample API for managing pets.",
        base_url="https://petstore.example.com/v1",
        servers=[ServerInfo(url="https://petstore.example.com/v1")],
        source_format="openapi3.0",
        endpoints=[
            Endpoint(
                path="/pets",
                method=HttpMethod.GET,
                operation_id="listPets",
                summary="List all pets",
                tags=["pets"],
                parameters=[
                    Parameter(
                        name="limit",
                        location=ParameterLocation.QUERY,
                        schema=SchemaRef(type=SchemaType.INTEGER, minimum=1, maximum=100),
                        required=False,
                        description="Max number of results",
                    ),
                ],
                responses=[
                    Response(status_code="200", description="A list of pets"),
                ],
            ),
            Endpoint(
                path="/pets",
                method=HttpMethod.POST,
                operation_id="createPet",
                summary="Create a pet",
                tags=["pets"],
                request_body=RequestBody(
                    content_type="application/json",
                    schema=SchemaRef(
                        type=SchemaType.OBJECT,
                        properties={
                            "name": SchemaRef(type=SchemaType.STRING),
                            "tag": SchemaRef(type=SchemaType.STRING),
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
                path="/pets/{petId}",
                method=HttpMethod.GET,
                operation_id="showPetById",
                summary="Info for a specific pet",
                tags=["pets"],
                parameters=[
                    Parameter(
                        name="petId",
                        location=ParameterLocation.PATH,
                        schema=SchemaRef(type=SchemaType.STRING),
                        required=True,
                        description="The id of the pet to retrieve",
                    ),
                ],
                responses=[
                    Response(status_code="200", description="A pet"),
                ],
            ),
            Endpoint(
                path="/pets/{petId}",
                method=HttpMethod.DELETE,
                operation_id="deletePet",
                summary="Delete a pet",
                tags=["pets"],
                deprecated=True,
                parameters=[
                    Parameter(
                        name="petId",
                        location=ParameterLocation.PATH,
                        schema=SchemaRef(type=SchemaType.STRING),
                        required=True,
                    ),
                ],
                responses=[
                    Response(status_code="204", description="Pet deleted"),
                ],
            ),
        ],
    )


class TestMCPToolDef:
    """Tests for MCPToolDef dataclass."""

    def test_to_mcp_dict(self) -> None:
        tool = MCPToolDef(
            name="listpets",
            description="List all pets",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
            endpoint=Endpoint(
                path="/pets",
                method=HttpMethod.GET,
                operation_id="listPets",
            ),
        )
        result = tool.to_mcp_dict()
        assert result["name"] == "listpets"
        assert result["description"] == "List all pets"
        assert result["inputSchema"]["type"] == "object"

    def test_to_mcp_dict_serializable(self) -> None:
        """The MCP dict should be JSON-serializable."""
        tool = MCPToolDef(
            name="test",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
            endpoint=Endpoint(
                path="/test", method=HttpMethod.GET, operation_id="test"
            ),
        )
        serialized = json.dumps(tool.to_mcp_dict())
        assert isinstance(serialized, str)


class TestToolGenerator:
    """Tests for ToolGenerator.generate()."""

    def test_generate_petstore(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        assert len(tools) == 4
        names = [t.name for t in tools]
        assert "listpets" in names
        assert "createpet" in names
        assert "showpetbyid" in names
        assert "deletepet" in names

    def test_tool_descriptions(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        tool_map = {t.name: t for t in tools}
        assert tool_map["listpets"].description == "List all pets"
        assert tool_map["createpet"].description == "Create a pet"
        assert "[DEPRECATED]" in tool_map["deletepet"].description

    def test_required_params(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        tool_map = {t.name: t for t in tools}

        # listPets has optional limit only
        list_schema = tool_map["listpets"].input_schema
        assert "required" not in list_schema

        # showPetById has required petId
        show_schema = tool_map["showpetbyid"].input_schema
        assert "petId" in show_schema["required"]

    def test_request_body_params(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        tool_map = {t.name: t for t in tools}

        create_schema = tool_map["createpet"].input_schema
        assert "name" in create_schema["properties"]
        assert "tag" in create_schema["properties"]
        assert "name" in create_schema["required"]

    def test_body_param_names_tracked(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        tool_map = {t.name: t for t in tools}

        assert "name" in tool_map["createpet"].body_param_names
        assert "tag" in tool_map["createpet"].body_param_names
        assert tool_map["listpets"].body_param_names == []

    def test_metadata_tags(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        for tool in tools:
            assert tool.metadata.get("tags") == ["pets"]

    def test_metadata_deprecated(self) -> None:
        gen = ToolGenerator()
        tools = gen.generate(_petstore_spec())
        tool_map = {t.name: t for t in tools}
        assert tool_map["deletepet"].metadata.get("deprecated") is True
        assert "deprecated" not in tool_map["listpets"].metadata

    def test_empty_spec_returns_empty(self) -> None:
        spec = APISpec(title="Empty", version="1.0", endpoints=[])
        gen = ToolGenerator()
        tools = gen.generate(spec)
        assert tools == []

    def test_no_operation_id_fallback(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/items",
                    method=HttpMethod.GET,
                    operation_id="",
                    summary="Get items",
                ),
            ],
        )
        gen = ToolGenerator()
        tools = gen.generate(spec)
        assert len(tools) == 1
        assert tools[0].name == "get_items"

    def test_max_depth_passed_through(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/data",
                    method=HttpMethod.POST,
                    operation_id="postData",
                    request_body=RequestBody(
                        content_type="application/json",
                        schema=SchemaRef(
                            type=SchemaType.OBJECT,
                            properties={
                                "nested": SchemaRef(
                                    type=SchemaType.OBJECT,
                                    properties={
                                        "deep": SchemaRef(type=SchemaType.STRING)
                                    },
                                ),
                            },
                        ),
                    ),
                ),
            ],
        )
        # max_depth=1 means: depth 0 = top-level, depth 1 = properties truncated
        gen = ToolGenerator(max_depth=1)
        tools = gen.generate(spec)
        assert len(tools) == 1
        nested = tools[0].input_schema["properties"]["nested"]
        assert nested["type"] == "object"
        assert "properties" not in nested


class TestEdgeCases:
    """Tests for edge cases (TASK-017)."""

    def test_endpoint_no_parameters_no_body(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/health",
                    method=HttpMethod.GET,
                    operation_id="healthCheck",
                    summary="Health check",
                ),
            ],
        )
        gen = ToolGenerator()
        tools = gen.generate(spec)
        assert len(tools) == 1
        assert tools[0].input_schema["properties"] == {}
        assert tools[0].description == "Health check"

    def test_endpoint_empty_response(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/pets/{petId}",
                    method=HttpMethod.DELETE,
                    operation_id="deletePet",
                    responses=[
                        Response(status_code="204", description="No content"),
                    ],
                ),
            ],
        )
        gen = ToolGenerator()
        tools = gen.generate(spec)
        assert len(tools) == 1

    def test_multipart_form_body(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/upload",
                    method=HttpMethod.POST,
                    operation_id="uploadFile",
                    summary="Upload a file",
                    request_body=RequestBody(
                        content_type="multipart/form-data",
                        schema=SchemaRef(
                            type=SchemaType.OBJECT,
                            properties={
                                "file": SchemaRef(
                                    type=SchemaType.STRING, format="binary"
                                ),
                                "description": SchemaRef(type=SchemaType.STRING),
                            },
                            required=["file"],
                        ),
                        required=True,
                    ),
                ),
            ],
        )
        gen = ToolGenerator()
        tools = gen.generate(spec)
        assert len(tools) == 1
        schema = tools[0].input_schema
        assert "file" in schema["properties"]
        assert "description" in schema["properties"]

    def test_description_fallback_from_description_field(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/test",
                    method=HttpMethod.GET,
                    operation_id="testOp",
                    summary="",
                    description="This is a detailed description. With multiple sentences.",
                ),
            ],
        )
        gen = ToolGenerator()
        tools = gen.generate(spec)
        # Should use first sentence
        assert tools[0].description == "This is a detailed description"

    def test_description_fallback_to_method_path(self) -> None:
        spec = APISpec(
            title="Test",
            version="1.0",
            endpoints=[
                Endpoint(
                    path="/test",
                    method=HttpMethod.GET,
                    operation_id="testOp",
                    summary="",
                    description="",
                ),
            ],
        )
        gen = ToolGenerator()
        tools = gen.generate(spec)
        assert tools[0].description == "GET /test"


class TestServerCodeGeneration:
    """Tests for Jinja2 template-based server code generation."""

    def test_generate_server_code(self, tmp_path: Path) -> None:
        gen = ToolGenerator()
        spec = _petstore_spec()
        files = gen.generate_server_code(spec, tmp_path)
        assert len(files) == 1
        server_file = files[0]
        assert server_file.name == "server.py"
        assert server_file.exists()

        content = server_file.read_text()
        assert "Petstore" in content
        assert "listpets" in content
        assert "createpet" in content
        assert "showpetbyid" in content
        assert "deletepet" in content
        assert "BASE_URL" in content

    def test_generate_server_code_empty_spec(self, tmp_path: Path) -> None:
        gen = ToolGenerator()
        spec = APISpec(title="Empty", version="1.0", endpoints=[])
        files = gen.generate_server_code(spec, tmp_path)
        assert files == []

    def test_generate_server_code_custom_name(self, tmp_path: Path) -> None:
        gen = ToolGenerator()
        spec = _petstore_spec()
        files = gen.generate_server_code(spec, tmp_path, server_name="my_server")
        content = files[0].read_text()
        assert "my_server" in content

    def test_generated_server_has_handlers(self, tmp_path: Path) -> None:
        gen = ToolGenerator()
        spec = _petstore_spec()
        files = gen.generate_server_code(spec, tmp_path)
        content = files[0].read_text()
        # Each tool should have a handler function
        assert "_handle_listpets" in content
        assert "_handle_createpet" in content
        assert "_handle_showpetbyid" in content
        assert "_handle_deletepet" in content

    def test_generated_server_has_tool_definitions(self, tmp_path: Path) -> None:
        gen = ToolGenerator()
        spec = _petstore_spec()
        files = gen.generate_server_code(spec, tmp_path)
        content = files[0].read_text()
        assert "TOOLS" in content
        assert "Tool(" in content
        assert "inputSchema" in content
