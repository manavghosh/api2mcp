"""Unit tests for IR-to-JSON-Schema mapper (TASK-013, TASK-015, TASK-018)."""


from api2mcp.core.ir_schema import (
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    RequestBody,
    SchemaRef,
    SchemaType,
)
from api2mcp.generators.schema_mapper import build_input_schema


def _make_endpoint(
    parameters: list[Parameter] | None = None,
    request_body: RequestBody | None = None,
    path: str = "/test",
    method: HttpMethod = HttpMethod.GET,
) -> Endpoint:
    return Endpoint(
        path=path,
        method=method,
        operation_id="test_op",
        parameters=parameters or [],
        request_body=request_body,
    )


class TestBuildInputSchema:
    """Tests for build_input_schema()."""

    def test_no_parameters(self) -> None:
        ep = _make_endpoint()
        schema = build_input_schema(ep)
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert "required" not in schema

    def test_single_query_param(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="limit",
                    location=ParameterLocation.QUERY,
                    schema=SchemaRef(type=SchemaType.INTEGER, description="Max results"),
                    required=False,
                )
            ]
        )
        schema = build_input_schema(ep)
        assert "limit" in schema["properties"]
        assert schema["properties"]["limit"]["type"] == "integer"
        assert "required" not in schema

    def test_required_path_param(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="petId",
                    location=ParameterLocation.PATH,
                    schema=SchemaRef(type=SchemaType.STRING),
                    required=True,
                    description="The pet ID",
                )
            ]
        )
        schema = build_input_schema(ep)
        assert "petId" in schema["properties"]
        assert schema["required"] == ["petId"]
        assert schema["properties"]["petId"]["description"] == "The pet ID"

    def test_multiple_params_mixed_required(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="petId",
                    location=ParameterLocation.PATH,
                    schema=SchemaRef(type=SchemaType.STRING),
                    required=True,
                ),
                Parameter(
                    name="limit",
                    location=ParameterLocation.QUERY,
                    schema=SchemaRef(type=SchemaType.INTEGER),
                    required=False,
                ),
                Parameter(
                    name="X-Request-ID",
                    location=ParameterLocation.HEADER,
                    schema=SchemaRef(type=SchemaType.STRING),
                    required=False,
                ),
            ]
        )
        schema = build_input_schema(ep)
        assert len(schema["properties"]) == 3
        assert schema["required"] == ["petId"]

    def test_json_request_body_merged(self) -> None:
        body_schema = SchemaRef(
            type=SchemaType.OBJECT,
            properties={
                "name": SchemaRef(type=SchemaType.STRING),
                "tag": SchemaRef(type=SchemaType.STRING),
            },
            required=["name"],
        )
        ep = _make_endpoint(
            request_body=RequestBody(
                content_type="application/json",
                schema=body_schema,
                required=True,
            ),
            method=HttpMethod.POST,
        )
        schema = build_input_schema(ep)
        # Body properties merged directly
        assert "name" in schema["properties"]
        assert "tag" in schema["properties"]
        assert "name" in schema["required"]

    def test_body_property_collision_prefixed(self) -> None:
        """When a body property name collides with a param name, prefix with body_."""
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="name",
                    location=ParameterLocation.QUERY,
                    schema=SchemaRef(type=SchemaType.STRING),
                    required=False,
                )
            ],
            request_body=RequestBody(
                content_type="application/json",
                schema=SchemaRef(
                    type=SchemaType.OBJECT,
                    properties={
                        "name": SchemaRef(type=SchemaType.STRING),
                    },
                    required=["name"],
                ),
                required=True,
            ),
            method=HttpMethod.POST,
        )
        schema = build_input_schema(ep)
        assert "name" in schema["properties"]  # from query param
        assert "body_name" in schema["properties"]  # from body, prefixed

    def test_non_object_body_wrapped(self) -> None:
        """Array or primitive bodies are wrapped as a 'body' property."""
        ep = _make_endpoint(
            request_body=RequestBody(
                content_type="application/json",
                schema=SchemaRef(
                    type=SchemaType.ARRAY,
                    items=SchemaRef(type=SchemaType.STRING),
                ),
                required=True,
                description="List of tags",
            ),
            method=HttpMethod.POST,
        )
        schema = build_input_schema(ep)
        assert "body" in schema["properties"]
        assert schema["properties"]["body"]["type"] == "array"
        assert "body" in schema["required"]

    def test_deprecated_param_flagged(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="old_field",
                    location=ParameterLocation.QUERY,
                    schema=SchemaRef(type=SchemaType.STRING),
                    deprecated=True,
                )
            ]
        )
        schema = build_input_schema(ep)
        assert schema["properties"]["old_field"].get("deprecated") is True

    def test_param_example_included(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="limit",
                    location=ParameterLocation.QUERY,
                    schema=SchemaRef(type=SchemaType.INTEGER),
                    example=25,
                )
            ]
        )
        schema = build_input_schema(ep)
        assert schema["properties"]["limit"]["example"] == 25


