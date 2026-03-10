"""Unit tests for IR schema definitions (TASK-001)."""

from api2mcp.core.ir_schema import (
    APISpec,
    AuthScheme,
    AuthType,
    Endpoint,
    HttpMethod,
    ModelDef,
    Parameter,
    ParameterLocation,
    PaginationConfig,
    SchemaRef,
    SchemaType,
    ServerInfo,
)


class TestSchemaRef:
    """Tests for SchemaRef dataclass and to_json_schema()."""

    def test_simple_string_schema(self) -> None:
        sr = SchemaRef(type=SchemaType.STRING, description="A name")
        result = sr.to_json_schema()
        assert result == {"type": "string", "description": "A name"}

    def test_integer_with_constraints(self) -> None:
        sr = SchemaRef(
            type=SchemaType.INTEGER,
            minimum=1,
            maximum=100,
            format="int32",
        )
        result = sr.to_json_schema()
        assert result["type"] == "integer"
        assert result["minimum"] == 1
        assert result["maximum"] == 100
        assert result["format"] == "int32"

    def test_object_with_properties(self) -> None:
        sr = SchemaRef(
            type=SchemaType.OBJECT,
            properties={
                "name": SchemaRef(type=SchemaType.STRING),
                "age": SchemaRef(type=SchemaType.INTEGER),
            },
            required=["name"],
        )
        result = sr.to_json_schema()
        assert result["type"] == "object"
        assert "name" in result["properties"]
        assert result["properties"]["name"]["type"] == "string"
        assert result["required"] == ["name"]

    def test_array_with_items(self) -> None:
        sr = SchemaRef(
            type=SchemaType.ARRAY,
            items=SchemaRef(type=SchemaType.STRING),
        )
        result = sr.to_json_schema()
        assert result["type"] == "array"
        assert result["items"]["type"] == "string"

    def test_nullable_schema(self) -> None:
        sr = SchemaRef(type=SchemaType.STRING, nullable=True)
        result = sr.to_json_schema()
        assert result["type"] == ["string", "null"]

    def test_enum_schema(self) -> None:
        sr = SchemaRef(type=SchemaType.STRING, enum=["active", "inactive"])
        result = sr.to_json_schema()
        assert result["enum"] == ["active", "inactive"]

    def test_one_of_composition(self) -> None:
        sr = SchemaRef(
            type="",
            one_of=[
                SchemaRef(type=SchemaType.STRING),
                SchemaRef(type=SchemaType.INTEGER),
            ],
        )
        result = sr.to_json_schema()
        assert len(result["oneOf"]) == 2

    def test_additional_properties_bool(self) -> None:
        sr = SchemaRef(type=SchemaType.OBJECT, additional_properties=False)
        result = sr.to_json_schema()
        assert result["additionalProperties"] is False

    def test_additional_properties_schema(self) -> None:
        sr = SchemaRef(
            type=SchemaType.OBJECT,
            additional_properties=SchemaRef(type=SchemaType.STRING),
        )
        result = sr.to_json_schema()
        assert result["additionalProperties"]["type"] == "string"

    def test_default_values(self) -> None:
        sr = SchemaRef(type=SchemaType.STRING, default="hello")
        result = sr.to_json_schema()
        assert result["default"] == "hello"

    def test_pattern_and_length(self) -> None:
        sr = SchemaRef(
            type=SchemaType.STRING,
            pattern="^[a-z]+$",
            min_length=1,
            max_length=50,
        )
        result = sr.to_json_schema()
        assert result["pattern"] == "^[a-z]+$"
        assert result["minLength"] == 1
        assert result["maxLength"] == 50


