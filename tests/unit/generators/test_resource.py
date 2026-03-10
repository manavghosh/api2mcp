"""Tests for MCPResourceGenerator."""
import pytest
from api2mcp.generators.resource import MCPResourceDef, MCPResourceGenerator
from api2mcp.core.ir_schema import APISpec, Endpoint, HttpMethod


def _make_spec(method: HttpMethod = HttpMethod.GET) -> APISpec:
    return APISpec(
        title="Test API",
        version="1.0.0",
        base_url="https://api.example.com",
        endpoints=[
            Endpoint(
                path="/users/{id}",
                method=method,
                operation_id="get_user",
                summary="Get a user by ID",
                parameters=[],
                responses=[],
            )
        ],
    )


def test_generate_returns_resource_defs():
    spec = _make_spec()
    gen = MCPResourceGenerator()
    resources = gen.generate(spec)
    assert len(resources) == 1
    assert resources[0].name == "get_user"
    assert resources[0].uri_template == "https://api.example.com/users/{id}"


def test_resource_def_has_description():
    spec = _make_spec()
    gen = MCPResourceGenerator()
    resources = gen.generate(spec)
    assert resources[0].description == "Get a user by ID"


def test_non_get_endpoints_excluded():
    spec = _make_spec(method=HttpMethod.POST)
    gen = MCPResourceGenerator()
    resources = gen.generate(spec)
    assert resources == []


def test_empty_spec_returns_empty():
    spec = APISpec(
        title="Empty",
        version="1.0",
        base_url="https://api.example.com",
        endpoints=[],
    )
    gen = MCPResourceGenerator()
    assert gen.generate(spec) == []
