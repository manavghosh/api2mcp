"""Tests for MCPPromptGenerator."""
import pytest
from api2mcp.generators.prompt import MCPPromptDef, MCPPromptGenerator
from api2mcp.core.ir_schema import (
    APISpec,
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    SchemaRef,
)


def _make_spec() -> APISpec:
    return APISpec(
        title="Test API",
        version="1.0.0",
        base_url="https://api.example.com",
        endpoints=[
            Endpoint(
                path="/search",
                method=HttpMethod.GET,
                operation_id="search_items",
                summary="Search for items",
                parameters=[
                    Parameter(
                        name="q",
                        location=ParameterLocation.QUERY,
                        required=True,
                        schema=SchemaRef(type="string"),
                    ),
                ],
                responses=[],
            )
        ],
    )


def test_generate_returns_prompt_defs():
    spec = _make_spec()
    gen = MCPPromptGenerator()
    prompts = gen.generate(spec)
    assert len(prompts) == 1
    assert prompts[0].name == "search_items"


def test_prompt_has_arguments():
    spec = _make_spec()
    gen = MCPPromptGenerator()
    prompts = gen.generate(spec)
    assert any(a["name"] == "q" for a in prompts[0].arguments)


def test_prompt_description():
    spec = _make_spec()
    gen = MCPPromptGenerator()
    prompts = gen.generate(spec)
    assert prompts[0].description == "Search for items"


def test_empty_spec_returns_empty():
    spec = APISpec(
        title="Empty",
        version="1.0",
        base_url="https://api.example.com",
        endpoints=[],
    )
    gen = MCPPromptGenerator()
    assert gen.generate(spec) == []
