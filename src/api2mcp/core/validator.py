# SPDX-License-Identifier: MIT
"""Schema validation for API specifications.

Validates parsed OpenAPI documents against structural rules
and produces detailed error reports with line-number context.
"""

from __future__ import annotations

import logging
from typing import Any

from .exceptions import ParseError

logger = logging.getLogger(__name__)


def validate_openapi_structure(doc: dict[str, Any]) -> list[ParseError]:
    """Validate an OpenAPI document's structural correctness.

    Checks for required fields, valid types, and known patterns.
    This is NOT full JSON Schema validation — it covers the most
    important structural rules for robust parsing.

    Returns:
        List of ParseError (empty means valid).
    """
    errors: list[ParseError] = []

    # Required top-level fields
    _check_required_fields(doc, ["openapi", "info", "paths"], "", errors)

    # openapi version string
    openapi_ver = doc.get("openapi", "")
    if openapi_ver and not isinstance(openapi_ver, str):
        errors.append(ParseError("'openapi' must be a string", path="openapi"))
    elif isinstance(openapi_ver, str) and not openapi_ver.startswith("3."):
        errors.append(
            ParseError(
                f"Unsupported OpenAPI version: '{openapi_ver}'. Only 3.x is supported.",
                path="openapi",
            )
        )

    # info object
    info = doc.get("info")
    if isinstance(info, dict):
        _check_required_fields(info, ["title", "version"], "info", errors)
    elif info is not None:
        errors.append(ParseError("'info' must be an object", path="info"))

    # paths object
    paths = doc.get("paths")
    if isinstance(paths, dict):
        _validate_paths(paths, errors)
    elif paths is not None:
        errors.append(ParseError("'paths' must be an object", path="paths"))

    # servers (optional)
    servers = doc.get("servers")
    if servers is not None:
        if not isinstance(servers, list):
            errors.append(ParseError("'servers' must be an array", path="servers"))
        else:
            for i, srv in enumerate(servers):
                if not isinstance(srv, dict):
                    errors.append(
                        ParseError(
                            f"Server entry must be an object",
                            path=f"servers[{i}]",
                        )
                    )
                elif "url" not in srv:
                    errors.append(
                        ParseError("Server missing 'url'", path=f"servers[{i}]")
                    )

    # components (optional)
    components = doc.get("components")
    if components is not None and not isinstance(components, dict):
        errors.append(ParseError("'components' must be an object", path="components"))

    return errors


_VALID_HTTP_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
)
_PATH_ITEM_FIELDS = frozenset(
    _VALID_HTTP_METHODS
    | {"$ref", "summary", "description", "parameters", "servers"}
)
_VALID_PARAM_LOCATIONS = frozenset({"path", "query", "header", "cookie"})


def _validate_paths(paths: dict[str, Any], errors: list[ParseError]) -> None:
    """Validate paths structure."""
    for path_key, path_item in paths.items():
        if not isinstance(path_item, dict):
            errors.append(
                ParseError("Path item must be an object", path=f"paths.{path_key}")
            )
            continue

        for key, value in path_item.items():
            if key in _PATH_ITEM_FIELDS or key.startswith("x-"):
                pass  # valid
            else:
                errors.append(
                    ParseError(
                        f"Unknown field '{key}' in path item",
                        path=f"paths.{path_key}",
                        severity="warning",
                    )
                )

            # Validate operations
            if key in _VALID_HTTP_METHODS and isinstance(value, dict):
                _validate_operation(value, f"paths.{path_key}.{key}", errors)


def _validate_operation(op: dict[str, Any], path: str, errors: list[ParseError]) -> None:
    """Validate a single operation object."""
    # responses is the only required field in an operation
    if "responses" not in op:
        errors.append(
            ParseError("Operation missing 'responses'", path=path, severity="warning")
        )

    # Validate parameters
    params = op.get("parameters", [])
    if not isinstance(params, list):
        errors.append(ParseError("'parameters' must be an array", path=path))
    else:
        for i, param in enumerate(params):
            if not isinstance(param, dict):
                continue
            if "$ref" in param:
                continue  # Will be resolved later
            if "name" not in param:
                errors.append(
                    ParseError(
                        "Parameter missing 'name'",
                        path=f"{path}.parameters[{i}]",
                    )
                )
            param_in = param.get("in", "")
            if param_in and param_in not in _VALID_PARAM_LOCATIONS:
                errors.append(
                    ParseError(
                        f"Invalid parameter location: '{param_in}'",
                        path=f"{path}.parameters[{i}]",
                    )
                )


def _check_required_fields(
    obj: dict[str, Any],
    fields: list[str],
    path: str,
    errors: list[ParseError],
) -> None:
    """Check that required fields exist in an object."""
    for field_name in fields:
        if field_name not in obj:
            full_path = f"{path}.{field_name}" if path else field_name
            errors.append(
                ParseError(f"Missing required field: '{field_name}'", path=full_path)
            )