class TestParameter:
    def test_path_parameter_required_by_default(self) -> None:
        p = Parameter(
            name="id",
            location=ParameterLocation.PATH,
            schema=SchemaRef(type=SchemaType.STRING),
            required=True,
        )
        assert p.required is True
        assert p.location == ParameterLocation.PATH

    def test_query_parameter(self) -> None:
        p = Parameter(
            name="limit",
            location=ParameterLocation.QUERY,
            schema=SchemaRef(type=SchemaType.INTEGER),
            required=False,
        )
        assert p.required is False


class TestEndpoint:
    def test_basic_endpoint(self) -> None:
        ep = Endpoint(
            path="/pets",
            method=HttpMethod.GET,
            operation_id="listPets",
            summary="List pets",
        )
        assert ep.path == "/pets"
        assert ep.method == HttpMethod.GET
        assert ep.operation_id == "listPets"
        assert ep.parameters == []
        assert ep.deprecated is False

    def test_deprecated_endpoint(self) -> None:
        ep = Endpoint(
            path="/old",
            method=HttpMethod.DELETE,
            operation_id="deleteOld",
            deprecated=True,
        )
        assert ep.deprecated is True

    def test_endpoint_with_pagination(self) -> None:
        ep = Endpoint(
            path="/items",
            method=HttpMethod.GET,
            operation_id="listItems",
            pagination=PaginationConfig(
                style="cursor", cursor_param="after", limit_param="limit"
            ),
        )
        assert ep.pagination is not None
        assert ep.pagination.style == "cursor"


class TestAuthScheme:
    def test_api_key(self) -> None:
        auth = AuthScheme(
            name="apiKey",
            type=AuthType.API_KEY,
            api_key_name="X-API-Key",
            api_key_location="header",
        )
        assert auth.type == AuthType.API_KEY
        assert auth.api_key_name == "X-API-Key"

    def test_oauth2(self) -> None:
        auth = AuthScheme(
            name="oauth",
            type=AuthType.OAUTH2,
            flows={"authorizationCode": {"authorizationUrl": "https://example.com/auth"}},
        )
        assert auth.type == AuthType.OAUTH2
        assert "authorizationCode" in auth.flows

    def test_bearer(self) -> None:
        auth = AuthScheme(
            name="bearer",
            type=AuthType.HTTP_BEARER,
            scheme="bearer",
            bearer_format="JWT",
        )
        assert auth.scheme == "bearer"
        assert auth.bearer_format == "JWT"


class TestAPISpec:
    def test_empty_spec(self) -> None:
        spec = APISpec(title="Test", version="1.0.0")
        assert spec.title == "Test"
        assert spec.endpoints == []
        assert spec.auth_schemes == []
        assert spec.models == {}

    def test_full_spec(self) -> None:
        spec = APISpec(
            title="Full API",
            version="2.0.0",
            description="A complete API",
            base_url="https://api.example.com",
            servers=[ServerInfo(url="https://api.example.com")],
            endpoints=[
                Endpoint(
                    path="/items",
                    method=HttpMethod.GET,
                    operation_id="listItems",
                )
            ],
            auth_schemes=[
                AuthScheme(name="key", type=AuthType.API_KEY)
            ],
            models={
                "Item": ModelDef(
                    name="Item",
                    schema=SchemaRef(type=SchemaType.OBJECT),
                )
            },
            source_format="openapi3.0",
        )
        assert len(spec.endpoints) == 1
        assert len(spec.auth_schemes) == 1
        assert "Item" in spec.models
        assert spec.source_format == "openapi3.0"


class TestEnums:
    def test_http_methods(self) -> None:
        assert HttpMethod.GET.value == "GET"
        assert HttpMethod.QUERY.value == "QUERY"
        assert HttpMethod.MUTATION.value == "MUTATION"

    def test_parameter_locations(self) -> None:
        assert ParameterLocation.PATH.value == "path"
        assert ParameterLocation.BODY.value == "body"

    def test_schema_types(self) -> None:
        assert SchemaType.STRING.value == "string"
        assert SchemaType.OBJECT.value == "object"
        assert SchemaType.ARRAY.value == "array"
