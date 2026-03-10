"""Unit tests for the Postman Collection v2.1 parser (F3.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api2mcp.parsers.postman import (
    PostmanParser,
    _to_operation_id,
    _value_to_schema,
    extract_variables,
    parse_auth,
    substitute_variables,
)
from api2mcp.core.ir_schema import AuthType, HttpMethod, ParameterLocation


# ---------------------------------------------------------------------------
# Minimal collection fixture
# ---------------------------------------------------------------------------

def _make_collection(
    name: str = "Test API",
    items: list[dict[str, Any]] | None = None,
    variables: list[dict[str, Any]] | None = None,
    auth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    col: dict[str, Any] = {
        "info": {
            "name": name,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items or [],
    }
    if variables is not None:
        col["variable"] = variables
    if auth is not None:
        col["auth"] = auth
    return col


def _make_request_item(
    name: str = "Get Users",
    method: str = "GET",
    url: str | dict[str, Any] = "{{baseUrl}}/users",
    headers: list[dict[str, Any]] | None = None,
    body: dict[str, Any] | None = None,
    auth: dict[str, Any] | None = None,
    responses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    req: dict[str, Any] = {
        "name": name,
        "request": {
            "method": method,
            "url": url,
            "header": headers or [],
        },
        "response": responses or [],
    }
    if body:
        req["request"]["body"] = body
    if auth:
        req["request"]["auth"] = auth
    return req


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------


class TestSubstituteVariables:
    def test_single_var(self) -> None:
        assert substitute_variables("{{baseUrl}}/api", {"baseUrl": "https://example.com"}) == \
               "https://example.com/api"

    def test_multiple_vars(self) -> None:
        result = substitute_variables(
            "{{scheme}}://{{host}}/{{path}}",
            {"scheme": "https", "host": "api.example.com", "path": "v1"},
        )
        assert result == "https://api.example.com/v1"

    def test_unknown_var_preserved(self) -> None:
        assert substitute_variables("{{unknown}}", {}) == "{{unknown}}"

    def test_no_vars(self) -> None:
        assert substitute_variables("plain text", {}) == "plain text"

    def test_whitespace_trimmed_in_var_name(self) -> None:
        assert substitute_variables("{{ key }}", {"key": "value"}) == "value"

    def test_empty_string(self) -> None:
        assert substitute_variables("", {"a": "b"}) == ""


class TestExtractVariables:
    def test_basic_extraction(self) -> None:
        items = [
            {"key": "baseUrl", "value": "https://api.example.com"},
            {"key": "token", "value": "secret"},
        ]
        result = extract_variables(items)
        assert result == {"baseUrl": "https://api.example.com", "token": "secret"}

    def test_empty_list(self) -> None:
        assert extract_variables([]) == {}

    def test_none_value_becomes_empty_string(self) -> None:
        items = [{"key": "nullVar", "value": None}]
        result = extract_variables(items)
        assert result["nullVar"] == ""

    def test_non_dict_items_skipped(self) -> None:
        items = ["not_a_dict", {"key": "valid", "value": "yes"}]  # type: ignore[list-item]
        result = extract_variables(items)
        assert result == {"valid": "yes"}

    def test_missing_key_skipped(self) -> None:
        items = [{"value": "orphan"}]
        result = extract_variables(items)
        assert result == {}


# ---------------------------------------------------------------------------
# Auth parsing
# ---------------------------------------------------------------------------


class TestParseAuth:
    def test_bearer(self) -> None:
        auth = {"type": "bearer", "bearer": [{"key": "token", "value": "abc"}]}
        scheme = parse_auth(auth)
        assert scheme is not None
        assert scheme.type == AuthType.HTTP_BEARER
        assert scheme.name == "bearer"

    def test_basic(self) -> None:
        auth = {"type": "basic", "basic": []}
        scheme = parse_auth(auth)
        assert scheme is not None
        assert scheme.type == AuthType.HTTP_BASIC

    def test_apikey_header(self) -> None:
        auth = {
            "type": "apikey",
            "apikey": [
                {"key": "key", "value": "X-API-Key"},
                {"key": "in", "value": "header"},
            ],
        }
        scheme = parse_auth(auth)
        assert scheme is not None
        assert scheme.type == AuthType.API_KEY
        assert scheme.api_key_location == "header"

    def test_oauth2(self) -> None:
        auth = {"type": "oauth2", "oauth2": []}
        scheme = parse_auth(auth)
        assert scheme is not None
        assert scheme.type == AuthType.OAUTH2

    def test_noauth_returns_none(self) -> None:
        assert parse_auth({"type": "noauth"}) is None

    def test_none_returns_none(self) -> None:
        assert parse_auth(None) is None

    def test_empty_dict_returns_none(self) -> None:
        assert parse_auth({}) is None


# ---------------------------------------------------------------------------
# operation_id generation
# ---------------------------------------------------------------------------


class TestToOperationId:
    def test_no_folder(self) -> None:
        assert _to_operation_id("Get Users", []) == "get_users"

    def test_with_folder(self) -> None:
        result = _to_operation_id("Get User", ["Users"])
        assert result == "users_get_user"

    def test_nested_folders(self) -> None:
        result = _to_operation_id("Create Post", ["Blog", "Posts"])
        assert result == "blog_posts_create_post"

    def test_special_chars_removed(self) -> None:
        result = _to_operation_id("Get /users/{id}", [])
        assert "{" not in result and "/" not in result

    def test_lowercase(self) -> None:
        result = _to_operation_id("GET USERS", [])
        assert result == result.lower()

    def test_digit_prefix_escaped(self) -> None:
        result = _to_operation_id("123start", [])
        assert result.startswith("op_") or not result[0].isdigit()

    def test_empty_name(self) -> None:
        result = _to_operation_id("", [])
        assert result == "unnamed_operation"


# ---------------------------------------------------------------------------
# Schema inference
# ---------------------------------------------------------------------------


class TestValueToSchema:
    def test_string(self) -> None:
        assert _value_to_schema("hello").type == "string"

    def test_int(self) -> None:
        assert _value_to_schema(42).type == "integer"

    def test_float(self) -> None:
        assert _value_to_schema(3.14).type == "number"

    def test_bool(self) -> None:
        assert _value_to_schema(True).type == "boolean"

    def test_list(self) -> None:
        s = _value_to_schema([1, 2, 3])
        assert s.type == "array"
        assert s.items is not None
        assert s.items.type == "integer"

    def test_dict(self) -> None:
        s = _value_to_schema({"name": "Alice", "age": 30})
        assert s.type == "object"
        assert "name" in s.properties
        assert s.properties["name"].type == "string"
        assert "age" in s.properties
        assert s.properties["age"].type == "integer"

    def test_empty_list_items_default_string(self) -> None:
        s = _value_to_schema([])
        assert s.type == "array"
        assert s.items is not None
        assert s.items.type == "string"


# ---------------------------------------------------------------------------
# PostmanParser.detect()
# ---------------------------------------------------------------------------


class TestPostmanParserDetect:
    def test_valid_v21(self) -> None:
        parser = PostmanParser()
        doc = _make_collection()
        assert parser.detect(doc) is True

    def test_missing_info(self) -> None:
        parser = PostmanParser()
        assert parser.detect({"item": []}) is False

    def test_missing_item(self) -> None:
        parser = PostmanParser()
        doc = {
            "info": {
                "name": "Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            }
        }
        assert parser.detect(doc) is False

    def test_no_postman_schema(self) -> None:
        parser = PostmanParser()
        doc = {"info": {"name": "Test", "schema": "https://other.com/schema.json"}, "item": []}
        assert parser.detect(doc) is False

    def test_openapi_doc_rejected(self) -> None:
        parser = PostmanParser()
        assert parser.detect({"openapi": "3.0.0", "info": {}, "paths": {}}) is False


# ---------------------------------------------------------------------------
# PostmanParser.validate()
# ---------------------------------------------------------------------------


class TestPostmanParserValidate:
    @pytest.mark.asyncio
    async def test_valid_collection(self) -> None:
        parser = PostmanParser()
        errors = await parser.validate(json.dumps(_make_collection()))
        assert errors == []

    @pytest.mark.asyncio
    async def test_invalid_json(self) -> None:
        parser = PostmanParser()
        errors = await parser.validate("{ not valid json")
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_missing_info_name(self) -> None:
        parser = PostmanParser()
        doc: dict[str, Any] = {
            "info": {
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
            },
            "item": [],
        }
        errors = await parser.validate(json.dumps(doc))
        assert any("info" in e.message.lower() or "name" in e.message.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_missing_item_array(self) -> None:
        parser = PostmanParser()
        doc = {"info": {"name": "T", "schema": "getpostman.com"}}
        errors = await parser.validate(json.dumps(doc))
        assert any("item" in e.message.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        parser = PostmanParser()
        errors = await parser.validate(Path("/nonexistent/collection.json"))
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# PostmanParser.parse() — basics
# ---------------------------------------------------------------------------


class TestPostmanParserParse:
    @pytest.mark.asyncio
    async def test_parse_returns_api_spec(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            name="Pet API",
            items=[_make_request_item("List Pets", "GET", "https://api.example.com/pets")],
        )
        spec = await parser.parse(json.dumps(col))
        assert spec.title == "Pet API"
        assert spec.source_format == "postman"

    @pytest.mark.asyncio
    async def test_title_override(self) -> None:
        parser = PostmanParser()
        col = _make_collection(name="Original")
        spec = await parser.parse(json.dumps(col), title="Custom Title")
        assert spec.title == "Custom Title"

    @pytest.mark.asyncio
    async def test_endpoint_count(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            _make_request_item("Get A", "GET", "https://api.example.com/a"),
            _make_request_item("Get B", "GET", "https://api.example.com/b"),
        ])
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 2

    @pytest.mark.asyncio
    async def test_http_method_mapping(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            _make_request_item("Create", "POST", "https://api.example.com/items"),
            _make_request_item("Update", "PUT", "https://api.example.com/items/1"),
            _make_request_item("Delete", "DELETE", "https://api.example.com/items/1"),
        ])
        spec = await parser.parse(json.dumps(col))
        methods = {e.method for e in spec.endpoints}
        assert HttpMethod.POST in methods
        assert HttpMethod.PUT in methods
        assert HttpMethod.DELETE in methods

    @pytest.mark.asyncio
    async def test_source_format_is_postman(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(_make_collection()))
        assert spec.source_format == "postman"

    @pytest.mark.asyncio
    async def test_raises_for_non_postman(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = PostmanParser()
        oas3 = {"openapi": "3.0.0", "info": {"title": "X", "version": "1"}, "paths": {}}
        with pytest.raises(ParseException):
            await parser.parse(json.dumps(oas3))

    @pytest.mark.asyncio
    async def test_raises_for_missing_file(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = PostmanParser()
        with pytest.raises(ParseException):
            await parser.parse(Path("/nonexistent/collection.json"))

    @pytest.mark.asyncio
    async def test_empty_collection(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(_make_collection()))
        assert spec.endpoints == []


# ---------------------------------------------------------------------------
# Variable substitution in parse()
# ---------------------------------------------------------------------------


class TestPostmanParserVariables:
    @pytest.mark.asyncio
    async def test_base_url_substituted(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "{{baseUrl}}/users")],
            variables=[{"key": "baseUrl", "value": "https://api.example.com"}],
        )
        spec = await parser.parse(json.dumps(col))
        assert any("api.example.com" in s.url for s in spec.servers)

    @pytest.mark.asyncio
    async def test_unknown_variable_left_as_placeholder(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "{{unknownUrl}}/users")],
        )
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 1  # endpoint still created


# ---------------------------------------------------------------------------
# Folder hierarchy → tags
# ---------------------------------------------------------------------------


class TestPostmanParserFolders:
    @pytest.mark.asyncio
    async def test_folder_becomes_tag(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            {
                "name": "Users",
                "item": [
                    _make_request_item("Get User", "GET", "https://api.example.com/users/1"),
                ],
            }
        ])
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 1
        assert "Users" in spec.endpoints[0].tags

    @pytest.mark.asyncio
    async def test_nested_folders(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            {
                "name": "API",
                "item": [
                    {
                        "name": "Users",
                        "item": [
                            _make_request_item("List", "GET", "https://api.example.com/users"),
                        ],
                    }
                ],
            }
        ])
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 1
        ep = spec.endpoints[0]
        assert "api" in ep.operation_id or "users" in ep.operation_id

    @pytest.mark.asyncio
    async def test_folder_operation_id_includes_folder_name(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            {
                "name": "Products",
                "item": [
                    _make_request_item("List Products", "GET", "https://api.example.com/products"),
                ],
            }
        ])
        spec = await parser.parse(json.dumps(col))
        assert "products" in spec.endpoints[0].operation_id


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


class TestPostmanParserParameters:
    @pytest.mark.asyncio
    async def test_query_params_extracted(self) -> None:
        parser = PostmanParser()
        url_obj = {
            "raw": "https://api.example.com/users",
            "query": [
                {"key": "limit", "value": "10", "description": "Max results"},
                {"key": "offset", "value": "0"},
            ],
        }
        col = _make_collection(items=[_make_request_item("List", "GET", url_obj)])
        spec = await parser.parse(json.dumps(col))
        param_names = {p.name for p in spec.endpoints[0].parameters}
        assert "limit" in param_names
        assert "offset" in param_names

    @pytest.mark.asyncio
    async def test_query_param_location(self) -> None:
        parser = PostmanParser()
        url_obj = {
            "raw": "https://api.example.com/users",
            "query": [{"key": "filter", "value": "active"}],
        }
        col = _make_collection(items=[_make_request_item("List", "GET", url_obj)])
        spec = await parser.parse(json.dumps(col))
        filter_param = next(p for p in spec.endpoints[0].parameters if p.name == "filter")
        assert filter_param.location == ParameterLocation.QUERY

    @pytest.mark.asyncio
    async def test_path_variables_from_url_object(self) -> None:
        parser = PostmanParser()
        url_obj = {
            "raw": "https://api.example.com/users/:id",
            "path": ["users", ":id"],
            "variable": [{"key": "id", "value": "", "description": "User ID"}],
        }
        col = _make_collection(items=[_make_request_item("Get User", "GET", url_obj)])
        spec = await parser.parse(json.dumps(col))
        path_params = [p for p in spec.endpoints[0].parameters if p.location == ParameterLocation.PATH]
        assert any(p.name == "id" for p in path_params)

    @pytest.mark.asyncio
    async def test_path_variables_from_braces(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            _make_request_item("Get Item", "GET", "https://api.example.com/items/{itemId}")
        ])
        spec = await parser.parse(json.dumps(col))
        path_params = [p for p in spec.endpoints[0].parameters if p.location == ParameterLocation.PATH]
        assert any(p.name == "itemId" for p in path_params)

    @pytest.mark.asyncio
    async def test_disabled_query_params_excluded(self) -> None:
        parser = PostmanParser()
        url_obj = {
            "raw": "https://api.example.com/users",
            "query": [
                {"key": "active", "value": "true", "disabled": True},
                {"key": "limit", "value": "10"},
            ],
        }
        col = _make_collection(items=[_make_request_item("List", "GET", url_obj)])
        spec = await parser.parse(json.dumps(col))
        param_names = {p.name for p in spec.endpoints[0].parameters}
        assert "active" not in param_names
        assert "limit" in param_names

    @pytest.mark.asyncio
    async def test_custom_headers_extracted(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            _make_request_item(
                "List",
                "GET",
                "https://api.example.com/users",
                headers=[{"key": "X-Custom-Header", "value": "val"}],
            )
        ])
        spec = await parser.parse(json.dumps(col))
        header_params = [p for p in spec.endpoints[0].parameters if p.location == ParameterLocation.HEADER]
        assert any(p.name == "X-Custom-Header" for p in header_params)

    @pytest.mark.asyncio
    async def test_standard_headers_excluded(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            _make_request_item(
                "List",
                "GET",
                "https://api.example.com/users",
                headers=[
                    {"key": "Content-Type", "value": "application/json"},
                    {"key": "Authorization", "value": "Bearer token"},
                ],
            )
        ])
        spec = await parser.parse(json.dumps(col))
        header_params = [p for p in spec.endpoints[0].parameters if p.location == ParameterLocation.HEADER]
        names = {p.name.lower() for p in header_params}
        assert "content-type" not in names
        assert "authorization" not in names


# ---------------------------------------------------------------------------
# Request body parsing
# ---------------------------------------------------------------------------


class TestPostmanParserBody:
    @pytest.mark.asyncio
    async def test_raw_json_body(self) -> None:
        parser = PostmanParser()
        body = {
            "mode": "raw",
            "raw": '{"name": "Alice", "age": 30}',
            "options": {"raw": {"language": "json"}},
        }
        col = _make_collection(items=[
            _make_request_item("Create", "POST", "https://api.example.com/users", body=body)
        ])
        spec = await parser.parse(json.dumps(col))
        ep = spec.endpoints[0]
        assert ep.request_body is not None
        assert ep.request_body.content_type == "application/json"
        assert ep.request_body.schema.type == "object"

    @pytest.mark.asyncio
    async def test_raw_text_body(self) -> None:
        parser = PostmanParser()
        body = {
            "mode": "raw",
            "raw": "plain text content",
            "options": {"raw": {"language": "text"}},
        }
        col = _make_collection(items=[
            _make_request_item("Send", "POST", "https://api.example.com/msg", body=body)
        ])
        spec = await parser.parse(json.dumps(col))
        assert spec.endpoints[0].request_body is not None
        assert spec.endpoints[0].request_body.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_formdata_body(self) -> None:
        parser = PostmanParser()
        body = {
            "mode": "formdata",
            "formdata": [
                {"key": "name", "value": "Alice", "type": "text"},
                {"key": "avatar", "type": "file"},
            ],
        }
        col = _make_collection(items=[
            _make_request_item("Upload", "POST", "https://api.example.com/users", body=body)
        ])
        spec = await parser.parse(json.dumps(col))
        rb = spec.endpoints[0].request_body
        assert rb is not None
        assert rb.content_type == "multipart/form-data"
        assert "name" in rb.schema.properties

    @pytest.mark.asyncio
    async def test_urlencoded_body(self) -> None:
        parser = PostmanParser()
        body = {
            "mode": "urlencoded",
            "urlencoded": [
                {"key": "username", "value": "alice"},
                {"key": "password", "value": "secret"},
            ],
        }
        col = _make_collection(items=[
            _make_request_item("Login", "POST", "https://api.example.com/auth", body=body)
        ])
        spec = await parser.parse(json.dumps(col))
        rb = spec.endpoints[0].request_body
        assert rb is not None
        assert rb.content_type == "application/x-www-form-urlencoded"

    @pytest.mark.asyncio
    async def test_no_body_for_get(self) -> None:
        parser = PostmanParser()
        col = _make_collection(items=[
            _make_request_item("List", "GET", "https://api.example.com/users")
        ])
        spec = await parser.parse(json.dumps(col))
        assert spec.endpoints[0].request_body is None

    @pytest.mark.asyncio
    async def test_disabled_formdata_fields_excluded(self) -> None:
        parser = PostmanParser()
        body = {
            "mode": "formdata",
            "formdata": [
                {"key": "active", "value": "yes", "disabled": True},
                {"key": "name", "value": "Alice"},
            ],
        }
        col = _make_collection(items=[
            _make_request_item("Create", "POST", "https://api.example.com/users", body=body)
        ])
        spec = await parser.parse(json.dumps(col))
        props = spec.endpoints[0].request_body.schema.properties  # type: ignore[union-attr]
        assert "active" not in props
        assert "name" in props


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestPostmanParserAuth:
    @pytest.mark.asyncio
    async def test_collection_level_auth_extracted(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "https://api.example.com/users")],
            auth={"type": "bearer", "bearer": [{"key": "token", "value": "secret"}]},
        )
        spec = await parser.parse(json.dumps(col))
        assert len(spec.auth_schemes) >= 1
        assert any(s.type == AuthType.HTTP_BEARER for s in spec.auth_schemes)

    @pytest.mark.asyncio
    async def test_collection_auth_applied_to_endpoints(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "https://api.example.com/users")],
            auth={"type": "bearer", "bearer": []},
        )
        spec = await parser.parse(json.dumps(col))
        ep = spec.endpoints[0]
        assert len(ep.security) > 0

    @pytest.mark.asyncio
    async def test_request_auth_overrides_collection(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[
                _make_request_item(
                    "List",
                    "GET",
                    "https://api.example.com/users",
                    auth={"type": "apikey", "apikey": [
                        {"key": "key", "value": "X-Custom-Key"},
                        {"key": "in", "value": "header"},
                    ]},
                )
            ],
            auth={"type": "bearer", "bearer": []},
        )
        spec = await parser.parse(json.dumps(col))
        ep = spec.endpoints[0]
        # The endpoint's security should reflect the request-level auth (apikey)
        sec_names = {k for s in ep.security for k in s}
        assert "apiKey" in sec_names

    @pytest.mark.asyncio
    async def test_no_auth(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "https://api.example.com/users")],
        )
        spec = await parser.parse(json.dumps(col))
        assert spec.auth_schemes == []


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


class TestPostmanParserServers:
    @pytest.mark.asyncio
    async def test_servers_extracted(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "https://api.example.com/users")],
        )
        spec = await parser.parse(json.dumps(col))
        assert len(spec.servers) >= 1
        assert any("api.example.com" in s.url for s in spec.servers)

    @pytest.mark.asyncio
    async def test_base_url_set(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "https://api.example.com/users")],
        )
        spec = await parser.parse(json.dumps(col))
        assert "api.example.com" in spec.base_url

    @pytest.mark.asyncio
    async def test_variable_base_url(self) -> None:
        parser = PostmanParser()
        col = _make_collection(
            items=[_make_request_item("List", "GET", "{{baseUrl}}/users")],
            variables=[{"key": "baseUrl", "value": "https://api.example.com"}],
        )
        spec = await parser.parse(json.dumps(col))
        assert any("api.example.com" in s.url for s in spec.servers)


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


class TestPostmanParserFileLoading:
    @pytest.mark.asyncio
    async def test_parse_from_file(self, tmp_path: Path) -> None:
        f = tmp_path / "collection.json"
        col = _make_collection(
            items=[_make_request_item("List", "GET", "https://api.example.com/users")]
        )
        f.write_text(json.dumps(col), encoding="utf-8")
        parser = PostmanParser()
        spec = await parser.parse(f)
        assert spec.source_format == "postman"
        assert len(spec.endpoints) == 1

    @pytest.mark.asyncio
    async def test_parse_missing_file_raises(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = PostmanParser()
        with pytest.raises(ParseException, match="not found"):
            await parser.parse(Path("/nonexistent/collection.json"))
