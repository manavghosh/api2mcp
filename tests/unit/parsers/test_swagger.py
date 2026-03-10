"""Unit tests for the Swagger 2.0 migration parser (F3.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from api2mcp.parsers.swagger import (
    MigrationSeverity,
    MigrationSuggestion,
    SwaggerConverter,
    SwaggerParser,
)


# ---------------------------------------------------------------------------
# Minimal Swagger 2.0 fixture
# ---------------------------------------------------------------------------

MINIMAL_SWAGGER: dict[str, Any] = {
    "swagger": "2.0",
    "info": {"title": "Pets API", "version": "1.0.0"},
    "host": "petstore.example.com",
    "basePath": "/v2",
    "schemes": ["https"],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [
                    {"name": "limit", "in": "query", "type": "integer", "required": False},
                ],
                "responses": {"200": {"description": "A list of pets"}},
            }
        }
    },
}


# ---------------------------------------------------------------------------
# SwaggerParser.detect()
# ---------------------------------------------------------------------------


class TestSwaggerParserDetect:
    def test_detects_swagger_20(self) -> None:
        parser = SwaggerParser()
        assert parser.detect({"swagger": "2.0"}) is True

    def test_rejects_openapi_30(self) -> None:
        parser = SwaggerParser()
        assert parser.detect({"openapi": "3.0.3"}) is False

    def test_rejects_swagger_10(self) -> None:
        parser = SwaggerParser()
        assert parser.detect({"swagger": "1.0"}) is False

    def test_rejects_empty_dict(self) -> None:
        parser = SwaggerParser()
        assert parser.detect({}) is False

    def test_rejects_none_value(self) -> None:
        parser = SwaggerParser()
        assert parser.detect({"swagger": None}) is False


# ---------------------------------------------------------------------------
# SwaggerParser.validate()
# ---------------------------------------------------------------------------


class TestSwaggerParserValidate:
    @pytest.mark.asyncio
    async def test_valid_swagger(self) -> None:
        parser = SwaggerParser()
        src = yaml.dump(MINIMAL_SWAGGER)
        errors = await parser.validate(src)
        assert errors == []

    @pytest.mark.asyncio
    async def test_missing_swagger_field(self) -> None:
        parser = SwaggerParser()
        doc = {"openapi": "3.0.0", "info": {"title": "X", "version": "1"}, "paths": {}}
        errors = await parser.validate(yaml.dump(doc))
        assert any("swagger" in e.message.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_missing_info_field(self) -> None:
        parser = SwaggerParser()
        doc = {"swagger": "2.0", "paths": {}}
        errors = await parser.validate(yaml.dump(doc))
        assert any("info" in e.message.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_missing_paths_field(self) -> None:
        parser = SwaggerParser()
        doc = {"swagger": "2.0", "info": {"title": "X", "version": "1"}}
        errors = await parser.validate(yaml.dump(doc))
        assert any("paths" in e.message.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_invalid_yaml_returns_errors(self) -> None:
        parser = SwaggerParser()
        errors = await parser.validate("{ unclosed yaml: [")
        assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_file_not_found_returns_errors(self) -> None:
        parser = SwaggerParser()
        errors = await parser.validate(Path("/nonexistent/swagger.yaml"))
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# SwaggerConverter — servers
# ---------------------------------------------------------------------------


class TestSwaggerConverterServers:
    def test_single_scheme(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            {
                "swagger": "2.0",
                "info": {"title": "T", "version": "1"},
                "host": "api.example.com",
                "basePath": "/v1",
                "schemes": ["https"],
                "paths": {},
            }
        )
        assert doc["servers"] == [{"url": "https://api.example.com/v1"}]

    def test_multiple_schemes(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            {
                "swagger": "2.0",
                "info": {"title": "T", "version": "1"},
                "host": "api.example.com",
                "basePath": "/",
                "schemes": ["https", "http"],
                "paths": {},
            }
        )
        urls = [s["url"] for s in doc["servers"]]
        assert "https://api.example.com/" in urls
        assert "http://api.example.com/" in urls

    def test_default_server_when_no_host(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            {"swagger": "2.0", "info": {"title": "T", "version": "1"}, "paths": {}}
        )
        assert len(doc["servers"]) == 1
        assert "localhost" in doc["servers"][0]["url"]

    def test_server_suggestion_emitted(self) -> None:
        converter = SwaggerConverter()
        _, suggestions = converter.convert(
            {
                "swagger": "2.0",
                "info": {"title": "T", "version": "1"},
                "host": "example.com",
                "basePath": "/api",
                "schemes": ["https"],
                "paths": {},
            }
        )
        cats = [s.category for s in suggestions]
        assert "servers" in cats


# ---------------------------------------------------------------------------
# SwaggerConverter — $ref rewriting
# ---------------------------------------------------------------------------


class TestSwaggerConverterRefRewrite:
    def test_definitions_refs_rewritten(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            {
                "swagger": "2.0",
                "info": {"title": "T", "version": "1"},
                "definitions": {
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "owner": {"$ref": "#/definitions/Owner"}
                        },
                    },
                    "Owner": {"type": "object"},
                },
                "paths": {},
            }
        )
        pet_schema = doc["components"]["schemas"]["Pet"]
        assert pet_schema["properties"]["owner"]["$ref"] == "#/components/schemas/Owner"

    def test_path_schema_refs_rewritten(self) -> None:
        converter = SwaggerConverter()
        swagger = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "definitions": {"Dog": {"type": "object"}},
            "paths": {
                "/dogs": {
                    "get": {
                        "operationId": "getDogs",
                        "parameters": [],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "schema": {"$ref": "#/definitions/Dog"},
                            }
                        },
                    }
                }
            },
        }
        doc, _ = converter.convert(swagger)
        resp_schema = doc["paths"]["/dogs"]["get"]["responses"]["200"]["content"]
        # at least one media type contains the ref
        refs = [
            mt["schema"]["$ref"]
            for mt in resp_schema.values()
            if "$ref" in mt.get("schema", {})
        ]
        assert any("#/components/schemas/Dog" in r for r in refs)


# ---------------------------------------------------------------------------
# SwaggerConverter — definitions / components
# ---------------------------------------------------------------------------


class TestSwaggerConverterComponents:
    def test_definitions_moved_to_components_schemas(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            {
                "swagger": "2.0",
                "info": {"title": "T", "version": "1"},
                "definitions": {"Cat": {"type": "object"}},
                "paths": {},
            }
        )
        assert "components" in doc
        assert "Cat" in doc["components"]["schemas"]

    def test_no_components_when_no_definitions(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            {"swagger": "2.0", "info": {"title": "T", "version": "1"}, "paths": {}}
        )
        assert "components" not in doc


# ---------------------------------------------------------------------------
# SwaggerConverter — body parameter → requestBody
# ---------------------------------------------------------------------------


class TestSwaggerConverterBodyParam:
    def _swagger_with_body(
        self, body_param: dict[str, Any], consumes: list[str] | None = None
    ) -> dict[str, Any]:
        sw: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/items": {
                    "post": {
                        "operationId": "createItem",
                        "parameters": [body_param],
                        "responses": {"201": {"description": "created"}},
                    }
                }
            },
        }
        if consumes:
            sw["paths"]["/items"]["post"]["consumes"] = consumes
        return sw

    def test_body_param_becomes_request_body(self) -> None:
        converter = SwaggerConverter()
        swagger = self._swagger_with_body(
            {
                "name": "body",
                "in": "body",
                "required": True,
                "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        )
        doc, _ = converter.convert(swagger)
        op = doc["paths"]["/items"]["post"]
        assert "requestBody" in op
        assert op["requestBody"]["required"] is True

    def test_body_param_default_content_type_json(self) -> None:
        converter = SwaggerConverter()
        swagger = self._swagger_with_body(
            {"name": "body", "in": "body", "schema": {"type": "object"}}
        )
        doc, _ = converter.convert(swagger)
        content = doc["paths"]["/items"]["post"]["requestBody"]["content"]
        assert "application/json" in content

    def test_body_param_respects_consumes(self) -> None:
        converter = SwaggerConverter()
        swagger = self._swagger_with_body(
            {"name": "body", "in": "body", "schema": {"type": "object"}},
            consumes=["application/xml"],
        )
        doc, _ = converter.convert(swagger)
        content = doc["paths"]["/items"]["post"]["requestBody"]["content"]
        assert "application/xml" in content

    def test_body_param_suggestion_emitted(self) -> None:
        converter = SwaggerConverter()
        swagger = self._swagger_with_body(
            {"name": "body", "in": "body", "schema": {"type": "object"}}
        )
        _, suggestions = converter.convert(swagger)
        cats = [s.category for s in suggestions]
        assert "body-param" in cats

    def test_form_data_params_merged(self) -> None:
        converter = SwaggerConverter()
        swagger = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/upload": {
                    "post": {
                        "operationId": "upload",
                        "parameters": [
                            {"name": "file", "in": "formData", "type": "string", "required": True},
                            {"name": "caption", "in": "formData", "type": "string"},
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        doc, suggestions = converter.convert(swagger)
        op = doc["paths"]["/upload"]["post"]
        assert "requestBody" in op
        content = op["requestBody"]["content"]
        assert "application/x-www-form-urlencoded" in content or "multipart/form-data" in content
        cats = [s.category for s in suggestions]
        assert "form-data" in cats

    def test_form_data_multipart_when_consumes_multipart(self) -> None:
        converter = SwaggerConverter()
        swagger = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/upload": {
                    "post": {
                        "operationId": "upload",
                        "consumes": ["multipart/form-data"],
                        "parameters": [
                            {"name": "file", "in": "formData", "type": "string"},
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        doc, _ = converter.convert(swagger)
        content = doc["paths"]["/upload"]["post"]["requestBody"]["content"]
        assert "multipart/form-data" in content


# ---------------------------------------------------------------------------
# SwaggerConverter — query / path parameters
# ---------------------------------------------------------------------------


class TestSwaggerConverterParameters:
    def test_query_param_converted(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(MINIMAL_SWAGGER)
        params = doc["paths"]["/pets"]["get"]["parameters"]
        assert any(p["name"] == "limit" and p["in"] == "query" for p in params)

    def test_query_param_schema_inlined(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(MINIMAL_SWAGGER)
        params = doc["paths"]["/pets"]["get"]["parameters"]
        limit = next(p for p in params if p["name"] == "limit")
        assert "schema" in limit
        assert limit["schema"]["type"] == "integer"

    def test_path_param_preserved(self) -> None:
        converter = SwaggerConverter()
        swagger: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/pets/{id}": {
                    "get": {
                        "operationId": "getPet",
                        "parameters": [
                            {"name": "id", "in": "path", "required": True, "type": "string"}
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        doc, _ = converter.convert(swagger)
        params = doc["paths"]["/pets/{id}"]["get"]["parameters"]
        id_param = next(p for p in params if p["name"] == "id")
        assert id_param["in"] == "path"
        assert id_param["required"] is True
        assert id_param["schema"]["type"] == "string"


# ---------------------------------------------------------------------------
# SwaggerConverter — security definitions
# ---------------------------------------------------------------------------


class TestSwaggerConverterSecurity:
    def _swagger_with_security(self, sec_def: dict[str, Any]) -> dict[str, Any]:
        return {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "securityDefinitions": {"myAuth": sec_def},
            "paths": {},
        }

    def test_apikey_converted(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            self._swagger_with_security(
                {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            )
        )
        scheme = doc["components"]["securitySchemes"]["myAuth"]
        assert scheme["type"] == "apiKey"
        assert scheme["in"] == "header"
        assert scheme["name"] == "X-API-Key"

    def test_basic_auth_converted(self) -> None:
        converter = SwaggerConverter()
        doc, suggestions = converter.convert(
            self._swagger_with_security({"type": "basic"})
        )
        scheme = doc["components"]["securitySchemes"]["myAuth"]
        assert scheme["type"] == "http"
        assert scheme["scheme"] == "basic"
        cats = [s.category for s in suggestions]
        assert "security" in cats

    def test_oauth2_implicit_converted(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            self._swagger_with_security(
                {
                    "type": "oauth2",
                    "flow": "implicit",
                    "authorizationUrl": "https://auth.example.com/oauth",
                    "scopes": {"read": "Read access"},
                }
            )
        )
        scheme = doc["components"]["securitySchemes"]["myAuth"]
        assert scheme["type"] == "oauth2"
        assert "implicit" in scheme["flows"]
        assert scheme["flows"]["implicit"]["authorizationUrl"] == "https://auth.example.com/oauth"

    def test_oauth2_access_code_becomes_authorization_code(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            self._swagger_with_security(
                {
                    "type": "oauth2",
                    "flow": "accessCode",
                    "authorizationUrl": "https://auth.example.com/oauth",
                    "tokenUrl": "https://auth.example.com/token",
                    "scopes": {},
                }
            )
        )
        scheme = doc["components"]["securitySchemes"]["myAuth"]
        assert "authorizationCode" in scheme["flows"]

    def test_oauth2_application_becomes_client_credentials(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(
            self._swagger_with_security(
                {
                    "type": "oauth2",
                    "flow": "application",
                    "tokenUrl": "https://auth.example.com/token",
                    "scopes": {},
                }
            )
        )
        scheme = doc["components"]["securitySchemes"]["myAuth"]
        assert "clientCredentials" in scheme["flows"]

    def test_oauth2_suggestion_has_warning_severity(self) -> None:
        converter = SwaggerConverter()
        _, suggestions = converter.convert(
            self._swagger_with_security(
                {
                    "type": "oauth2",
                    "flow": "password",
                    "tokenUrl": "https://auth.example.com/token",
                    "scopes": {},
                }
            )
        )
        oauth_sug = next(
            (s for s in suggestions if s.category == "security" and "OAuth2" in s.message),
            None,
        )
        assert oauth_sug is not None
        assert oauth_sug.severity == MigrationSeverity.WARNING


# ---------------------------------------------------------------------------
# SwaggerConverter — produces → response content
# ---------------------------------------------------------------------------


class TestSwaggerConverterProduces:
    def test_produces_becomes_content_key(self) -> None:
        converter = SwaggerConverter()
        swagger: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "produces": ["application/xml"],
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "parameters": [],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "schema": {"type": "array", "items": {"type": "string"}},
                            }
                        },
                    }
                }
            },
        }
        doc, _ = converter.convert(swagger)
        content = doc["paths"]["/pets"]["get"]["responses"]["200"]["content"]
        assert "application/xml" in content

    def test_op_level_produces_overrides_global(self) -> None:
        converter = SwaggerConverter()
        swagger = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "produces": ["application/json"],
            "paths": {
                "/csv": {
                    "get": {
                        "operationId": "getCsv",
                        "produces": ["text/csv"],
                        "parameters": [],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "schema": {"type": "string"},
                            }
                        },
                    }
                }
            },
        }
        doc, _ = converter.convert(swagger)
        content = doc["paths"]["/csv"]["get"]["responses"]["200"]["content"]
        assert "text/csv" in content
        assert "application/json" not in content


# ---------------------------------------------------------------------------
# SwaggerConverter — OAS3 structural correctness
# ---------------------------------------------------------------------------


class TestSwaggerConverterStructure:
    def test_output_has_openapi_30_version(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(MINIMAL_SWAGGER)
        assert doc["openapi"] == "3.0.3"

    def test_info_preserved(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(MINIMAL_SWAGGER)
        assert doc["info"]["title"] == "Pets API"
        assert doc["info"]["version"] == "1.0.0"

    def test_tags_preserved(self) -> None:
        converter = SwaggerConverter()
        swagger = {**MINIMAL_SWAGGER, "tags": [{"name": "pets", "description": "Pet operations"}]}
        doc, _ = converter.convert(swagger)
        assert doc["tags"] == [{"name": "pets", "description": "Pet operations"}]

    def test_operation_id_preserved(self) -> None:
        converter = SwaggerConverter()
        doc, _ = converter.convert(MINIMAL_SWAGGER)
        assert doc["paths"]["/pets"]["get"]["operationId"] == "listPets"


# ---------------------------------------------------------------------------
# SwaggerParser.parse() — end-to-end
# ---------------------------------------------------------------------------


class TestSwaggerParserParse:
    @pytest.mark.asyncio
    async def test_parse_yaml_string(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(MINIMAL_SWAGGER))
        assert spec.source_format == "swagger"
        assert any(e.operation_id == "listPets" for e in spec.endpoints)

    @pytest.mark.asyncio
    async def test_parse_json_string(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(json.dumps(MINIMAL_SWAGGER))
        assert spec.source_format == "swagger"

    @pytest.mark.asyncio
    async def test_parse_sets_title_from_info(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(MINIMAL_SWAGGER))
        assert spec.title == "Pets API"

    @pytest.mark.asyncio
    async def test_parse_title_override(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(MINIMAL_SWAGGER), title="Overridden Title")
        assert spec.title == "Overridden Title"

    @pytest.mark.asyncio
    async def test_parse_from_file_yaml(self, tmp_path: Path) -> None:
        f = tmp_path / "petstore.yaml"
        f.write_text(yaml.dump(MINIMAL_SWAGGER), encoding="utf-8")
        parser = SwaggerParser()
        spec = await parser.parse(f)
        assert spec.source_format == "swagger"

    @pytest.mark.asyncio
    async def test_parse_from_file_json(self, tmp_path: Path) -> None:
        f = tmp_path / "petstore.json"
        f.write_text(json.dumps(MINIMAL_SWAGGER), encoding="utf-8")
        parser = SwaggerParser()
        spec = await parser.parse(f)
        assert spec.source_format == "swagger"

    @pytest.mark.asyncio
    async def test_parse_raises_for_non_swagger(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = SwaggerParser()
        oas3 = {"openapi": "3.0.0", "info": {"title": "X", "version": "1"}, "paths": {}}
        with pytest.raises(ParseException):
            await parser.parse(yaml.dump(oas3))

    @pytest.mark.asyncio
    async def test_parse_raises_for_missing_file(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = SwaggerParser()
        with pytest.raises(ParseException):
            await parser.parse(Path("/nonexistent/swagger.yaml"))

    @pytest.mark.asyncio
    async def test_last_suggestions_populated(self) -> None:
        parser = SwaggerParser()
        await parser.parse(yaml.dump(MINIMAL_SWAGGER))
        # At least a "servers" suggestion
        assert len(parser.last_suggestions) >= 1

    @pytest.mark.asyncio
    async def test_last_suggestions_reset_on_each_parse(self) -> None:
        parser = SwaggerParser()
        simple: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {},
        }
        await parser.parse(yaml.dump(MINIMAL_SWAGGER))
        count_first = len(parser.last_suggestions)
        await parser.parse(yaml.dump(simple))
        count_second = len(parser.last_suggestions)
        # second parse has fewer suggestions (no host/schemes)
        assert count_second <= count_first


# ---------------------------------------------------------------------------
# MigrationSuggestion model
# ---------------------------------------------------------------------------


class TestMigrationSuggestion:
    def test_default_severity_is_info(self) -> None:
        s = MigrationSuggestion(category="test", message="hello")
        assert s.severity == MigrationSeverity.INFO

    def test_default_path_is_empty(self) -> None:
        s = MigrationSuggestion(category="test", message="hello")
        assert s.path == ""

    def test_warning_severity(self) -> None:
        s = MigrationSuggestion(
            category="sec", message="check oauth", severity=MigrationSeverity.WARNING
        )
        assert s.severity == MigrationSeverity.WARNING
