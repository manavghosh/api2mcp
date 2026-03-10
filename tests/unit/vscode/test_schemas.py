"""Unit tests for F6.4 VS Code Integration — JSON Schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import jsonschema
from jsonschema import Draft7Validator, validate, ValidationError

# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------

_SCHEMAS_DIR = Path(__file__).parents[3] / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMAS_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def config_schema() -> dict:
    return _load_schema("api2mcp-config.schema.json")


@pytest.fixture(scope="module")
def spec_schema() -> dict:
    return _load_schema("feature-spec.schema.json")


# ---------------------------------------------------------------------------
# api2mcp-config.schema.json — valid configs
# ---------------------------------------------------------------------------


def test_config_schema_loads(config_schema: dict) -> None:
    Draft7Validator.check_schema(config_schema)


def test_config_empty_is_valid(config_schema: dict) -> None:
    validate({}, config_schema)


def test_config_all_fields_valid(config_schema: dict) -> None:
    validate(
        {
            "output": "./generated",
            "host": "127.0.0.1",
            "port": 8000,
            "transport": "http",
            "log_level": "info",
        },
        config_schema,
    )


def test_config_stdio_transport_valid(config_schema: dict) -> None:
    validate({"transport": "stdio"}, config_schema)


def test_config_all_log_levels_valid(config_schema: dict) -> None:
    for level in ("debug", "info", "warning", "error", "critical"):
        validate({"log_level": level}, config_schema)


def test_config_port_boundaries_valid(config_schema: dict) -> None:
    validate({"port": 1}, config_schema)
    validate({"port": 65535}, config_schema)


def test_config_minimal_host_override(config_schema: dict) -> None:
    validate({"host": "0.0.0.0", "port": 3000}, config_schema)


# ---------------------------------------------------------------------------
# api2mcp-config.schema.json — invalid configs
# ---------------------------------------------------------------------------


def test_config_invalid_transport_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError, match="transport"):
        validate({"transport": "websocket"}, config_schema)


def test_config_invalid_log_level_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate({"log_level": "verbose"}, config_schema)


def test_config_port_below_minimum_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate({"port": 0}, config_schema)


def test_config_port_above_maximum_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate({"port": 99999}, config_schema)


def test_config_port_not_integer_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate({"port": "8000"}, config_schema)


def test_config_unknown_field_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate({"unknown_field": "value"}, config_schema)


def test_config_host_not_string_rejected(config_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate({"host": 12345}, config_schema)


# ---------------------------------------------------------------------------
# api2mcp-config.schema.json — schema completeness
# ---------------------------------------------------------------------------


def test_config_schema_has_all_config_keys(config_schema: dict) -> None:
    """Ensure every key supported by config.py is present in the schema."""
    expected_keys = {"output", "host", "port", "transport", "log_level"}
    schema_properties = set(config_schema.get("properties", {}).keys())
    assert expected_keys <= schema_properties, (
        f"Missing keys in schema: {expected_keys - schema_properties}"
    )


def test_config_schema_transport_enum(config_schema: dict) -> None:
    transport_enum = config_schema["properties"]["transport"]["enum"]
    assert "http" in transport_enum
    assert "stdio" in transport_enum


def test_config_schema_log_level_enum(config_schema: dict) -> None:
    log_level_enum = config_schema["properties"]["log_level"]["enum"]
    assert set(log_level_enum) == {"debug", "info", "warning", "error", "critical"}


def test_config_schema_port_has_min_max(config_schema: dict) -> None:
    port_props = config_schema["properties"]["port"]
    assert port_props["minimum"] == 1
    assert port_props["maximum"] == 65535


# ---------------------------------------------------------------------------
# feature-spec.schema.json — valid frontmatter
# ---------------------------------------------------------------------------


def test_spec_schema_loads(spec_schema: dict) -> None:
    Draft7Validator.check_schema(spec_schema)


def test_spec_minimal_valid(spec_schema: dict) -> None:
    validate(
        {
            "id": "F1.1",
            "title": "OpenAPI Parser",
            "phase": 1,
            "priority": "P1",
            "effort": "2 weeks",
            "status": "completed",
        },
        spec_schema,
    )


def test_spec_with_dependencies_valid(spec_schema: dict) -> None:
    validate(
        {
            "id": "F6.4",
            "title": "VS Code Integration",
            "phase": 6,
            "priority": "P2",
            "effort": "1 week",
            "status": "planned",
            "dependencies": ["F1.4"],
        },
        spec_schema,
    )


def test_spec_all_statuses_valid(spec_schema: dict) -> None:
    base = {
        "id": "F1.1",
        "title": "Test",
        "phase": 1,
        "priority": "P1",
        "effort": "1 week",
    }
    for status in ("planned", "in-progress", "completed", "blocked", "cancelled"):
        validate({**base, "status": status}, spec_schema)


def test_spec_all_priorities_valid(spec_schema: dict) -> None:
    base = {
        "id": "F1.1",
        "title": "Test",
        "phase": 1,
        "effort": "1 week",
        "status": "planned",
    }
    for priority in ("P0", "P1", "P2", "P3"):
        validate({**base, "priority": priority}, spec_schema)


def test_spec_id_pattern_valid(spec_schema: dict) -> None:
    base = {
        "title": "Test",
        "phase": 1,
        "priority": "P1",
        "effort": "1 week",
        "status": "planned",
    }
    for fid in ("F1.1", "F5.10", "F7.99"):
        validate({**base, "id": fid}, spec_schema)


def test_spec_multi_dependencies_valid(spec_schema: dict) -> None:
    validate(
        {
            "id": "F5.3",
            "title": "Planner Graph",
            "phase": 5,
            "priority": "P1",
            "effort": "2 weeks",
            "status": "planned",
            "dependencies": ["F5.1", "F5.2", "F1.3"],
        },
        spec_schema,
    )


# ---------------------------------------------------------------------------
# feature-spec.schema.json — invalid frontmatter
# ---------------------------------------------------------------------------


def test_spec_missing_required_id_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError, match="'id' is a required property"):
        validate(
            {
                "title": "Missing ID",
                "phase": 1,
                "priority": "P1",
                "effort": "1 week",
                "status": "planned",
            },
            spec_schema,
        )


def test_spec_missing_required_title_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError, match="'title' is a required property"):
        validate(
            {
                "id": "F1.1",
                "phase": 1,
                "priority": "P1",
                "effort": "1 week",
                "status": "planned",
            },
            spec_schema,
        )


def test_spec_invalid_id_pattern_rejected(spec_schema: dict) -> None:
    base = {
        "title": "Test",
        "phase": 1,
        "priority": "P1",
        "effort": "1 week",
        "status": "planned",
    }
    for bad_id in ("F1", "1.1", "Feature-1", "f1.1"):
        with pytest.raises(ValidationError):
            validate({**base, "id": bad_id}, spec_schema)


def test_spec_invalid_priority_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "id": "F1.1",
                "title": "Test",
                "phase": 1,
                "priority": "P5",
                "effort": "1 week",
                "status": "planned",
            },
            spec_schema,
        )


def test_spec_invalid_status_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "id": "F1.1",
                "title": "Test",
                "phase": 1,
                "priority": "P1",
                "effort": "1 week",
                "status": "unknown",
            },
            spec_schema,
        )


def test_spec_phase_out_of_range_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "id": "F8.1",
                "title": "Test",
                "phase": 8,
                "priority": "P1",
                "effort": "1 week",
                "status": "planned",
            },
            spec_schema,
        )


def test_spec_unknown_field_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "id": "F1.1",
                "title": "Test",
                "phase": 1,
                "priority": "P1",
                "effort": "1 week",
                "status": "planned",
                "unknown_key": "value",
            },
            spec_schema,
        )


def test_spec_dependency_invalid_pattern_rejected(spec_schema: dict) -> None:
    with pytest.raises(ValidationError):
        validate(
            {
                "id": "F1.1",
                "title": "Test",
                "phase": 1,
                "priority": "P1",
                "effort": "1 week",
                "status": "planned",
                "dependencies": ["Feature-1"],
            },
            spec_schema,
        )


# ---------------------------------------------------------------------------
# Schema completeness — spec schema
# ---------------------------------------------------------------------------


def test_spec_schema_required_fields(spec_schema: dict) -> None:
    required = set(spec_schema.get("required", []))
    assert required == {"id", "title", "phase", "priority", "effort", "status"}


def test_spec_schema_has_dependencies_property(spec_schema: dict) -> None:
    assert "dependencies" in spec_schema["properties"]
    dep_schema = spec_schema["properties"]["dependencies"]
    assert dep_schema["type"] == "array"


def test_spec_schema_status_enum_coverage(spec_schema: dict) -> None:
    status_enum = set(spec_schema["properties"]["status"]["enum"])
    assert "planned" in status_enum
    assert "in-progress" in status_enum
    assert "completed" in status_enum
