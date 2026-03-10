# SPDX-License-Identifier: MIT
"""Intermediate Representation (IR) schema for API2MCP.

The IR is the central data structure bridging ALL parsers to ALL generators.
Every parser outputs IR; every generator consumes IR. Changes to the IR schema
affect the entire pipeline.

Design decisions:
- GraphQL queries/mutations map to Endpoint with method="QUERY"/"MUTATION"
- GraphQL fragments resolved during parsing, not stored in IR
- Postman variables substituted during parsing, not stored in IR
- Pagination patterns detected and stored for smart tool generation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HttpMethod(str, Enum):
    """HTTP methods + GraphQL virtual methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    # GraphQL virtual methods
    QUERY = "QUERY"
    MUTATION = "MUTATION"
    SUBSCRIPTION = "SUBSCRIPTION"


class ParameterLocation(str, Enum):
    """Where in the request a parameter is sent."""

    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"
    BODY = "body"  # GraphQL variables


class AuthType(str, Enum):
    """Authentication scheme types."""

    API_KEY = "apiKey"
    HTTP_BASIC = "http_basic"
    HTTP_BEARER = "http_bearer"
    OAUTH2 = "oauth2"
    OPENID_CONNECT = "openIdConnect"


class SchemaType(str, Enum):
    """JSON Schema types."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    NULL = "null"


@dataclass
class SchemaRef:
    """Unified JSON Schema type reference.

    Maps to JSON Schema for MCP tool input_schema generation.
    """

    type: str  # SchemaType value or composite (e.g., "string", "object")
    description: str = ""
    properties: dict[str, SchemaRef] = field(default_factory=dict)
    items: SchemaRef | None = None  # For array types
    required: list[str] = field(default_factory=list)
    enum: list[Any] = field(default_factory=list)
    format: str = ""  # date-time, email, uri, etc.
    default: Any = None
    nullable: bool = False
    additional_properties: SchemaRef | bool | None = None
    one_of: list[SchemaRef] = field(default_factory=list)
    any_of: list[SchemaRef] = field(default_factory=list)
    all_of: list[SchemaRef] = field(default_factory=list)
    ref_name: str = ""  # Original $ref name for traceability
    pattern: str = ""
    min_length: int | None = None
    max_length: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    example: Any = None

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to standard JSON Schema dict."""
        schema: dict[str, Any] = {}

        if self.type:
            schema["type"] = self.type
        if self.description:
            schema["description"] = self.description
        if self.format:
            schema["format"] = self.format
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        if self.pattern:
            schema["pattern"] = self.pattern
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.example is not None:
            schema["example"] = self.example

        if self.type == SchemaType.OBJECT or self.properties:
            if self.properties:
                schema["properties"] = {
                    name: prop.to_json_schema()
                    for name, prop in self.properties.items()
                }
            if self.required:
                schema["required"] = self.required
            if self.additional_properties is not None:
                if isinstance(self.additional_properties, SchemaRef):
                    schema["additionalProperties"] = (
                        self.additional_properties.to_json_schema()
                    )
                else:
                    schema["additionalProperties"] = self.additional_properties

        if self.type == SchemaType.ARRAY and self.items:
            schema["items"] = self.items.to_json_schema()

        if self.one_of:
            schema["oneOf"] = [s.to_json_schema() for s in self.one_of]
        if self.any_of:
            schema["anyOf"] = [s.to_json_schema() for s in self.any_of]
        if self.all_of:
            schema["allOf"] = [s.to_json_schema() for s in self.all_of]

        if self.nullable and self.type:
            # JSON Schema 2020-12 style
            schema["type"] = [self.type, "null"]

        return schema


@dataclass
class Parameter:
    """API parameter with location and schema."""

    name: str
    location: ParameterLocation
    schema: SchemaRef
    required: bool = False
    description: str = ""
    deprecated: bool = False
    example: Any = None


@dataclass
class RequestBody:
    """Request body definition."""

    content_type: str  # e.g., "application/json"
    schema: SchemaRef
    required: bool = False
    description: str = ""


@dataclass
class Response:
    """API response definition."""

    status_code: str  # "200", "default", etc.
    description: str = ""
    content_type: str = ""
    schema: SchemaRef | None = None


@dataclass
class PaginationConfig:
    """Detected pagination patterns for smart tool generation."""

    style: str  # "offset", "cursor", "page"
    page_param: str = ""
    limit_param: str = ""
    cursor_param: str = ""
    next_field: str = ""  # Response field containing next page info


@dataclass
class Endpoint:
    """Single API operation."""

    path: str
    method: HttpMethod
    operation_id: str
    summary: str = ""
    description: str = ""
    parameters: list[Parameter] = field(default_factory=list)
    request_body: RequestBody | None = None
    responses: list[Response] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    security: list[dict[str, list[str]]] = field(default_factory=list)
    deprecated: bool = False
    pagination: PaginationConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthScheme:
    """Authentication scheme definition."""

    name: str
    type: AuthType
    description: str = ""
    # API Key specifics
    api_key_name: str = ""
    api_key_location: str = ""  # "header", "query", "cookie"
    # OAuth2 specifics
    flows: dict[str, Any] = field(default_factory=dict)
    # OpenID Connect
    openid_connect_url: str = ""
    # HTTP specifics
    scheme: str = ""  # "basic", "bearer"
    bearer_format: str = ""


@dataclass
class ModelDef:
    """Named model/schema definition."""

    name: str
    schema: SchemaRef
    description: str = ""


@dataclass
class ServerInfo:
    """API server URL with optional variable templating."""

    url: str
    description: str = ""
    variables: dict[str, Any] = field(default_factory=dict)


@dataclass
class APISpec:
    """Top-level Intermediate Representation for a parsed API.

    This is the output of every parser and input to every generator.
    """

    title: str
    version: str
    description: str = ""
    base_url: str = ""
    servers: list[ServerInfo] = field(default_factory=list)
    endpoints: list[Endpoint] = field(default_factory=list)
    auth_schemes: list[AuthScheme] = field(default_factory=list)
    models: dict[str, ModelDef] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_format: str = ""  # "openapi3.0", "openapi3.1", "graphql", etc.
