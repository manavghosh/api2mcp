# SPDX-License-Identifier: MIT
"""Core parsing, validation, and IR schema definitions."""

from .exceptions import (
    API2MCPError,
    CircularRefError,
    ParseError,
    ParseException,
    RefResolutionError,
    ValidationException,
)
from .ir_schema import (
    APISpec,
    AuthScheme,
    AuthType,
    Endpoint,
    HttpMethod,
    ModelDef,
    PaginationConfig,
    Parameter,
    ParameterLocation,
    RequestBody,
    Response,
    SchemaRef,
    SchemaType,
    ServerInfo,
)
from .parser import BaseParser

__all__ = [
    # Exceptions
    "API2MCPError",
    "CircularRefError",
    "ParseError",
    "ParseException",
    "RefResolutionError",
    "ValidationException",
    # IR Schema
    "APISpec",
    "AuthScheme",
    "AuthType",
    "Endpoint",
    "HttpMethod",
    "ModelDef",
    "Parameter",
    "ParameterLocation",
    "PaginationConfig",
    "RequestBody",
    "Response",
    "SchemaRef",
    "SchemaType",
    "ServerInfo",
    # Parser
    "BaseParser",
]
