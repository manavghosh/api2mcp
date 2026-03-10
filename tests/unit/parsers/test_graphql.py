"""Unit tests for the GraphQL parser (F3.1).

Tests cover:
- SDL parsing for various schema patterns
- Introspection result parsing
- Input type to parameter mapping
- Type system mapping (scalars, enums, objects, lists, non-null)
- Fragment-free parsing (fragments live in operations, not schemas)
- Subscription support
- Detect format detection
- Validate method
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api2mcp.core.ir_schema import HttpMethod, ParameterLocation
from api2mcp.parsers.graphql import (
    GraphQLParser,
    _IntrospectionParser,
    _SDLParser,
    _type_to_schema_ref,
)

# ---------------------------------------------------------------------------
# Check if graphql-core is available
# ---------------------------------------------------------------------------

try:
    import graphql  # noqa: F401
    HAS_GRAPHQL_CORE = True
except ImportError:
    HAS_GRAPHQL_CORE = False

pytestmark_gql = pytest.mark.skipif(
    not HAS_GRAPHQL_CORE, reason="graphql-core not installed"
)

# ---------------------------------------------------------------------------
# Sample SDL schemas
# ---------------------------------------------------------------------------

SIMPLE_SDL = """
type Query {
  hello: String
  greet(name: String!): String
}
"""

FULL_SDL = """
\"\"\"A user in the system\"\"\"
type User {
  id: ID!
  name: String!
  email: String
  age: Int
  score: Float
  active: Boolean
}

input CreateUserInput {
  name: String!
  email: String
  age: Int
}

enum Role {
  ADMIN
  USER
  GUEST
}

type Query {
  \"\"\"Get a user by ID\"\"\"
  getUser(id: ID!): User
  listUsers(limit: Int, offset: Int, role: Role): [User!]!
}

type Mutation {
  \"\"\"Create a new user\"\"\"
  createUser(input: CreateUserInput!): User
  deleteUser(id: ID!): Boolean!
}

type Subscription {
  \"\"\"Watch user updates\"\"\"
  userUpdated(id: ID!): User
}
"""

NESTED_INPUT_SDL = """
input AddressInput {
  street: String!
  city: String!
  country: String
}

input CreateProfileInput {
  name: String!
  address: AddressInput
}

type Profile {
  id: ID!
  name: String!
}

type Mutation {
  createProfile(input: CreateProfileInput!): Profile
}
"""

UNION_SDL = """
type Cat {
  meow: String
}

type Dog {
  bark: String
}

union Animal = Cat | Dog

