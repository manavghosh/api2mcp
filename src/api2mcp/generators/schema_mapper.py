# SPDX-License-Identifier: MIT
"""IR-to-JSON-Schema mapper for MCP tool input_schema (TASK-013, TASK-015).

Converts IR endpoints (parameters + request body) into a unified JSON Schema
object suitable for MCP tool input_schema. Handles:
- Path, query, and header parameter merging
- Request body integration
- Configurable depth limiting for deeply nested schemas
"""

from __future__ import annotations

from typing import Any

from api2mcp.core.ir_schema import (
    Endpoint,
    Parameter,
    ParameterLocation,
    SchemaRef,
)


def _parameter_to_property(param: Parameter) -> dict[str, Any]:
    """Convert an IR Parameter to a JSON Schema property dict."""
    prop = param.schema.to_json_schema()
    # Prefer parameter-level description over schema description
    if param.description:
        prop["description"] = param.description
    if param.example is not None:
        prop["example"] = param.example
    if param.deprecated:
        prop["deprecated"] = True
    return prop


def _simplify_schema(
    schema: dict[str, Any],
    current_depth: int,
    max_depth: int,
) -> dict[str, Any]:
    """Recursively simplify a JSON Schema, truncating at max_depth.

    At the depth limit, object types are replaced with a generic object
    and arrays with generic array, preserving descriptions.
    """
    if current_depth >= max_depth:
        result: dict[str, Any] = {}
        schema_type = schema.get("type", "object")
        if isinstance(schema_type, list):
            result["type"] = schema_type
        elif schema_type == "array":
            result["type"] = "array"
            result["description"] = schema.get(
                "description", "Nested array (truncated at depth limit)"
            )
        elif schema_type == "object":
            result["type"] = "object"
            result["description"] = schema.get(
                "description", "Nested object (truncated at depth limit)"
            )
        else:
            # Primitives pass through unchanged
            return schema
        return result

    simplified = dict(schema)

    # Recurse into properties
    if "properties" in simplified:
        simplified["properties"] = {
            name: _simplify_schema(prop, current_depth + 1, max_depth)
            for name, prop in simplified["properties"].items()
        }

    # Recurse into items (arrays)
    if "items" in simplified:
        simplified["items"] = _simplify_schema(
            simplified["items"], current_depth + 1, max_depth
        )

    # Recurse into additionalProperties
    if isinstance(simplified.get("additionalProperties"), dict):
        simplified["additionalProperties"] = _simplify_schema(
            simplified["additionalProperties"], current_depth + 1, max_depth
        )

    # Recurse into composition keywords
    for keyword in ("oneOf", "anyOf", "allOf"):
        if keyword in simplified:
            simplified[keyword] = [
                _simplify_schema(s, current_depth + 1, max_depth)
                for s in simplified[keyword]
            ]

    return simplified


def build_input_schema(
    endpoint: Endpoint,
    max_depth: int = 5,
) -> dict[str, Any]:
    """Build a unified MCP input_schema from an endpoint's parameters and request body.

    Merges path, query, header, and cookie parameters into a single JSON Schema
    object. Request body properties are nested under a 'body' key (or merged
    directly for simple object bodies).

    Args:
        endpoint: The IR endpoint to build schema for.
        max_depth: Maximum nesting depth before schema simplification.

    Returns:
        A JSON Schema dict with type "object" suitable for MCP tool inputSchema.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    # Include parameters (path, query, header, cookie — skip body location used by GraphQL)
    for param in endpoint.parameters:
        if param.location == ParameterLocation.BODY:
            # GraphQL body params handled separately
            continue
        prop = _parameter_to_property(param)
        properties[param.name] = prop
        if param.required:
            required.append(param.name)

    # Include request body
    if endpoint.request_body is not None:
        body_schema = endpoint.request_body.schema.to_json_schema()

        if _is_simple_object(body_schema):
            # Merge object properties directly into top-level for flat APIs
            body_props = body_schema.get("properties", {})
            body_required = body_schema.get("required", [])

            for name, prop in body_props.items():
                # Avoid collision with parameter names — prefix with 'body_'
                final_name = name if name not in properties else f"body_{name}"
                properties[final_name] = prop
                if name in body_required:
                    required.append(final_name)
        else:
            # Non-object body (array, primitive) — wrap as 'body' parameter
            description = endpoint.request_body.description or "Request body"
            body_schema.setdefault("description", description)
            properties["body"] = body_schema
            if endpoint.request_body.required:
                required.append("body")

    # Handle GraphQL body-location parameters
    for param in endpoint.parameters:
        if param.location == ParameterLocation.BODY:
            prop = _parameter_to_property(param)
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    # Apply depth simplification
    return _simplify_schema(schema, current_depth=0, max_depth=max_depth)


def _is_simple_object(schema: dict[str, Any]) -> bool:
    """Check if a schema represents a simple object (has properties, no composition)."""
    return (
        schema.get("type") == "object"
        and "properties" in schema
        and not any(k in schema for k in ("oneOf", "anyOf", "allOf"))
    )
