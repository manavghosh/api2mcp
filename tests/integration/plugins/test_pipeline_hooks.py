"""Integration test: plugin hooks fired during parse pipeline."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

FIXTURES_DIR = Path(__file__).parents[2] / "unit"


def _get_minimal_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "openapi.yaml"
    spec.write_text("""
openapi: "3.0.0"
info:
  title: Hook Test API
  version: "1.0"
paths:
  /test:
    get:
      operationId: test_endpoint
      responses:
        "200":
          description: OK
""")
    return spec


def test_openapi_parser_parse_succeeds(tmp_path):
    """OpenAPI parser can parse a minimal spec without errors."""
    import asyncio

    from api2mcp.parsers.openapi import OpenAPIParser
    spec = _get_minimal_spec(tmp_path)
    parser = OpenAPIParser()
    result = asyncio.run(parser.parse(spec))
    assert result is not None


def test_generate_command_succeeds(tmp_path):
    """api2mcp generate runs without errors (plugin hooks don't crash it)."""
    from api2mcp.cli.main import cli
    spec = _get_minimal_spec(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", str(spec), "--output", str(tmp_path / "out")])
    assert result.exit_code == 0, f"generate failed: {result.output}"
