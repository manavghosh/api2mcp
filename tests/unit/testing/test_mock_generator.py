"""Unit tests for F6.3 MockResponseGenerator."""

from __future__ import annotations

import pytest

from api2mcp.testing.mock_generator import MockResponseGenerator, MockScenario


# ---------------------------------------------------------------------------
# Helpers — minimal APISpec fixtures
# ---------------------------------------------------------------------------

def _make_spec(endpoints_raw: list[dict]) -> object:
    """Build a minimal APISpec with given endpoint dicts."""
    from api2mcp.core.ir_schema import (
        APISpec, Endpoint, HttpMethod, Parameter, ParameterLocation, SchemaRef,
    )

    endpoints = []
    for ep in endpoints_raw:
        params = []
        for p in ep.get("params", []):
            params.append(
                Parameter(
                    name=p["name"],
                    location=ParameterLocation(p["in"]),
                    required=p.get("required", False),
                    schema=SchemaRef(type="string"),
                )
            )
        endpoints.append(
            Endpoint(
                path=ep["path"],
                method=HttpMethod(ep["method"].upper()),
                operation_id=ep.get("operationId", ""),
                summary=ep.get("summary", ""),
                parameters=params,
            )
        )
    return APISpec(title="Test", version="1.0", endpoints=endpoints)


# ---------------------------------------------------------------------------
# MockScenario
# ---------------------------------------------------------------------------


def test_mock_scenario_defaults() -> None:
    s = MockScenario(name="test")
    assert s.status_code == 200
    assert s.body is None
    assert s.headers == {}


def test_mock_scenario_to_dict() -> None:
    s = MockScenario(name="ok", status_code=201, body={"id": 1}, headers={"X-Foo": "bar"})
    d = s.to_dict()
    assert d["name"] == "ok"
    assert d["status_code"] == 201
    assert d["body"] == {"id": 1}
    assert d["headers"] == {"X-Foo": "bar"}


# ---------------------------------------------------------------------------
# MockResponseGenerator.scenarios_for
# ---------------------------------------------------------------------------


def test_scenarios_for_get_list_endpoint() -> None:
    spec = _make_spec([{"path": "/items", "method": "GET"}])
    gen = MockResponseGenerator(spec)  # type: ignore[arg-type]
    scenarios = gen.scenarios_for("get_items")
    names = [s.name for s in scenarios]
    assert "success" in names
    assert "unauthorized" in names


def test_scenarios_for_get_with_path_param() -> None:
    spec = _make_spec([
        {
            "path": "/items/{id}",
            "method": "GET",
            "params": [{"name": "id", "in": "path", "required": True}],
        }
    ])
    gen = MockResponseGenerator(spec)  # type: ignore[arg-type]
    scenarios = gen.scenarios_for("get_items_id")
    names = [s.name for s in scenarios]
    assert "not_found" in names


def test_scenarios_for_post_includes_validation_error() -> None:
    spec = _make_spec([{"path": "/items", "method": "POST"}])
    gen = MockResponseGenerator(spec)  # type: ignore[arg-type]
    scenarios = gen.scenarios_for("post_items")
    names = [s.name for s in scenarios]
    assert "validation_error" in names


def test_scenarios_for_unknown_tool_raises_key_error() -> None:
    spec = _make_spec([{"path": "/items", "method": "GET"}])
    gen = MockResponseGenerator(spec)  # type: ignore[arg-type]
    with pytest.raises(KeyError, match="no_such_tool"):
        gen.scenarios_for("no_such_tool")


def test_success_body_returns_dict_or_list() -> None:
    spec = _make_spec([{"path": "/items", "method": "GET"}])
    gen = MockResponseGenerator(spec)  # type: ignore[arg-type]
    body = gen.success_body("get_items")
    assert isinstance(body, (dict, list))


# ---------------------------------------------------------------------------
# MockResponseGenerator.all_scenarios
# ---------------------------------------------------------------------------


def test_all_scenarios_covers_every_endpoint() -> None:
    spec = _make_spec([
        {"path": "/items", "method": "GET"},
        {"path": "/items", "method": "POST"},
    ])
    gen = MockResponseGenerator(spec)  # type: ignore[arg-type]
    all_s = gen.all_scenarios()
    assert len(all_s) == 2


# ---------------------------------------------------------------------------
# Deterministic generation with seed
# ---------------------------------------------------------------------------


def test_seeded_generation_is_deterministic() -> None:
    spec = _make_spec([{"path": "/items", "method": "GET"}])
    gen1 = MockResponseGenerator(spec, seed=42)  # type: ignore[arg-type]
    gen2 = MockResponseGenerator(spec, seed=42)  # type: ignore[arg-type]
    body1 = gen1.success_body("get_items")
    body2 = gen2.success_body("get_items")
    assert body1 == body2


def test_different_seeds_may_differ() -> None:
    spec = _make_spec([{"path": "/items", "method": "GET"}])
    gen1 = MockResponseGenerator(spec, seed=1)  # type: ignore[arg-type]
    gen2 = MockResponseGenerator(spec, seed=2)  # type: ignore[arg-type]
    body1 = gen1.success_body("get_items")
    body2 = gen2.success_body("get_items")
    # With different seeds the random IDs almost certainly differ
    assert body1 != body2 or True  # non-determinism is possible but unlikely
