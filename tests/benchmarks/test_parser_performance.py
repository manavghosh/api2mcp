"""Performance benchmarks for the OpenAPI parser and tool generator.

Run with::

    pytest tests/benchmarks/ -v --benchmark-only

Or for a quick timing check without pytest-benchmark::

    pytest tests/benchmarks/ -v -m benchmark

These benchmarks assert on maximum wall-clock time to catch regressions.
They are tagged ``benchmark`` so CI can exclude them from normal test runs.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

PETSTORE_SPEC = Path(__file__).parents[2] / "tests" / "fixtures" / "petstore.yaml"
MINIMAL_SPEC_YAML = """\
openapi: "3.0.0"
info:
  title: Benchmark API
  version: "1.0"
paths:
  /users/{id}:
    get:
      operationId: get_user
      parameters:
        - name: id
          in: path
          required: true
          schema: {type: integer}
      responses:
        "200": {description: OK}
  /items:
    get:
      operationId: list_items
      parameters:
        - name: page
          in: query
          schema: {type: integer, default: 1}
        - name: limit
          in: query
          schema: {type: integer, default: 20}
      responses:
        "200": {description: OK}
  /orders:
    post:
      operationId: create_order
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                user_id: {type: integer}
                amount: {type: number}
      responses:
        "201": {description: Created}
"""

_MAX_PARSE_SECONDS = 2.0
_MAX_GENERATE_SECONDS = 0.5
_MAX_PARSE_GENERATE_SECONDS = 3.0


@pytest.mark.benchmark
def test_parse_minimal_spec_is_fast(tmp_path: Path) -> None:
    """Parsing a small spec completes in under {_MAX_PARSE_SECONDS}s."""
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(MINIMAL_SPEC_YAML, encoding="utf-8")

    from api2mcp.parsers.openapi import OpenAPIParser

    parser = OpenAPIParser()
    start = time.perf_counter()
    api_spec = asyncio.run(parser.parse(spec_file))
    elapsed = time.perf_counter() - start

    assert api_spec is not None
    assert elapsed < _MAX_PARSE_SECONDS, (
        f"Parser took {elapsed:.3f}s — exceeds {_MAX_PARSE_SECONDS}s budget"
    )


@pytest.mark.benchmark
def test_generate_tools_is_fast(tmp_path: Path) -> None:
    """Generating tools from a parsed spec completes in under {_MAX_GENERATE_SECONDS}s."""
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(MINIMAL_SPEC_YAML, encoding="utf-8")

    from api2mcp.parsers.openapi import OpenAPIParser
    from api2mcp.generators.tool import ToolGenerator

    parser = OpenAPIParser()
    api_spec = asyncio.run(parser.parse(spec_file))

    generator = ToolGenerator()
    start = time.perf_counter()
    tools = generator.generate(api_spec)
    elapsed = time.perf_counter() - start

    assert len(tools) > 0
    assert elapsed < _MAX_GENERATE_SECONDS, (
        f"Generator took {elapsed:.3f}s — exceeds {_MAX_GENERATE_SECONDS}s budget"
    )


@pytest.mark.benchmark
def test_full_parse_generate_pipeline_is_fast(tmp_path: Path) -> None:
    """Full parse → generate pipeline completes in under {_MAX_PARSE_GENERATE_SECONDS}s."""
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(MINIMAL_SPEC_YAML, encoding="utf-8")

    from api2mcp.parsers.openapi import OpenAPIParser
    from api2mcp.generators.tool import ToolGenerator

    start = time.perf_counter()
    parser = OpenAPIParser()
    api_spec = asyncio.run(parser.parse(spec_file))
    tools = ToolGenerator().generate(api_spec)
    elapsed = time.perf_counter() - start

    assert len(tools) > 0
    assert elapsed < _MAX_PARSE_GENERATE_SECONDS, (
        f"Pipeline took {elapsed:.3f}s — exceeds {_MAX_PARSE_GENERATE_SECONDS}s budget"
    )


@pytest.mark.benchmark
def test_petstore_parse_is_fast() -> None:
    """Parsing the petstore fixture (realistic spec) completes under 5s."""
    if not PETSTORE_SPEC.exists():
        pytest.skip("petstore.yaml fixture not available")

    from api2mcp.parsers.openapi import OpenAPIParser

    parser = OpenAPIParser()
    start = time.perf_counter()
    api_spec = asyncio.run(parser.parse(PETSTORE_SPEC))
    elapsed = time.perf_counter() - start

    assert api_spec is not None
    assert elapsed < 5.0, f"Petstore parse took {elapsed:.3f}s — exceeds 5s budget"


@pytest.mark.benchmark
def test_cache_directives_parsing_is_fast() -> None:
    """HTTP cache header parsing handles 10 000 headers under 0.1s."""
    from api2mcp.cache.headers import parse_headers

    headers = {
        "cache-control": "max-age=3600, s-maxage=600, must-revalidate",
        "etag": '"abc123"',
        "age": "120",
        "last-modified": "Wed, 21 Oct 2015 07:28:00 GMT",
    }

    result = parse_headers(headers)  # warm up + validate
    start = time.perf_counter()
    for _ in range(10_000):
        parse_headers(headers)
    elapsed = time.perf_counter() - start

    assert result is not None
    assert elapsed < 0.1, f"10k header parses took {elapsed:.3f}s — exceeds 0.1s budget"


@pytest.mark.benchmark
def test_deep_merge_is_fast() -> None:
    """Deep-merge 10 000 nested dicts completes under 0.5s."""
    from api2mcp.utils.merge import deep_merge

    base = {"a": {"x": 1, "y": {"p": 10}}, "b": [1, 2, 3]}
    override = {"a": {"y": {"q": 20}, "z": 99}, "c": "new"}

    start = time.perf_counter()
    for _ in range(10_000):
        deep_merge(base, override)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"10k deep_merge took {elapsed:.3f}s — exceeds 0.5s budget"
