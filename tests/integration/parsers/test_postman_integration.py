"""Integration tests for the Postman Collection parser (F3.3).

Tests full collection parsing end-to-end with realistic collections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api2mcp.core.ir_schema import AuthType, HttpMethod, ParameterLocation
from api2mcp.parsers.postman import PostmanParser

# ---------------------------------------------------------------------------
# Realistic Postman Collection v2.1 fixture — "Todo API"
# ---------------------------------------------------------------------------

TODO_COLLECTION: dict[str, Any] = {
    "info": {
        "name": "Todo API",
        "description": "A simple Todo REST API",
        "version": "2.0.0",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "variable": [
        {"key": "baseUrl", "value": "https://api.todo.example.com"},
        {"key": "apiVersion", "value": "v2"},
        {"key": "defaultLimit", "value": "25"},
    ],
    "auth": {
        "type": "bearer",
        "bearer": [{"key": "token", "value": "{{authToken}}", "type": "string"}],
    },
    "item": [
        # Folder: Todos
        {
            "name": "Todos",
            "description": "Todo item operations",
            "item": [
                {
                    "name": "List Todos",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/todos?limit={{defaultLimit}}&offset=0",
                            "protocol": "https",
                            "host": ["{{baseUrl}}"],
                            "path": ["{{apiVersion}}", "todos"],
                            "query": [
                                {"key": "limit", "value": "{{defaultLimit}}", "description": "Max results"},
                                {"key": "offset", "value": "0", "description": "Skip count"},
                                {"key": "status", "value": "", "description": "Filter by status", "disabled": True},
                            ],
                        },
                        "header": [
                            {"key": "Accept", "value": "application/json"},
                            {"key": "X-Request-ID", "value": "{{$guid}}"},
                        ],
                        "description": "Retrieve a list of todos with pagination",
                    },
                    "response": [
                        {
                            "name": "Success",
                            "status": "OK",
                            "code": 200,
                            "body": '[{"id": 1, "title": "Buy milk", "done": false}]',
                        }
                    ],
                },
                {
                    "name": "Get Todo",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/todos/:id",
                            "protocol": "https",
                            "host": ["{{baseUrl}}"],
                            "path": ["{{apiVersion}}", "todos", ":id"],
                            "variable": [
                                {"key": "id", "value": "", "description": "Todo ID"},
                            ],
                        },
                        "header": [],
                        "description": "Get a single todo item by ID",
                    },
                    "response": [],
                },
                {
                    "name": "Create Todo",
                    "request": {
                        "method": "POST",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/todos",
                            "protocol": "https",
                            "host": ["{{baseUrl}}"],
                            "path": ["{{apiVersion}}", "todos"],
                        },
                        "header": [
                            {"key": "Content-Type", "value": "application/json"},
                        ],
                        "body": {
                            "mode": "raw",
                            "raw": '{"title": "New task", "done": false, "priority": 1}',
                            "options": {"raw": {"language": "json"}},
                        },
                        "description": "Create a new todo item",
                    },
                    "response": [],
                },
                {
                    "name": "Update Todo",
                    "request": {
                        "method": "PUT",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/todos/:id",
                            "path": ["{{apiVersion}}", "todos", ":id"],
                            "variable": [{"key": "id", "value": "", "description": "Todo ID"}],
                        },
                        "header": [],
                        "body": {
                            "mode": "raw",
                            "raw": '{"title": "Updated", "done": true}',
                            "options": {"raw": {"language": "json"}},
                        },
                        "description": "Update an existing todo item",
                    },
                    "response": [],
                },
                {
                    "name": "Delete Todo",
                    "request": {
                        "method": "DELETE",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/todos/:id",
                            "path": ["{{apiVersion}}", "todos", ":id"],
                            "variable": [{"key": "id", "value": "", "description": "Todo ID"}],
                        },
                        "header": [],
                        "description": "Delete a todo item",
                    },
                    "response": [],
                },
            ],
        },
        # Folder: Tags
        {
            "name": "Tags",
            "item": [
                {
                    "name": "List Tags",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/tags",
                            "path": ["{{apiVersion}}", "tags"],
                        },
                        "header": [],
                    },
                    "response": [],
                },
                {
                    "name": "Assign Tag",
                    "request": {
                        "method": "POST",
                        "url": {
                            "raw": "{{baseUrl}}/{{apiVersion}}/todos/:todoId/tags",
                            "path": ["{{apiVersion}}", "todos", ":todoId", "tags"],
                            "variable": [{"key": "todoId", "value": ""}],
                        },
                        "header": [],
                        "body": {
                            "mode": "raw",
                            "raw": '{"tagId": 5}',
                            "options": {"raw": {"language": "json"}},
                        },
                    },
                    "response": [],
                },
            ],
        },
        # Top-level request (no folder)
        {
            "name": "Health Check",
            "request": {
                "method": "GET",
                "url": {
                    "raw": "{{baseUrl}}/health",
                    "path": ["health"],
                },
                "header": [],
                "auth": {"type": "noauth"},
                "description": "Check API health",
            },
            "response": [
                {"name": "Healthy", "status": "OK", "code": 200},
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# End-to-end tests
# ---------------------------------------------------------------------------


class TestTodoCollectionEndToEnd:
    @pytest.mark.asyncio
    async def test_parse_title(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        assert spec.title == "Todo API"

    @pytest.mark.asyncio
    async def test_source_format(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        assert spec.source_format == "postman"

    @pytest.mark.asyncio
    async def test_version_from_info(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        assert spec.version == "2.0.0"

    @pytest.mark.asyncio
    async def test_endpoint_count(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        # 5 Todos + 2 Tags + 1 Health = 8
        assert len(spec.endpoints) == 8

    @pytest.mark.asyncio
    async def test_operation_ids_unique(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        ids = [e.operation_id for e in spec.endpoints]
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_folder_in_tags(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        # All Todos endpoints should have "Todos" tag
        todo_eps = [e for e in spec.endpoints if "Todos" in e.tags]
        assert len(todo_eps) == 5

    @pytest.mark.asyncio
    async def test_tag_folder_in_tags(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        tag_eps = [e for e in spec.endpoints if "Tags" in e.tags]
        assert len(tag_eps) == 2

    @pytest.mark.asyncio
    async def test_top_level_request_has_no_folder_tag(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        health_ep = next(
            (e for e in spec.endpoints if "health_check" in e.operation_id or "health" in e.operation_id),
            None,
        )
        assert health_ep is not None
        assert health_ep.tags == []

    @pytest.mark.asyncio
    async def test_http_methods(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        methods = {e.method for e in spec.endpoints}
        assert HttpMethod.GET in methods
        assert HttpMethod.POST in methods
        assert HttpMethod.PUT in methods
        assert HttpMethod.DELETE in methods

    @pytest.mark.asyncio
    async def test_list_todos_query_params(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        list_ep = next(e for e in spec.endpoints if "list_todos" in e.operation_id)
        param_names = {p.name for p in list_ep.parameters if p.location == ParameterLocation.QUERY}
        # "limit" and "offset" are enabled; "status" is disabled
        assert "limit" in param_names
        assert "offset" in param_names
        assert "status" not in param_names

    @pytest.mark.asyncio
    async def test_get_todo_path_param(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        get_ep = next(e for e in spec.endpoints if "get_todo" in e.operation_id)
        path_params = [p for p in get_ep.parameters if p.location == ParameterLocation.PATH]
        assert any(p.name == "id" for p in path_params)

    @pytest.mark.asyncio
    async def test_create_todo_request_body(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        create_ep = next(e for e in spec.endpoints if "create_todo" in e.operation_id)
        assert create_ep.request_body is not None
        assert create_ep.request_body.content_type == "application/json"
        assert create_ep.request_body.schema.type == "object"

    @pytest.mark.asyncio
    async def test_create_todo_body_schema_has_fields(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        create_ep = next(e for e in spec.endpoints if "create_todo" in e.operation_id)
        props = create_ep.request_body.schema.properties  # type: ignore[union-attr]
        assert "title" in props
        assert "done" in props

    @pytest.mark.asyncio
    async def test_delete_has_no_body(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        del_ep = next(e for e in spec.endpoints if "delete_todo" in e.operation_id)
        assert del_ep.request_body is None

    @pytest.mark.asyncio
    async def test_collection_auth_applied(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        assert any(s.type == AuthType.HTTP_BEARER for s in spec.auth_schemes)

    @pytest.mark.asyncio
    async def test_bearer_auth_on_endpoints(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        # Most endpoints should have bearer security
        list_ep = next(e for e in spec.endpoints if "list_todos" in e.operation_id)
        assert len(list_ep.security) > 0

    @pytest.mark.asyncio
    async def test_custom_header_extracted(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        list_ep = next(e for e in spec.endpoints if "list_todos" in e.operation_id)
        header_params = [p for p in list_ep.parameters if p.location == ParameterLocation.HEADER]
        # X-Request-ID is a custom header, Accept is standard -> excluded
        assert any(p.name == "X-Request-ID" for p in header_params)

    @pytest.mark.asyncio
    async def test_description_preserved(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        list_ep = next(e for e in spec.endpoints if "list_todos" in e.operation_id)
        assert "pagination" in list_ep.description.lower() or list_ep.description != ""

    @pytest.mark.asyncio
    async def test_responses_populated(self) -> None:
        parser = PostmanParser()
        spec = await parser.parse(json.dumps(TODO_COLLECTION))
        list_ep = next(e for e in spec.endpoints if "list_todos" in e.operation_id)
        assert len(list_ep.responses) >= 1
        assert list_ep.responses[0].status_code == "200"


class TestPostmanParserFromFile:
    @pytest.mark.asyncio
    async def test_parse_json_file(self, tmp_path: Path) -> None:
        f = tmp_path / "todo.postman_collection.json"
        f.write_text(json.dumps(TODO_COLLECTION), encoding="utf-8")
        parser = PostmanParser()
        spec = await parser.parse(f)
        assert spec.title == "Todo API"
        assert len(spec.endpoints) == 8

    @pytest.mark.asyncio
    async def test_missing_file_raises(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = PostmanParser()
        with pytest.raises(ParseException, match="not found"):
            await parser.parse(Path("/nonexistent/collection.json"))

    @pytest.mark.asyncio
    async def test_title_override_from_kwarg(self, tmp_path: Path) -> None:
        f = tmp_path / "collection.json"
        f.write_text(json.dumps(TODO_COLLECTION), encoding="utf-8")
        parser = PostmanParser()
        spec = await parser.parse(f, title="Overridden")
        assert spec.title == "Overridden"


class TestPostmanParserEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_collection(self) -> None:
        parser = PostmanParser()
        col: dict[str, Any] = {
            "info": {
                "name": "Empty",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [],
        }
        spec = await parser.parse(json.dumps(col))
        assert spec.endpoints == []
        assert spec.title == "Empty"

    @pytest.mark.asyncio
    async def test_deeply_nested_folders(self) -> None:
        parser = PostmanParser()
        col: dict[str, Any] = {
            "info": {
                "name": "Nested",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [
                {
                    "name": "L1",
                    "item": [
                        {
                            "name": "L2",
                            "item": [
                                {
                                    "name": "Deep Request",
                                    "request": {
                                        "method": "GET",
                                        "url": "https://api.example.com/deep",
                                        "header": [],
                                    },
                                    "response": [],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 1
        assert "l2" in spec.endpoints[0].operation_id or "l1" in spec.endpoints[0].operation_id

    @pytest.mark.asyncio
    async def test_unknown_http_method_defaults_to_get(self) -> None:
        parser = PostmanParser()
        col: dict[str, Any] = {
            "info": {
                "name": "Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [
                {
                    "name": "Weird Method",
                    "request": {
                        "method": "CUSTOM",
                        "url": "https://api.example.com/resource",
                        "header": [],
                    },
                    "response": [],
                }
            ],
        }
        spec = await parser.parse(json.dumps(col))
        assert spec.endpoints[0].method == HttpMethod.GET

    @pytest.mark.asyncio
    async def test_url_as_string(self) -> None:
        parser = PostmanParser()
        col: dict[str, Any] = {
            "info": {
                "name": "Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [
                {
                    "name": "String URL",
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/simple",
                        "header": [],
                    },
                    "response": [],
                }
            ],
        }
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 1

    @pytest.mark.asyncio
    async def test_no_variables(self) -> None:
        parser = PostmanParser()
        col: dict[str, Any] = {
            "info": {
                "name": "No Vars",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "item": [
                {
                    "name": "Request",
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/items",
                        "header": [],
                    },
                    "response": [],
                }
            ],
        }
        spec = await parser.parse(json.dumps(col))
        assert len(spec.endpoints) == 1

    @pytest.mark.asyncio
    async def test_folder_with_own_auth(self) -> None:
        parser = PostmanParser()
        col: dict[str, Any] = {
            "info": {
                "name": "Auth Test",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            },
            "auth": {"type": "bearer", "bearer": []},
            "item": [
                {
                    "name": "Admin",
                    "auth": {
                        "type": "apikey",
                        "apikey": [
                            {"key": "key", "value": "X-Admin-Key"},
                            {"key": "in", "value": "header"},
                        ],
                    },
                    "item": [
                        {
                            "name": "Admin Endpoint",
                            "request": {
                                "method": "GET",
                                "url": "https://api.example.com/admin",
                                "header": [],
                            },
                            "response": [],
                        }
                    ],
                }
            ],
        }
        spec = await parser.parse(json.dumps(col))
        admin_ep = spec.endpoints[0]
        # Should use folder-level apikey, not collection-level bearer
        sec_names = {k for s in admin_ep.security for k in s}
        assert "apiKey" in sec_names
