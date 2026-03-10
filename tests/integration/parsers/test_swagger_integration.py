"""Integration tests for the Swagger 2.0 migration parser (F3.2).

Tests full conversion and parsing end-to-end with realistic Swagger specs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from api2mcp.core.ir_schema import HttpMethod, ParameterLocation
from api2mcp.parsers.swagger import MigrationSeverity, SwaggerParser

# ---------------------------------------------------------------------------
# Full Petstore-style Swagger 2.0 fixture
# ---------------------------------------------------------------------------

PETSTORE_SWAGGER: dict[str, Any] = {
    "swagger": "2.0",
    "info": {
        "title": "Petstore",
        "description": "A sample pet store API",
        "version": "1.0.5",
    },
    "host": "petstore.swagger.io",
    "basePath": "/v2",
    "schemes": ["https", "http"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "securityDefinitions": {
        "api_key": {"type": "apiKey", "name": "api_key", "in": "header"},
        "petstore_auth": {
            "type": "oauth2",
            "flow": "implicit",
            "authorizationUrl": "https://petstore.swagger.io/oauth/authorize",
            "scopes": {
                "write:pets": "modify pets in your account",
                "read:pets": "read your pets",
            },
        },
    },
    "definitions": {
        "Pet": {
            "type": "object",
            "required": ["name", "photoUrls"],
            "properties": {
                "id": {"type": "integer", "format": "int64"},
                "name": {"type": "string"},
                "photoUrls": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["available", "pending", "sold"]},
                "category": {"$ref": "#/definitions/Category"},
            },
        },
        "Category": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "format": "int64"},
                "name": {"type": "string"},
            },
        },
        "ApiResponse": {
            "type": "object",
            "properties": {
                "code": {"type": "integer", "format": "int32"},
                "type": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
    "paths": {
        "/pet": {
            "post": {
                "tags": ["pet"],
                "summary": "Add a new pet",
                "operationId": "addPet",
                "security": [{"petstore_auth": ["write:pets"]}],
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "description": "Pet object to add",
                        "required": True,
                        "schema": {"$ref": "#/definitions/Pet"},
                    }
                ],
                "responses": {
                    "201": {"description": "Pet created"},
                    "405": {"description": "Invalid input"},
                },
            },
            "put": {
                "tags": ["pet"],
                "summary": "Update an existing pet",
                "operationId": "updatePet",
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {"$ref": "#/definitions/Pet"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Updated pet",
                        "schema": {"$ref": "#/definitions/Pet"},
                    }
                },
            },
        },
        "/pet/findByStatus": {
            "get": {
                "tags": ["pet"],
                "summary": "Finds Pets by status",
                "operationId": "findPetsByStatus",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "description": "Status values to filter by",
                        "required": True,
                        "type": "array",
                        "items": {"type": "string", "enum": ["available", "pending", "sold"]},
                        "collectionFormat": "multi",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "successful operation",
                        "schema": {
                            "type": "array",
                            "items": {"$ref": "#/definitions/Pet"},
                        },
                    }
                },
            }
        },
        "/pet/{petId}": {
            "get": {
                "tags": ["pet"],
                "summary": "Find pet by ID",
                "operationId": "getPetById",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "description": "ID of pet to return",
                        "required": True,
                        "type": "integer",
                        "format": "int64",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "successful operation",
                        "schema": {"$ref": "#/definitions/Pet"},
                    },
                    "404": {"description": "Pet not found"},
                },
            },
            "delete": {
                "tags": ["pet"],
                "summary": "Deletes a pet",
                "operationId": "deletePet",
                "parameters": [
                    {
                        "name": "api_key",
                        "in": "header",
                        "type": "string",
                    },
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "type": "integer",
                        "format": "int64",
                    },
                ],
                "responses": {"200": {"description": "Pet deleted"}},
            },
        },
        "/pet/{petId}/uploadImage": {
            "post": {
                "tags": ["pet"],
                "summary": "Uploads an image",
                "operationId": "uploadFile",
                "consumes": ["multipart/form-data"],
                "produces": ["application/json"],
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "type": "integer",
                        "format": "int64",
                    },
                    {"name": "additionalMetadata", "in": "formData", "type": "string"},
                    {"name": "file", "in": "formData", "type": "string", "format": "binary"},
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "schema": {"$ref": "#/definitions/ApiResponse"},
                    }
                },
            }
        },
    },
}


# ---------------------------------------------------------------------------
# End-to-end integration tests
# ---------------------------------------------------------------------------


class TestPetstoreSwaggerEndToEnd:
    @pytest.mark.asyncio
    async def test_parse_produces_api_spec(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        assert spec.title == "Petstore"
        assert spec.source_format == "swagger"

    @pytest.mark.asyncio
    async def test_endpoint_count(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        op_ids = {e.operation_id for e in spec.endpoints}
        expected = {
            "addPet", "updatePet", "findPetsByStatus",
            "getPetById", "deletePet", "uploadFile",
        }
        assert expected.issubset(op_ids)

    @pytest.mark.asyncio
    async def test_get_endpoints_use_get_method(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        get_ep = next(e for e in spec.endpoints if e.operation_id == "getPetById")
        assert get_ep.method == HttpMethod.GET

    @pytest.mark.asyncio
    async def test_post_endpoints_use_post_method(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        add_ep = next(e for e in spec.endpoints if e.operation_id == "addPet")
        assert add_ep.method == HttpMethod.POST

    @pytest.mark.asyncio
    async def test_delete_endpoint_uses_delete_method(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        del_ep = next(e for e in spec.endpoints if e.operation_id == "deletePet")
        assert del_ep.method == HttpMethod.DELETE

    @pytest.mark.asyncio
    async def test_path_param_parsed(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        get_ep = next(e for e in spec.endpoints if e.operation_id == "getPetById")
        param_names = {p.name for p in get_ep.parameters}
        assert "petId" in param_names

    @pytest.mark.asyncio
    async def test_path_param_is_required(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        get_ep = next(e for e in spec.endpoints if e.operation_id == "getPetById")
        pet_id = next(p for p in get_ep.parameters if p.name == "petId")
        assert pet_id.required is True

    @pytest.mark.asyncio
    async def test_query_param_location(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        find_ep = next(e for e in spec.endpoints if e.operation_id == "findPetsByStatus")
        status_param = next(p for p in find_ep.parameters if p.name == "status")
        assert status_param.location == ParameterLocation.QUERY

    @pytest.mark.asyncio
    async def test_request_body_created_for_post(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        add_ep = next(e for e in spec.endpoints if e.operation_id == "addPet")
        assert add_ep.request_body is not None

    @pytest.mark.asyncio
    async def test_servers_from_host_basepath(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        urls = [s.url for s in spec.servers]
        assert any("petstore.swagger.io" in url for url in urls)
        assert any("/v2" in url for url in urls)

    @pytest.mark.asyncio
    async def test_auth_schemes_extracted(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        scheme_names = {s.name for s in spec.auth_schemes}
        assert "api_key" in scheme_names or "petstore_auth" in scheme_names

    @pytest.mark.asyncio
    async def test_models_include_pet(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        assert "Pet" in spec.models

    @pytest.mark.asyncio
    async def test_suggestions_include_servers(self) -> None:
        parser = SwaggerParser()
        await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        cats = [s.category for s in parser.last_suggestions]
        assert "servers" in cats

    @pytest.mark.asyncio
    async def test_suggestions_include_oauth2_warning(self) -> None:
        parser = SwaggerParser()
        await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        warning_suggestions = [
            s for s in parser.last_suggestions
            if s.severity == MigrationSeverity.WARNING
        ]
        assert any("OAuth2" in s.message or "oauth" in s.message.lower()
                   for s in warning_suggestions)

    @pytest.mark.asyncio
    async def test_formdata_upload_endpoint(self) -> None:
        parser = SwaggerParser()
        spec = await parser.parse(yaml.dump(PETSTORE_SWAGGER))
        upload_ep = next(e for e in spec.endpoints if e.operation_id == "uploadFile")
        assert upload_ep.request_body is not None


class TestSwaggerParserFromFile:
    @pytest.mark.asyncio
    async def test_parse_yaml_file(self, tmp_path: Path) -> None:
        f = tmp_path / "petstore.yaml"
        f.write_text(yaml.dump(PETSTORE_SWAGGER), encoding="utf-8")
        parser = SwaggerParser()
        spec = await parser.parse(f)
        assert spec.title == "Petstore"
        assert spec.source_format == "swagger"

    @pytest.mark.asyncio
    async def test_parse_json_file(self, tmp_path: Path) -> None:
        f = tmp_path / "petstore.json"
        f.write_text(json.dumps(PETSTORE_SWAGGER), encoding="utf-8")
        parser = SwaggerParser()
        spec = await parser.parse(f)
        assert spec.title == "Petstore"

    @pytest.mark.asyncio
    async def test_missing_file_raises(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = SwaggerParser()
        with pytest.raises(ParseException, match="not found"):
            await parser.parse(Path("/nonexistent/api/swagger.yaml"))

    @pytest.mark.asyncio
    async def test_title_override_from_kwarg(self, tmp_path: Path) -> None:
        f = tmp_path / "petstore.yaml"
        f.write_text(yaml.dump(PETSTORE_SWAGGER), encoding="utf-8")
        parser = SwaggerParser()
        spec = await parser.parse(f, title="Custom Title")
        assert spec.title == "Custom Title"


class TestSwaggerConverterEdgeCases:
    @pytest.mark.asyncio
    async def test_no_security_definitions(self) -> None:
        parser = SwaggerParser()
        swagger: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "getX",
                        "parameters": [],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
        spec = await parser.parse(yaml.dump(swagger))
        assert any(e.operation_id == "getX" for e in spec.endpoints)

    @pytest.mark.asyncio
    async def test_empty_paths(self) -> None:
        parser = SwaggerParser()
        swagger = {
            "swagger": "2.0",
            "info": {"title": "Empty", "version": "0.1"},
            "paths": {},
        }
        spec = await parser.parse(yaml.dump(swagger))
        assert spec.endpoints == []

    @pytest.mark.asyncio
    async def test_multiple_responses(self) -> None:
        parser = SwaggerParser()
        swagger: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "paths": {
                "/items/{id}": {
                    "get": {
                        "operationId": "getItem",
                        "parameters": [
                            {"name": "id", "in": "path", "required": True, "type": "string"}
                        ],
                        "responses": {
                            "200": {"description": "OK", "schema": {"type": "object"}},
                            "404": {"description": "Not found"},
                            "500": {"description": "Server error"},
                        },
                    }
                }
            },
        }
        spec = await parser.parse(yaml.dump(swagger))
        item_ep = next(e for e in spec.endpoints if e.operation_id == "getItem")
        assert len(item_ep.responses) >= 1

    @pytest.mark.asyncio
    async def test_ref_in_response_schema_resolved(self) -> None:
        parser = SwaggerParser()
        swagger: dict[str, Any] = {
            "swagger": "2.0",
            "info": {"title": "T", "version": "1"},
            "definitions": {
                "Item": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                }
            },
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "parameters": [],
                        "responses": {
                            "200": {
                                "description": "ok",
                                "schema": {"$ref": "#/definitions/Item"},
                            }
                        },
                    }
                }
            },
        }
        spec = await parser.parse(yaml.dump(swagger))
        assert any(e.operation_id == "listItems" for e in spec.endpoints)
        # models should include the resolved definition
        assert "Item" in spec.models
