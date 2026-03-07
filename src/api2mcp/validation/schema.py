"""JSON Schema-based validation of tool call arguments.

Uses ``jsonschema`` (already a project dependency) to validate the
``arguments`` dict against the ``input_schema`` from an
:class:`~api2mcp.generators.tool.MCPToolDef`.

Strict mode is used by default: unknown properties are allowed (the MCP
spec permits callers to pass extra context) but type coercion is disabled —
``"1"`` is not silently cast to ``1``.
"""

from __future__ import annotations

import logging
from typing import Any

import jsonschema
import jsonschema.exceptions

from api2mcp.validation.exceptions import SchemaValidationError

logger = logging.getLogger(__name__)


def validate_against_schema(
    arguments: dict[str, Any],
    schema: dict[str, Any],
    *,
    tool_name: str = "",
) -> None:
    """Validate *arguments* against a JSON Schema *schema*.

    Args:
        arguments: The tool call arguments to validate.
        schema: JSON Schema dict (from ``MCPToolDef.input_schema``).
        tool_name: Optional name for clearer error messages.

    Raises:
        :class:`~api2mcp.validation.exceptions.SchemaValidationError`:
            If any required field is missing or a value has the wrong type.
    """
    try:
        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(validator.iter_errors(arguments), key=lambda e: e.path)
        if errors:
            first = errors[0]
            field = ".".join(str(p) for p in first.absolute_path) or "<root>"
            prefix = f"[{tool_name}] " if tool_name else ""
            raise SchemaValidationError(
                f"{prefix}{first.message}",
                field=field,
            )
    except (jsonschema.SchemaError, SchemaValidationError):
        raise
    except Exception as exc:  # noqa: BLE001
        # Malformed schema raises unexpected errors (e.g., TypeError when
        # iter_errors encounters an invalid type value like {"type": 999}).
        # Log and skip — don't block the tool call.
        logger.warning("Invalid JSON Schema for tool '%s': %s", tool_name, exc)


def check_required_fields(
    arguments: dict[str, Any],
    schema: dict[str, Any],
    *,
    tool_name: str = "",
) -> None:
    """Explicitly check that all ``required`` fields are present.

    This is a fast pre-check before full schema validation.
    """
    required: list[str] = schema.get("required", [])
    for field in required:
        if field not in arguments:
            prefix = f"[{tool_name}] " if tool_name else ""
            raise SchemaValidationError(
                f"{prefix}Required field '{field}' is missing.",
                field=field,
            )


def infer_string_fields(schema: dict[str, Any]) -> set[str]:
    """Return the set of top-level property names whose type is ``"string"``."""
    props: dict[str, Any] = schema.get("properties", {})
    return {
        name
        for name, prop in props.items()
        if isinstance(prop, dict) and prop.get("type") == "string"
    }