type Query {
  getAnimal(id: ID!): Animal
}
"""

# ---------------------------------------------------------------------------
# Helper: build a minimal introspection result
# ---------------------------------------------------------------------------

def _make_introspection(
    query_fields: list[dict] | None = None,
    mutation_fields: list[dict] | None = None,
    extra_types: list[dict] | None = None,
) -> dict:
    """Build a minimal introspection JSON structure."""
    types: list[dict] = [
        {
            "kind": "SCALAR", "name": "String", "description": None,
            "fields": None, "inputFields": None, "enumValues": None,
            "possibleTypes": None,
        },
        {
            "kind": "SCALAR", "name": "ID", "description": None,
            "fields": None, "inputFields": None, "enumValues": None,
            "possibleTypes": None,
        },
        {
            "kind": "SCALAR", "name": "Boolean", "description": None,
            "fields": None, "inputFields": None, "enumValues": None,
            "possibleTypes": None,
        },
        {
            "kind": "SCALAR", "name": "Int", "description": None,
            "fields": None, "inputFields": None, "enumValues": None,
            "possibleTypes": None,
        },
    ]

    schema: dict = {"types": types}

    if query_fields is not None:
        types.append({
            "kind": "OBJECT", "name": "Query", "description": None,
            "fields": query_fields, "inputFields": None,
            "enumValues": None, "possibleTypes": None,
        })
        schema["queryType"] = {"name": "Query"}

    if mutation_fields is not None:
        types.append({
            "kind": "OBJECT", "name": "Mutation", "description": None,
            "fields": mutation_fields, "inputFields": None,
            "enumValues": None, "possibleTypes": None,
        })
        schema["mutationType"] = {"name": "Mutation"}

    if extra_types:
        types.extend(extra_types)

    return {"__schema": schema}


# ---------------------------------------------------------------------------
# _SDLParser tests
# ---------------------------------------------------------------------------


@pytestmark_gql
class TestSDLParser:
    def test_simple_query_fields(self) -> None:
        spec = _SDLParser().parse(SIMPLE_SDL)
        names = [e.operation_id for e in spec.endpoints]
        assert "hello" in names
        assert "greet" in names

    def test_query_method(self) -> None:
        spec = _SDLParser().parse(SIMPLE_SDL)
        for ep in spec.endpoints:
            assert ep.method == HttpMethod.QUERY

    def test_mutation_method(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        mutations = [e for e in spec.endpoints if e.method == HttpMethod.MUTATION]
        assert {m.operation_id for m in mutations} == {"createUser", "deleteUser"}

    def test_subscription_method(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        subs = [e for e in spec.endpoints if e.method == HttpMethod.SUBSCRIPTION]
        assert len(subs) == 1
        assert subs[0].operation_id == "userUpdated"
        assert subs[0].metadata.get("subscription") is True

    def test_required_arg_becomes_required_param(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        get_user = next(e for e in spec.endpoints if e.operation_id == "getUser")
        param = next(p for p in get_user.parameters if p.name == "id")
        assert param.required is True

    def test_optional_arg_not_required(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        list_users = next(e for e in spec.endpoints if e.operation_id == "listUsers")
        limit_param = next(p for p in list_users.parameters if p.name == "limit")
        assert limit_param.required is False

    def test_parameters_have_body_location(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        for ep in spec.endpoints:
            for param in ep.parameters:
                assert param.location == ParameterLocation.BODY

    def test_input_type_parameter_is_object(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        create = next(e for e in spec.endpoints if e.operation_id == "createUser")
        input_param = next(p for p in create.parameters if p.name == "input")
        assert input_param.schema.type == "object"
        assert "name" in input_param.schema.properties
        assert "email" in input_param.schema.properties

    def test_enum_arg_becomes_string_with_enum_values(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        list_users = next(e for e in spec.endpoints if e.operation_id == "listUsers")
        role_param = next(p for p in list_users.parameters if p.name == "role")
        assert role_param.schema.type == "string"
        assert set(role_param.schema.enum) == {"ADMIN", "USER", "GUEST"}

    def test_list_return_type(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        list_users = next(e for e in spec.endpoints if e.operation_id == "listUsers")
        response = list_users.responses[0]
        assert response.schema is not None
        assert response.schema.type == "array"

    def test_models_populated_with_non_root_types(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        assert "User" in spec.models
        assert "CreateUserInput" in spec.models

    def test_source_format(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        assert spec.source_format == "graphql"

    def test_endpoint_path_contains_field_name(self) -> None:
        spec = _SDLParser().parse(SIMPLE_SDL)
        hello = next(e for e in spec.endpoints if e.operation_id == "hello")
        assert "hello" in hello.path

    def test_deprecated_field(self) -> None:
        sdl = """
        type Query {
          oldField: String @deprecated(reason: "Use newField")
          newField: String
        }
        """
        spec = _SDLParser().parse(sdl)
        old = next(e for e in spec.endpoints if e.operation_id == "oldField")
        assert old.deprecated is True

    def test_nested_input_type(self) -> None:
        spec = _SDLParser().parse(NESTED_INPUT_SDL)
        create = next(e for e in spec.endpoints if e.operation_id == "createProfile")
        input_param = next(p for p in create.parameters if p.name == "input")
        assert "address" in input_param.schema.properties
        address_schema = input_param.schema.properties["address"]
        assert address_schema.type == "object"
        assert "street" in address_schema.properties

    def test_union_return_type(self) -> None:
        spec = _SDLParser().parse(UNION_SDL)
        get_animal = next(e for e in spec.endpoints if e.operation_id == "getAnimal")
        resp_schema = get_animal.responses[0].schema
        assert resp_schema is not None
        assert len(resp_schema.any_of) == 2

    def test_invalid_sdl_raises_parse_exception(self) -> None:
        from api2mcp.core.exceptions import ParseException
        with pytest.raises(ParseException):
            _SDLParser().parse("this is not valid graphql !!@#$%")

    def test_validate_valid_sdl_returns_no_errors(self) -> None:
        errors = _SDLParser().validate(SIMPLE_SDL)
        assert errors == []

    def test_validate_invalid_sdl_returns_errors(self) -> None:
        errors = _SDLParser().validate("type Query { broken !!!")
        assert len(errors) > 0

    def test_request_body_created_when_args_present(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        get_user = next(e for e in spec.endpoints if e.operation_id == "getUser")
        assert get_user.request_body is not None
        assert get_user.request_body.content_type == "application/json"

    def test_no_request_body_when_no_args(self) -> None:
        spec = _SDLParser().parse(SIMPLE_SDL)
        hello = next(e for e in spec.endpoints if e.operation_id == "hello")
        assert hello.request_body is None

    def test_tags_reflect_operation_type(self) -> None:
        spec = _SDLParser().parse(FULL_SDL)
        queries = [e for e in spec.endpoints if e.method == HttpMethod.QUERY]
        for ep in queries:
            assert "query" in ep.tags


# ---------------------------------------------------------------------------
# _IntrospectionParser tests
# ---------------------------------------------------------------------------


class TestIntrospectionParser:
    def test_simple_query_field(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "getUser",
                "description": "Get user",
                "args": [
                    {
                        "name": "id",
                        "description": "User ID",
                        "type": {
                            "kind": "NON_NULL", "name": None,
                            "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None}
                        },
                        "defaultValue": None,
                    }
                ],
                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        spec = _IntrospectionParser().parse(data)
        assert len(spec.endpoints) == 1
        ep = spec.endpoints[0]
        assert ep.operation_id == "getUser"
        assert ep.method == HttpMethod.QUERY

    def test_mutation_field(self) -> None:
        data = _make_introspection(
            mutation_fields=[{
                "name": "createUser",
                "description": "Create user",
                "args": [],
                "type": {"kind": "SCALAR", "name": "Boolean", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        spec = _IntrospectionParser().parse(data)
        mutation = next(e for e in spec.endpoints if e.method == HttpMethod.MUTATION)
        assert mutation.operation_id == "createUser"

    def test_required_arg(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "find",
                "description": "",
                "args": [{
                    "name": "q",
                    "description": "",
                    "type": {"kind": "NON_NULL", "name": None,
                             "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}},
                    "defaultValue": None,
                }],
                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        spec = _IntrospectionParser().parse(data)
        param = spec.endpoints[0].parameters[0]
        assert param.required is True

    def test_optional_arg(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "search",
                "description": "",
                "args": [{
                    "name": "limit",
                    "description": "",
                    "type": {"kind": "SCALAR", "name": "Int", "ofType": None},
                    "defaultValue": None,
                }],
                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        spec = _IntrospectionParser().parse(data)
        param = spec.endpoints[0].parameters[0]
        assert param.required is False

    def test_unwraps_data_envelope(self) -> None:
        inner = _make_introspection(
            query_fields=[{
                "name": "ping",
                "description": "",
                "args": [],
                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        wrapped = {"data": inner}
        spec = _IntrospectionParser().parse(wrapped)
        assert len(spec.endpoints) == 1

    def test_missing_schema_raises(self) -> None:
        from api2mcp.core.exceptions import ParseException
        with pytest.raises(ParseException, match="__schema"):
            _IntrospectionParser().parse({"not": "a schema"})

    def test_list_type_field(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "listItems",
                "description": "",
                "args": [],
                "type": {
                    "kind": "LIST", "name": None,
                    "ofType": {"kind": "SCALAR", "name": "String", "ofType": None}
                },
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        spec = _IntrospectionParser().parse(data)
        resp_schema = spec.endpoints[0].responses[0].schema
        assert resp_schema is not None
        assert resp_schema.type == "array"

    def test_enum_type_field(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "getRole",
                "description": "",
                "args": [],
                "type": {"kind": "ENUM", "name": "Role", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }],
            extra_types=[{
                "kind": "ENUM",
                "name": "Role",
                "description": None,
                "fields": None,
                "inputFields": None,
                "enumValues": [
                    {"name": "ADMIN", "description": None},
                    {"name": "USER", "description": None},
                ],
                "possibleTypes": None,
            }]
        )
        spec = _IntrospectionParser().parse(data)
        resp_schema = spec.endpoints[0].responses[0].schema
        assert resp_schema is not None
        assert resp_schema.type == "string"
        assert set(resp_schema.enum) == {"ADMIN", "USER"}

    def test_validate_good_data(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "ping",
                "description": "",
                "args": [],
                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        errors = _IntrospectionParser().validate(data)
        assert errors == []

    def test_validate_missing_schema(self) -> None:
        errors = _IntrospectionParser().validate({"bad": "data"})
        assert len(errors) > 0

    def test_source_format_is_graphql(self) -> None:
        data = _make_introspection(query_fields=[])
        spec = _IntrospectionParser().parse(data)
        assert spec.source_format == "graphql"


# ---------------------------------------------------------------------------
# Scalar mapping tests
# ---------------------------------------------------------------------------


@pytestmark_gql
class TestScalarMapping:
    def _get_scalar_schema(self, scalar_name: str):
        from graphql.type import GraphQLScalarType
        scalar = GraphQLScalarType(name=scalar_name)
        return _type_to_schema_ref(scalar)

    def test_string_scalar(self) -> None:
        schema = self._get_scalar_schema("String")
        assert schema.type == "string"

    def test_id_scalar(self) -> None:
        schema = self._get_scalar_schema("ID")
        assert schema.type == "string"
        assert schema.format == "id"

    def test_int_scalar(self) -> None:
        schema = self._get_scalar_schema("Int")
        assert schema.type == "integer"

    def test_float_scalar(self) -> None:
        schema = self._get_scalar_schema("Float")
        assert schema.type == "number"

    def test_boolean_scalar(self) -> None:
        schema = self._get_scalar_schema("Boolean")
        assert schema.type == "boolean"

    def test_datetime_scalar(self) -> None:
        schema = self._get_scalar_schema("DateTime")
        assert schema.type == "string"
        assert schema.format == "date-time"

    def test_unknown_custom_scalar(self) -> None:
        schema = self._get_scalar_schema("MyCustomThing")
        assert schema.type == "string"

    def test_json_scalar(self) -> None:
        schema = self._get_scalar_schema("JSON")
        assert schema.type == "object"


# ---------------------------------------------------------------------------
# GraphQLParser (public interface) tests
# ---------------------------------------------------------------------------


class TestGraphQLParserDetect:
    def test_detects_direct_schema(self) -> None:
        parser = GraphQLParser()
        assert parser.detect({"__schema": {"types": []}}) is True

    def test_detects_wrapped_schema(self) -> None:
        parser = GraphQLParser()
        assert parser.detect({"data": {"__schema": {}}}) is True

    def test_does_not_detect_openapi(self) -> None:
        parser = GraphQLParser()
        assert parser.detect({"openapi": "3.0.0"}) is False

    def test_does_not_detect_empty_dict(self) -> None:
        parser = GraphQLParser()
        assert parser.detect({}) is False


class TestGraphQLParserDetectFormat:
    def test_sdl_text(self) -> None:
        fmt, data = GraphQLParser._detect_format("type Query { hello: String }")
        assert fmt == "sdl"
        assert data is None

    def test_introspection_json_string(self) -> None:
        payload = json.dumps({"__schema": {"types": [], "queryType": {"name": "Query"}}})
        fmt, data = GraphQLParser._detect_format(payload)
        assert fmt == "introspection"
        assert data is not None

    def test_wrapped_introspection_json(self) -> None:
        payload = json.dumps({"data": {"__schema": {"types": []}}})
        fmt, data = GraphQLParser._detect_format(payload)
        assert fmt == "introspection"

    def test_invalid_json_falls_back_to_sdl(self) -> None:
        fmt, data = GraphQLParser._detect_format("{ not json !!!! }")
        assert fmt == "sdl"


@pytestmark_gql
class TestGraphQLParserParse:
    @pytest.mark.asyncio
    async def test_parse_sdl_string(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(SIMPLE_SDL)
        assert any(e.operation_id == "hello" for e in spec.endpoints)

    @pytest.mark.asyncio
    async def test_parse_sdl_with_title(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(SIMPLE_SDL, title="My API")
        assert spec.title == "My API"

    @pytest.mark.asyncio
    async def test_parse_introspection_dict_via_json_string(self) -> None:
        data = _make_introspection(
            query_fields=[{
                "name": "ping",
                "description": "",
                "args": [],
                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                "isDeprecated": False,
                "deprecationReason": None,
            }]
        )
        parser = GraphQLParser()
        spec = await parser.parse(json.dumps(data))
        assert any(e.operation_id == "ping" for e in spec.endpoints)

    @pytest.mark.asyncio
    async def test_parse_sdl_file(self, tmp_path: Path) -> None:
        gql_file = tmp_path / "schema.graphql"
        gql_file.write_text(SIMPLE_SDL, encoding="utf-8")
        parser = GraphQLParser()
        spec = await parser.parse(gql_file)
        assert spec.title == "Schema"  # derived from filename

    @pytest.mark.asyncio
    async def test_parse_sets_base_url(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(SIMPLE_SDL, base_url="https://api.example.com")
        assert spec.base_url == "https://api.example.com/graphql"

    @pytest.mark.asyncio
    async def test_validate_valid_sdl(self) -> None:
        parser = GraphQLParser()
        errors = await parser.validate(SIMPLE_SDL)
        assert errors == []

    @pytest.mark.asyncio
    async def test_validate_invalid_sdl(self) -> None:
        parser = GraphQLParser()
        errors = await parser.validate("type Query { broken !!!")
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_custom_graphql_endpoint(self) -> None:
        parser = GraphQLParser(graphql_endpoint="/api/graphql")
        spec = await parser.parse(SIMPLE_SDL)
        assert all("/api/graphql/" in ep.path for ep in spec.endpoints)
