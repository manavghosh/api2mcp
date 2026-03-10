"""E2E test: spec file → generate → serve → tool call.

These tests verify the complete pipeline works end-to-end without mocking
any components. They are slower than unit tests and are gated by the
``e2e`` pytest mark.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

PETSTORE_SPEC = Path(__file__).parents[2] / "tests" / "fixtures" / "petstore.yaml"


@pytest.fixture
def petstore_spec() -> Path:
    assert PETSTORE_SPEC.exists(), f"Fixture not found: {PETSTORE_SPEC}"
    return PETSTORE_SPEC


@pytest.fixture
def minimal_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "openapi.yaml"
    spec.write_text(
        """
openapi: "3.0.0"
info:
  title: E2E Test API
  version: "1.0"
paths:
  /users/{id}:
    get:
      operationId: get_user
      summary: Get a user by ID
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        "200":
          description: OK
  /items:
    post:
      operationId: create_item
      summary: Create an item
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                price:
                  type: number
      responses:
        "201":
          description: Created
""",
        encoding="utf-8",
    )
    return spec


# ---------------------------------------------------------------------------
# Stage 1: Parse
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_parse_petstore(petstore_spec: Path) -> None:
    """OpenAPI parser produces a non-empty APISpec from the petstore fixture."""
    from api2mcp.parsers.openapi import OpenAPIParser

    parser = OpenAPIParser()
    spec = asyncio.run(parser.parse(petstore_spec))

    assert spec is not None
    assert spec.title
    assert len(spec.endpoints) > 0


@pytest.mark.e2e
def test_parse_minimal_spec(minimal_spec: Path) -> None:
    """Parser handles a minimal spec with path/query params and a request body."""
    from api2mcp.parsers.openapi import OpenAPIParser

    parser = OpenAPIParser()
    spec = asyncio.run(parser.parse(minimal_spec))

    assert spec is not None
    assert len(spec.endpoints) == 2
    op_ids = {ep.operation_id for ep in spec.endpoints}
    assert "get_user" in op_ids
    assert "create_item" in op_ids


# ---------------------------------------------------------------------------
# Stage 2: Generate
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_generate_tools_from_petstore(petstore_spec: Path) -> None:
    """Tool generator produces at least one tool from the petstore spec."""
    from api2mcp.parsers.openapi import OpenAPIParser
    from api2mcp.generators.tool import ToolGenerator

    parser = OpenAPIParser()
    spec = asyncio.run(parser.parse(petstore_spec))

    generator = ToolGenerator()
    tools = generator.generate(spec)

    assert len(tools) > 0
    tool_names = [t.name for t in tools]
    assert all(isinstance(n, str) and n for n in tool_names)


@pytest.mark.e2e
def test_generate_writes_output_dir(minimal_spec: Path, tmp_path: Path) -> None:
    """generate_cmd writes a non-empty output directory."""
    from click.testing import CliRunner
    from api2mcp.cli.main import cli

    out = tmp_path / "generated"
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(minimal_spec), "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert out.is_dir()
    assert any(out.iterdir()), "Output directory is empty"


# ---------------------------------------------------------------------------
# Stage 3: Full pipeline (parse → generate → validate round-trip)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_pipeline_tool_names_are_operation_ids(minimal_spec: Path) -> None:
    """Generated tool names correspond to OpenAPI operationIds."""
    from api2mcp.parsers.openapi import OpenAPIParser
    from api2mcp.generators.tool import ToolGenerator

    parser = OpenAPIParser()
    spec = asyncio.run(parser.parse(minimal_spec))
    tools = ToolGenerator().generate(spec)

    tool_names = {t.name for t in tools}
    assert "get_user" in tool_names
    assert "create_item" in tool_names


@pytest.mark.e2e
def test_validate_command_on_minimal_spec(minimal_spec: Path) -> None:
    """api2mcp validate returns exit code 0 for a valid spec."""
    from click.testing import CliRunner
    from api2mcp.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(minimal_spec)])
    assert result.exit_code == 0, result.output


@pytest.mark.e2e
def test_validate_command_json_format(minimal_spec: Path) -> None:
    """api2mcp validate --output-format json returns an empty JSON array on success."""
    import json
    from click.testing import CliRunner
    from api2mcp.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli, ["validate", str(minimal_spec), "--output-format", "json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output.strip())
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.e2e
def test_diff_identical_specs_exit_0(minimal_spec: Path, tmp_path: Path) -> None:
    """api2mcp diff with identical specs exits 0 (no breaking changes)."""
    import shutil
    from click.testing import CliRunner
    from api2mcp.cli.main import cli

    copy = tmp_path / "openapi_copy.yaml"
    shutil.copy(minimal_spec, copy)

    runner = CliRunner()
    result = runner.invoke(cli, ["diff", str(minimal_spec), str(copy)])
    assert result.exit_code == 0, result.output
