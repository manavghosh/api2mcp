"""Unit tests for OpenAPI 3.0/3.1 parser (TASK-003 through TASK-009)."""

from __future__ import annotations

from pathlib import Path

import pytest

from api2mcp.core.exceptions import (
    CircularRefError,
    ParseException,
    RefResolutionError,
    ValidationException,
)
from api2mcp.core.ir_schema import (
    AuthType,
    HttpMethod,
    ParameterLocation,
)
from api2mcp.parsers.openapi import (
    OpenAPIParser,
    RefResolver,
    _detect_openapi_version,
    _detect_pagination,
    _parse_yaml_or_json,
    _schema_to_ir,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


# --------------------------------------------------------------------------- #
#  YAML / JSON Loading
# --------------------------------------------------------------------------- #


class TestParseYamlOrJson:
    def test_valid_yaml(self) -> None:
        result = _parse_yaml_or_json("openapi: '3.0.3'\ninfo:\n  title: T\n  version: '1'", "test")
        assert result["openapi"] == "3.0.3"

    def test_valid_json(self) -> None:
        result = _parse_yaml_or_json('{"openapi": "3.0.3", "info": {"title": "T"}}', "test")
        assert result["openapi"] == "3.0.3"

    def test_invalid_yaml(self) -> None:
        with pytest.raises(ParseException) as exc_info:
            _parse_yaml_or_json(":\n  - :\n    invalid: [", "bad.yaml")
        assert len(exc_info.value.errors) > 0

    def test_non_mapping_root(self) -> None:
        with pytest.raises(ParseException, match="Expected mapping"):
            _parse_yaml_or_json("- item1\n- item2", "list.yaml")


# --------------------------------------------------------------------------- #
#  Version Detection
# --------------------------------------------------------------------------- #


class TestDetectVersion:
    def test_3_0_3(self) -> None:
        assert _detect_openapi_version({"openapi": "3.0.3"}) == (3, 0, 3)

    def test_3_1_0(self) -> None:
        assert _detect_openapi_version({"openapi": "3.1.0"}) == (3, 1, 0)

    def test_two_part_version(self) -> None:
        assert _detect_openapi_version({"openapi": "3.0"}) == (3, 0, 0)

    def test_missing_openapi(self) -> None:
        assert _detect_openapi_version({}) is None

    def test_non_string(self) -> None:
        assert _detect_openapi_version({"openapi": 3}) is None

    def test_swagger_2(self) -> None:
        assert _detect_openapi_version({"swagger": "2.0"}) is None


# --------------------------------------------------------------------------- #
#  $ref Resolver
# --------------------------------------------------------------------------- #


class TestRefResolver:
    def setup_method(self) -> None:
        self.doc = {
            "components": {
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                        },
                    },
                    "Error": {"$ref": "#/components/schemas/SimpleError"},
                    "SimpleError": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                        },
                    },
                }
            }
        }
        self.resolver = RefResolver(self.doc)

    def test_resolve_local_ref(self) -> None:
        result = self.resolver.resolve("#/components/schemas/Pet")
        assert result["type"] == "object"
        assert "name" in result["properties"]

    def test_resolve_chained_ref(self) -> None:
        result = self.resolver.resolve("#/components/schemas/Error")
        assert result["type"] == "object"
        assert "message" in result["properties"]

    def test_resolve_nonexistent_ref(self) -> None:
        with pytest.raises(RefResolutionError, match="not found"):
            self.resolver.resolve("#/components/schemas/NonExistent")

    def test_circular_ref_detection(self) -> None:
        self.doc["components"]["schemas"]["A"] = {"$ref": "#/components/schemas/B"}
        self.doc["components"]["schemas"]["B"] = {"$ref": "#/components/schemas/A"}
        resolver = RefResolver(self.doc)
        with pytest.raises(CircularRefError, match="Circular"):
            resolver.resolve("#/components/schemas/A")

    def test_resolve_all_refs(self) -> None:
        obj = {
            "pet": {"$ref": "#/components/schemas/Pet"},
            "list": [{"$ref": "#/components/schemas/SimpleError"}],
        }
        result = self.resolver.resolve_all_refs(obj)
        assert result["pet"]["type"] == "object"
        assert result["list"][0]["type"] == "object"

    def test_resolve_all_refs_circular_safe(self) -> None:
        self.doc["components"]["schemas"]["Loop"] = {"$ref": "#/components/schemas/Loop"}
        resolver = RefResolver(self.doc)
        result = resolver.resolve_all_refs({"x": {"$ref": "#/components/schemas/Loop"}})
        assert "_circular_ref" in result["x"]

    def test_pointer_with_escaped_chars(self) -> None:
        self.doc["paths"] = {"/users/{id}": {"get": {"summary": "Get user"}}}
        result = self.resolver.resolve("#/paths/~1users~1{id}/get")
        assert result["summary"] == "Get user"