class TestSchemaSimplification:
    """Tests for schema depth limiting."""

    def test_shallow_schema_unchanged(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="data",
                    location=ParameterLocation.QUERY,
                    schema=SchemaRef(type=SchemaType.STRING),
                )
            ]
        )
        schema = build_input_schema(ep, max_depth=5)
        assert schema["properties"]["data"]["type"] == "string"

    def test_deep_nesting_truncated(self) -> None:
        # Create a deeply nested object: level1 > level2 > level3 > level4
        level4 = SchemaRef(type=SchemaType.STRING, description="deep value")
        level3 = SchemaRef(
            type=SchemaType.OBJECT,
            properties={"l4": level4},
        )
        level2 = SchemaRef(
            type=SchemaType.OBJECT,
            properties={"l3": level3},
        )
        level1 = SchemaRef(
            type=SchemaType.OBJECT,
            properties={"l2": level2},
        )

        ep = _make_endpoint(
            request_body=RequestBody(
                content_type="application/json",
                schema=SchemaRef(
                    type=SchemaType.OBJECT,
                    properties={"l1": level1},
                ),
            ),
            method=HttpMethod.POST,
        )
        # With max_depth=3, level3+ should be truncated
        schema = build_input_schema(ep, max_depth=3)
        # l1 should exist (depth 1 within properties)
        assert "l1" in schema["properties"]
        l1 = schema["properties"]["l1"]
        # l2 should exist
        assert "l2" in l1.get("properties", {})
        l2 = l1["properties"]["l2"]
        # l3 should be truncated to generic object
        assert "l3" in l2.get("properties", {})
        l3 = l2["properties"]["l3"]
        assert l3["type"] == "object"
        assert "properties" not in l3  # truncated

    def test_array_depth_limited(self) -> None:
        nested = SchemaRef(
            type=SchemaType.ARRAY,
            items=SchemaRef(
                type=SchemaType.OBJECT,
                properties={
                    "deep": SchemaRef(type=SchemaType.STRING),
                },
            ),
        )
        ep = _make_endpoint(
            request_body=RequestBody(
                content_type="application/json",
                schema=SchemaRef(
                    type=SchemaType.OBJECT,
                    properties={"arr": nested},
                ),
            ),
            method=HttpMethod.POST,
        )
        schema = build_input_schema(ep, max_depth=2)
        arr = schema["properties"]["arr"]
        assert arr["type"] == "array"


class TestGraphQLParameters:
    """Tests for GraphQL body-location parameters."""

    def test_graphql_body_params_included(self) -> None:
        ep = _make_endpoint(
            parameters=[
                Parameter(
                    name="userId",
                    location=ParameterLocation.BODY,
                    schema=SchemaRef(type=SchemaType.STRING),
                    required=True,
                ),
                Parameter(
                    name="includeEmail",
                    location=ParameterLocation.BODY,
                    schema=SchemaRef(type=SchemaType.BOOLEAN),
                    required=False,
                ),
            ],
            method=HttpMethod.QUERY,
        )
        schema = build_input_schema(ep)
        assert "userId" in schema["properties"]
        assert "includeEmail" in schema["properties"]
        assert "userId" in schema["required"]