# --------------------------------------------------------------------------- #
#  Schema Conversion
# --------------------------------------------------------------------------- #


class TestSchemaToIr:
    def setup_method(self) -> None:
        self.resolver = RefResolver({})

    def test_string_type(self) -> None:
        ir = _schema_to_ir({"type": "string", "description": "A name"}, self.resolver)
        assert ir.type == "string"
        assert ir.description == "A name"

    def test_integer_with_constraints(self) -> None:
        ir = _schema_to_ir(
            {"type": "integer", "minimum": 0, "maximum": 100, "format": "int32"},
            self.resolver,
        )
        assert ir.type == "integer"
        assert ir.minimum == 0
        assert ir.maximum == 100

    def test_object_with_properties(self) -> None:
        ir = _schema_to_ir(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name"],
            },
            self.resolver,
        )
        assert ir.type == "object"
        assert "name" in ir.properties
        assert ir.required == ["name"]

    def test_array_with_items(self) -> None:
        ir = _schema_to_ir(
            {"type": "array", "items": {"type": "string"}},
            self.resolver,
        )
        assert ir.type == "array"
        assert ir.items is not None
        assert ir.items.type == "string"

    def test_nullable_openapi_30(self) -> None:
        ir = _schema_to_ir({"type": "string", "nullable": True}, self.resolver)
        assert ir.nullable is True

    def test_nullable_openapi_31(self) -> None:
        ir = _schema_to_ir({"type": ["string", "null"]}, self.resolver)
        assert ir.nullable is True
        assert ir.type == "string"

    def test_enum(self) -> None:
        ir = _schema_to_ir({"type": "string", "enum": ["a", "b"]}, self.resolver)
        assert ir.enum == ["a", "b"]

    def test_composition_one_of(self) -> None:
        ir = _schema_to_ir(
            {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            self.resolver,
        )
        assert len(ir.one_of) == 2

    def test_ref_resolution(self) -> None:
        doc = {
            "components": {
                "schemas": {
                    "Name": {"type": "string", "description": "A name"},
                }
            }
        }
        resolver = RefResolver(doc)
        ir = _schema_to_ir({"$ref": "#/components/schemas/Name"}, resolver)
        assert ir.type == "string"
        assert ir.ref_name == "Name"


# --------------------------------------------------------------------------- #
#  Pagination Detection
# --------------------------------------------------------------------------- #


class TestPaginationDetection:
    def _make_params(self, names: list[str]) -> list:
        from api2mcp.core.ir_schema import Parameter, ParameterLocation, SchemaRef

        return [
            Parameter(name=n, location=ParameterLocation.QUERY, schema=SchemaRef(type="string"))
            for n in names
        ]

    def test_offset_pagination(self) -> None:
        params = self._make_params(["offset", "limit"])
        result = _detect_pagination(params)
        assert result is not None
        assert result.style == "offset"

    def test_cursor_pagination(self) -> None:
        params = self._make_params(["after", "limit"])
        result = _detect_pagination(params)
        assert result is not None
        assert result.style == "cursor"

    def test_page_pagination(self) -> None:
        params = self._make_params(["page", "per_page"])
        result = _detect_pagination(params)
        assert result is not None
        assert result.style == "page"

    def test_no_pagination(self) -> None:
        params = self._make_params(["name", "filter"])
        result = _detect_pagination(params)
        assert result is None


# --------------------------------------------------------------------------- #
#  Parser Detection
# --------------------------------------------------------------------------- #


class TestOpenAPIParserDetect:
    def test_detects_openapi_30(self) -> None:
        parser = OpenAPIParser()
        assert parser.detect({"openapi": "3.0.3"}) is True

    def test_detects_openapi_31(self) -> None:
        parser = OpenAPIParser()
        assert parser.detect({"openapi": "3.1.0"}) is True

    def test_rejects_swagger_20(self) -> None:
        parser = OpenAPIParser()
        assert parser.detect({"swagger": "2.0"}) is False

    def test_rejects_random_doc(self) -> None:
        parser = OpenAPIParser()
        assert parser.detect({"type": "graphql"}) is False


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #


class TestOpenAPIParserValidate:
    @pytest.mark.asyncio
    async def test_validate_valid_spec(self) -> None:
        parser = OpenAPIParser()
        errors = await parser.validate(FIXTURES / "petstore.yaml")
        hard_errors = [e for e in errors if e.severity == "error"]
        assert len(hard_errors) == 0

    @pytest.mark.asyncio
    async def test_validate_missing_info(self) -> None:
        parser = OpenAPIParser()
        errors = await parser.validate(FIXTURES / "invalid-missing-info.yaml")
        error_msgs = [e.message for e in errors if e.severity == "error"]
        assert any("info" in m.lower() for m in error_msgs)

    @pytest.mark.asyncio
    async def test_validate_nonexistent_file(self) -> None:
        parser = OpenAPIParser()
        with pytest.raises(ParseException, match="not found"):
            await parser.validate(FIXTURES / "nonexistent.yaml")


# --------------------------------------------------------------------------- #
#  Full Parsing (Petstore 3.0)
# --------------------------------------------------------------------------- #


class TestOpenAPIParserParse30:
    @pytest.fixture
    async def spec(self):
        parser = OpenAPIParser()
        return await parser.parse(FIXTURES / "petstore.yaml")

    @pytest.mark.asyncio
    async def test_metadata(self, spec) -> None:
        assert spec.title == "Petstore"
        assert spec.version == "1.0.0"
        assert spec.source_format == "openapi3.0"
        assert spec.description == "A sample API for managing pets."

    @pytest.mark.asyncio
    async def test_servers(self, spec) -> None:
        assert len(spec.servers) == 2
        assert spec.base_url == "https://petstore.example.com/v1"
        assert spec.servers[1].description == "Development"

    @pytest.mark.asyncio
    async def test_endpoints(self, spec) -> None:
        assert len(spec.endpoints) == 4
        op_ids = {ep.operation_id for ep in spec.endpoints}
        assert op_ids == {"listPets", "createPet", "showPetById", "deletePet"}

    @pytest.mark.asyncio
    async def test_list_pets_endpoint(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "listPets")
        assert ep.method == HttpMethod.GET
        assert ep.path == "/pets"
        assert len(ep.parameters) == 2
        assert ep.tags == ["pets"]

    @pytest.mark.asyncio
    async def test_list_pets_pagination(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "listPets")
        assert ep.pagination is not None
        assert ep.pagination.style == "offset"
        assert ep.pagination.limit_param == "limit"

    @pytest.mark.asyncio
    async def test_parameter_details(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "listPets")
        limit_param = next(p for p in ep.parameters if p.name == "limit")
        assert limit_param.location == ParameterLocation.QUERY
        assert limit_param.required is False
        assert limit_param.schema.type == "integer"
        assert limit_param.schema.minimum == 1
        assert limit_param.schema.maximum == 100

    @pytest.mark.asyncio
    async def test_path_parameter(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "showPetById")
        pet_id = next(p for p in ep.parameters if p.name == "petId")
        assert pet_id.location == ParameterLocation.PATH
        assert pet_id.required is True

    @pytest.mark.asyncio
    async def test_request_body(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "createPet")
        assert ep.request_body is not None
        assert ep.request_body.content_type == "application/json"
        assert ep.request_body.required is True

    @pytest.mark.asyncio
    async def test_responses(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "listPets")
        assert len(ep.responses) == 2
        ok_resp = next(r for r in ep.responses if r.status_code == "200")
        assert ok_resp.content_type == "application/json"
        assert ok_resp.schema is not None
        assert ok_resp.schema.type == "array"

    @pytest.mark.asyncio
    async def test_deprecated_endpoint(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "deletePet")
        assert ep.deprecated is True

    @pytest.mark.asyncio
    async def test_security(self, spec) -> None:
        # Global security: apiKeyAuth
        ep = next(e for e in spec.endpoints if e.operation_id == "listPets")
        assert ep.security == [{"apiKeyAuth": []}]

        # Operation-level override: bearerAuth
        ep_del = next(e for e in spec.endpoints if e.operation_id == "deletePet")
        assert ep_del.security == [{"bearerAuth": []}]

    @pytest.mark.asyncio
    async def test_auth_schemes(self, spec) -> None:
        assert len(spec.auth_schemes) == 2
        bearer = next(a for a in spec.auth_schemes if a.name == "bearerAuth")
        assert bearer.type == AuthType.HTTP_BEARER
        assert bearer.bearer_format == "JWT"

        api_key = next(a for a in spec.auth_schemes if a.name == "apiKeyAuth")
        assert api_key.type == AuthType.API_KEY
        assert api_key.api_key_name == "X-API-Key"
        assert api_key.api_key_location == "header"

    @pytest.mark.asyncio
    async def test_models(self, spec) -> None:
        assert "Pet" in spec.models
        assert "NewPet" in spec.models
        assert "Error" in spec.models
        pet = spec.models["Pet"]
        assert "id" in pet.schema.properties
        assert "name" in pet.schema.properties
        assert pet.schema.required == ["id", "name"]

    @pytest.mark.asyncio
    async def test_ref_resolution_in_responses(self, spec) -> None:
        ep = next(e for e in spec.endpoints if e.operation_id == "listPets")
        ok_resp = next(r for r in ep.responses if r.status_code == "200")
        assert ok_resp.schema is not None
        # Items should be resolved from $ref to Pet
        assert ok_resp.schema.items is not None
        assert ok_resp.schema.items.type == "object"


# --------------------------------------------------------------------------- #
#  Full Parsing (Petstore 3.1)
# --------------------------------------------------------------------------- #


class TestOpenAPIParserParse31:
    @pytest.fixture
    async def spec(self):
        parser = OpenAPIParser()
        return await parser.parse(FIXTURES / "petstore-3.1.yaml")

    @pytest.mark.asyncio
    async def test_source_format(self, spec) -> None:
        assert spec.source_format == "openapi3.1"

    @pytest.mark.asyncio
    async def test_nullable_type_array(self, spec) -> None:
        """OpenAPI 3.1 uses type: [string, null] instead of nullable: true."""
        pet = spec.models["Pet"]
        tag_schema = pet.schema.properties.get("tag")
        assert tag_schema is not None
        assert tag_schema.nullable is True
        assert tag_schema.type == "string"

    @pytest.mark.asyncio
    async def test_webhooks_parsed(self, spec) -> None:
        webhook_eps = [e for e in spec.endpoints if e.metadata.get("webhook")]
        assert len(webhook_eps) == 1
        assert webhook_eps[0].operation_id == "onNewPet"

    @pytest.mark.asyncio
    async def test_total_endpoints(self, spec) -> None:
        # 2 path endpoints + 1 webhook
        assert len(spec.endpoints) == 3


# --------------------------------------------------------------------------- #
#  Error Cases
# --------------------------------------------------------------------------- #


class TestOpenAPIParserErrors:
    @pytest.mark.asyncio
    async def test_parse_missing_info(self) -> None:
        """Spec with openapi field but missing info raises ValidationException."""
        parser = OpenAPIParser()
        with pytest.raises(ValidationException, match="validation failed"):
            await parser.parse(FIXTURES / "invalid-missing-info.yaml")

    @pytest.mark.asyncio
    async def test_parse_file_not_found(self) -> None:
        parser = OpenAPIParser()
        with pytest.raises(ParseException, match="not found"):
            await parser.parse(Path("/nonexistent/spec.yaml"))

    @pytest.mark.asyncio
    async def test_parse_validation_failure(self) -> None:
        """A doc with openapi field but missing info should raise ValidationException."""
        parser = OpenAPIParser()
        # invalid-missing-info.yaml has openapi: 3.0.3 but no info
        with pytest.raises((ParseException, ValidationException)):
            await parser.parse(FIXTURES / "invalid-missing-info.yaml")


# --------------------------------------------------------------------------- #
#  Operation ID Generation
# --------------------------------------------------------------------------- #


class TestOperationIdGeneration:
    @pytest.mark.asyncio
    async def test_fallback_operation_id(self) -> None:
        """Endpoints without operationId get auto-generated IDs."""
        spec_yaml = """
openapi: "3.0.3"
info:
  title: Test
  version: "1.0"
paths:
  /users/{userId}/posts:
    get:
      responses:
        "200":
          description: OK
    post:
      responses:
        "201":
          description: Created
"""
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        assert len(spec.endpoints) == 2
        op_ids = {ep.operation_id for ep in spec.endpoints}
        assert "get_users_userId_posts" in op_ids
        assert "post_users_userId_posts" in op_ids
