# SPDX-License-Identifier: MIT
"""GraphQL schema parser for API2MCP.

Converts a GraphQL API schema into the IR (APISpec) so it can be used with
the same generators and orchestration layer as REST APIs.

Supports two input formats
--------------------------
* **SDL** (Schema Definition Language) — plain ``.graphql`` / ``.gql`` text
  files, or raw SDL strings passed directly.
* **Introspection JSON** — the JSON response from a GraphQL server's
  ``{__schema {...}}`` introspection query, optionally wrapped in a
  ``{"data": {...}}`` envelope.

GraphQL → IR mapping
--------------------
* Each field on the root ``Query`` type  → :data:`~api2mcp.core.ir_schema.HttpMethod.QUERY` Endpoint
* Each field on the root ``Mutation`` type → :data:`~api2mcp.core.ir_schema.HttpMethod.MUTATION` Endpoint
* Each field on the root ``Subscription`` type →
  :data:`~api2mcp.core.ir_schema.HttpMethod.SUBSCRIPTION` Endpoint
* Field arguments → :class:`~api2mcp.core.ir_schema.Parameter` objects with
  ``location = ParameterLocation.BODY``
* GraphQL types → :class:`~api2mcp.core.ir_schema.SchemaRef`
* Input types, enums, scalars all map to appropriate JSON Schema equivalents
* Named models (non-root object types) stored in :attr:`APISpec.models`
* Fragments resolved inline — not stored in the IR (SDL schema has no
  fragment definitions; introspection JSON is pre-resolved by the server)

Requires
--------
The ``graphql-core`` package (optional dependency group ``graphql``):

.. code-block:: shell

    pip install api2mcp[graphql]
    # or
    pip install graphql-core>=3.2.7
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from api2mcp.core.exceptions import ParseError, ParseException
from api2mcp.core.ir_schema import (
    APISpec,
    Endpoint,
    HttpMethod,
    ModelDef,
    Parameter,
    ParameterLocation,
    RequestBody,
    Response,
    SchemaRef,
    ServerInfo,
)
from api2mcp.core.parser import BaseParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional graphql-core import
# ---------------------------------------------------------------------------

try:
    from graphql import GraphQLSchema, build_schema as _gql_build_schema
    from graphql.type import (
        GraphQLEnumType,
        GraphQLInputObjectType,
        GraphQLInterfaceType,
        GraphQLList,
        GraphQLNonNull,
        GraphQLObjectType,
        GraphQLScalarType,
        GraphQLUnionType,
    )

    _HAS_GRAPHQL_CORE = True
except ImportError:  # pragma: no cover
    # Stub types so isinstance() checks and Pyright are satisfied at import time.
    # The _require_graphql_core() guard ensures these stubs are never actually hit.

    class GraphQLSchema:  # type: ignore[no-redef]
        query_type: Any = None
        mutation_type: Any = None
        subscription_type: Any = None
        type_map: dict[str, Any] = {}
        description: str | None = None

    class GraphQLNonNull:  # type: ignore[no-redef]
        of_type: Any = None

    class GraphQLList:  # type: ignore[no-redef]
        of_type: Any = None

    class GraphQLScalarType:  # type: ignore[no-redef]
        name: str = ""
        description: str | None = None

    class GraphQLEnumType:  # type: ignore[no-redef]
        name: str = ""
        description: str | None = None
        values: dict[str, Any] = {}

    class GraphQLInputObjectType:  # type: ignore[no-redef]
        name: str = ""
        description: str | None = None
        fields: dict[str, Any] = {}

    class GraphQLObjectType:  # type: ignore[no-redef]
        name: str = ""
        description: str | None = None
        fields: dict[str, Any] = {}

    class GraphQLInterfaceType:  # type: ignore[no-redef]
        name: str = ""
        description: str | None = None
        fields: dict[str, Any] = {}

    class GraphQLUnionType:  # type: ignore[no-redef]
        name: str = ""
        description: str | None = None
        types: list[Any] = []

    def _gql_build_schema(_sdl: str) -> GraphQLSchema:  # type: ignore[misc]
        raise ImportError("graphql-core not installed")

    _HAS_GRAPHQL_CORE = False


def _require_graphql_core() -> None:
    """Raise a helpful ImportError if graphql-core is not installed."""
    if not _HAS_GRAPHQL_CORE:  # pragma: no cover
        raise ImportError(
            "graphql-core is required for GraphQL parsing. "
            "Install it with: pip install api2mcp[graphql]  "
            "or: pip install 'graphql-core>=3.2.7'"
        )


# ---------------------------------------------------------------------------
# Scalar type mapping
# ---------------------------------------------------------------------------

_BUILTIN_SCALAR_MAP: dict[str, str] = {
    "String": "string",
    "ID": "string",
    "Int": "integer",
    "Float": "number",
    "Boolean": "boolean",
    # Common custom scalars
    "DateTime": "string",
    "Date": "string",
    "Time": "string",
    "URL": "string",
    "URI": "string",
    "JSON": "object",
    "JSONObject": "object",
    "BigInt": "integer",
    "Long": "integer",
    "Decimal": "number",
    "Bytes": "string",
    "UUID": "string",
    "Email": "string",
    "Upload": "string",
}

_BUILTIN_SCALAR_FORMAT: dict[str, str] = {
    "DateTime": "date-time",
    "Date": "date",
    "Time": "time",
    "URL": "uri",
    "URI": "uri",
    "UUID": "uuid",
    "Email": "email",
    "ID": "id",
}

# ---------------------------------------------------------------------------
# GraphQL type → IR SchemaRef (SDL path)
# ---------------------------------------------------------------------------


def _type_to_schema_ref(gql_type: Any, *, seen: set[str] | None = None) -> SchemaRef:
    """Recursively map a graphql-core type object to an IR :class:`SchemaRef`.

    Args:
        gql_type: A graphql-core type instance (e.g. ``GraphQLNonNull``,
            ``GraphQLScalarType``, ``GraphQLObjectType`` …).
        seen: Type names already visited — prevents infinite recursion on
            cyclic object types.

    Returns:
        Equivalent :class:`~api2mcp.core.ir_schema.SchemaRef`.
    """
    if seen is None:
        seen = set()

    # Unwrap NonNull (affects required-ness at arg level, not schema shape)
    if isinstance(gql_type, GraphQLNonNull):
        return _type_to_schema_ref(gql_type.of_type, seen=seen)

    # List
    if isinstance(gql_type, GraphQLList):
        return SchemaRef(
            type="array",
            items=_type_to_schema_ref(gql_type.of_type, seen=seen),
        )

    # Scalar
    if isinstance(gql_type, GraphQLScalarType):
        name = gql_type.name
        json_type = _BUILTIN_SCALAR_MAP.get(name, "string")
        fmt = _BUILTIN_SCALAR_FORMAT.get(name, "")
        desc = gql_type.description or ""
        return SchemaRef(type=json_type, format=fmt, description=desc, ref_name=name)

    # Enum
    if isinstance(gql_type, GraphQLEnumType):
        values = list(gql_type.values.keys())
        return SchemaRef(
            type="string",
            enum=values,
            description=gql_type.description or "",
            ref_name=gql_type.name,
        )

    # Input object
    if isinstance(gql_type, GraphQLInputObjectType):
        type_name = gql_type.name
        if type_name in seen:
            # Circular reference — return a ref placeholder
            return SchemaRef(type="object", ref_name=type_name)
        seen = seen | {type_name}
        props: dict[str, SchemaRef] = {}
        required_fields: list[str] = []
        for fname, field in gql_type.fields.items():
            field_schema = _type_to_schema_ref(field.type, seen=seen)
            field_schema.description = field.description or field_schema.description
            props[fname] = field_schema
            if isinstance(field.type, GraphQLNonNull):
                required_fields.append(fname)
        return SchemaRef(
            type="object",
            properties=props,
            required=required_fields,
            description=gql_type.description or "",
            ref_name=type_name,
        )

    # Object / Interface (output types — map structure for response schema)
    if isinstance(gql_type, (GraphQLObjectType, GraphQLInterfaceType)):
        type_name = gql_type.name
        if type_name in seen:
            return SchemaRef(type="object", ref_name=type_name)
        seen = seen | {type_name}
        props = {}
        for fname, field in gql_type.fields.items():
            field_schema = _type_to_schema_ref(field.type, seen=seen)
            field_schema.description = field.description or field_schema.description
            props[fname] = field_schema
        return SchemaRef(
            type="object",
            properties=props,
            description=gql_type.description or "",
            ref_name=type_name,
        )

    # Union
    if isinstance(gql_type, GraphQLUnionType):
        return SchemaRef(
            type="object",
            any_of=[_type_to_schema_ref(t, seen=seen) for t in gql_type.types],
            description=gql_type.description or "",
            ref_name=gql_type.name,
        )

    # Fallback — unknown type
    logger.debug("Unknown GraphQL type %r — defaulting to string", gql_type)
    return SchemaRef(type="string")


def _arg_to_parameter(arg_name: str, arg: Any) -> Parameter:
    """Convert a GraphQL field argument to an IR :class:`Parameter`.

    Args:
        arg_name: The argument name (dict key in field.args).
        arg: ``GraphQLArgument`` instance from graphql-core.

    Returns:
        Equivalent :class:`~api2mcp.core.ir_schema.Parameter`.
    """
    is_required = isinstance(arg.type, GraphQLNonNull)
    schema = _type_to_schema_ref(arg.type)
    schema.description = arg.description or schema.description

    default: Any = None
    if arg.default_value_is_set:
        try:
            default = arg.default_value
        except Exception as exc:
            logger.debug("Ignoring GraphQL parse detail: %s", exc)

    if default is not None:
        schema.default = default

    return Parameter(
        name=arg_name,
        location=ParameterLocation.BODY,
        schema=schema,
        required=is_required,
        description=arg.description or "",
    )


def _field_to_endpoint(
    field_name: str,
    field: Any,
    method: HttpMethod,
    graphql_endpoint: str = "/graphql",
) -> Endpoint:
    """Convert a single root-type GraphQL field to an IR :class:`Endpoint`.

    Args:
        field_name: The operation name (e.g. ``"getUser"``).
        field: ``GraphQLField`` from graphql-core.
        method: ``HttpMethod.QUERY``, ``MUTATION``, or ``SUBSCRIPTION``.
        graphql_endpoint: The HTTP path of the GraphQL endpoint.

    Returns:
        Equivalent :class:`~api2mcp.core.ir_schema.Endpoint`.
    """
    params: list[Parameter] = []
    for aname, arg in field.args.items():
        params.append(_arg_to_parameter(aname, arg))

    # Build a request body encompassing all arguments as a single object
    request_body: RequestBody | None = None
    if params:
        props = {p.name: p.schema for p in params}
        required = [p.name for p in params if p.required]
        body_schema = SchemaRef(type="object", properties=props, required=required)
        request_body = RequestBody(
            content_type="application/json",
            schema=body_schema,
            required=bool(required),
            description="GraphQL operation variables",
        )

    # Response schema from the return type
    return_schema = _type_to_schema_ref(field.type)
    responses = [
        Response(
            status_code="200",
            description="Successful GraphQL response",
            content_type="application/json",
            schema=return_schema,
        )
    ]

    tags: list[str] = [method.value.lower()]  # "query", "mutation", "subscription"
    metadata: dict[str, Any] = {"graphql_field": field_name}
    if method == HttpMethod.SUBSCRIPTION:
        metadata["subscription"] = True

    return Endpoint(
        path=f"{graphql_endpoint}/{field_name}",
        method=method,
        operation_id=field_name,
        summary=field.description or f"GraphQL {method.value.lower()} — {field_name}",
        description=field.description or "",
        parameters=params,
        request_body=request_body,
        responses=responses,
        tags=tags,
        deprecated=field.is_deprecated,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# SDL Parser (uses graphql-core build_schema)
# ---------------------------------------------------------------------------


class _SDLParser:
    """Parses GraphQL SDL text into an APISpec using graphql-core."""

    def __init__(self, graphql_endpoint: str = "/graphql") -> None:
        self._endpoint = graphql_endpoint

    def parse(self, sdl_text: str, title: str = "GraphQL API") -> APISpec:
        """Parse SDL text and return an :class:`APISpec`."""
        _require_graphql_core()

        try:
            schema: GraphQLSchema = _gql_build_schema(sdl_text)
        except Exception as exc:
            raise ParseException(
                f"Failed to build GraphQL schema from SDL: {exc}",
                errors=[ParseError(str(exc))],
            ) from exc

        endpoints: list[Endpoint] = []
        models: dict[str, ModelDef] = {}

        # Collect root type operations
        root_types = [
            (schema.query_type, HttpMethod.QUERY),
            (schema.mutation_type, HttpMethod.MUTATION),
            (schema.subscription_type, HttpMethod.SUBSCRIPTION),
        ]
        for root_type, method in root_types:
            if root_type is None:
                continue
            for field_name, field in root_type.fields.items():
                endpoints.append(
                    _field_to_endpoint(field_name, field, method, self._endpoint)
                )

        # Collect named models from non-root, non-builtin object types
        for type_name, gql_type in schema.type_map.items():
            if type_name.startswith("__"):
                continue  # skip introspection types
            root_names = {
                t.name
                for t in [schema.query_type, schema.mutation_type, schema.subscription_type]
                if t is not None
            }
            if type_name in root_names:
                continue
            if isinstance(gql_type, (GraphQLObjectType, GraphQLInputObjectType)):
                schema_ref = _type_to_schema_ref(gql_type)
                models[type_name] = ModelDef(
                    name=type_name,
                    schema=schema_ref,
                    description=gql_type.description or "",
                )

        return APISpec(
            title=title,
            version="1.0.0",
            description=schema.description or "",
            endpoints=endpoints,
            models=models,
            source_format="graphql",
        )

    def validate(self, sdl_text: str) -> list[ParseError]:
        """Validate SDL text and return any parse errors."""
        _require_graphql_core()
        errors: list[ParseError] = []
        try:
            _gql_build_schema(sdl_text)
        except Exception as exc:
            errors.append(ParseError(str(exc)))
        return errors


# ---------------------------------------------------------------------------
# Introspection JSON Parser
# ---------------------------------------------------------------------------


class _IntrospectionParser:
    """Parses a GraphQL introspection query result into an APISpec."""

    def __init__(self, graphql_endpoint: str = "/graphql") -> None:
        self._endpoint = graphql_endpoint

    def parse(self, data: dict[str, Any], title: str = "GraphQL API") -> APISpec:
        """Parse an introspection result dict and return an :class:`APISpec`."""
        schema_data = self._unwrap_schema(data)

        # Build a type lookup: name → type dict
        type_map: dict[str, dict[str, Any]] = {}
        for t in schema_data.get("types", []):
            if t.get("name"):
                type_map[t["name"]] = t

        endpoints: list[Endpoint] = []
        models: dict[str, ModelDef] = {}

        # Root operation types
        query_type_name = (schema_data.get("queryType") or {}).get("name")
        mutation_type_name = (schema_data.get("mutationType") or {}).get("name")
        subscription_type_name = (schema_data.get("subscriptionType") or {}).get("name")

        root_pairs = [
            (query_type_name, HttpMethod.QUERY),
            (mutation_type_name, HttpMethod.MUTATION),
            (subscription_type_name, HttpMethod.SUBSCRIPTION),
        ]
        root_names: set[str] = {n for n, _ in root_pairs if n}

        for type_name, method in root_pairs:
            if not type_name or type_name not in type_map:
                continue
            root_type = type_map[type_name]
            for field in root_type.get("fields") or []:
                endpoint = self._field_dict_to_endpoint(field, method, type_map)
                endpoints.append(endpoint)

        # Named models (non-root object and input types)
        for type_name, type_dict in type_map.items():
            if type_name.startswith("__"):
                continue
            if type_name in root_names:
                continue
            kind = type_dict.get("kind", "")
            if kind in ("OBJECT", "INPUT_OBJECT"):
                schema_ref = self._type_ref_to_schema_ref(
                    {"kind": kind, "name": type_name, "ofType": None},
                    type_map,
                    seen=set(),
                )
                models[type_name] = ModelDef(
                    name=type_name,
                    schema=schema_ref,
                    description=type_dict.get("description") or "",
                )

        description = schema_data.get("description") or ""
        return APISpec(
            title=title,
            version="1.0.0",
            description=description,
            endpoints=endpoints,
            models=models,
            source_format="graphql",
        )

    def validate(self, data: dict[str, Any]) -> list[ParseError]:
        """Validate an introspection result and return any structural errors."""
        errors: list[ParseError] = []
        try:
            schema_data = self._unwrap_schema(data)
        except ParseException as exc:
            return list(exc.errors) if exc.errors else [ParseError(str(exc))]

        if "types" not in schema_data:
            errors.append(ParseError("Introspection result is missing '__schema.types'"))
        if not (schema_data.get("queryType") or schema_data.get("mutationType")):
            errors.append(
                ParseError(
                    "Introspection result has neither queryType nor mutationType — "
                    "no operations to convert"
                )
            )
        return errors

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _unwrap_schema(data: dict[str, Any]) -> dict[str, Any]:
        """Extract the __schema dict from various envelope formats."""
        if "__schema" in data:
            return data["__schema"]
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
            if "__schema" in inner:
                return inner["__schema"]
        raise ParseException(
            "Could not find '__schema' in the introspection result. "
            "Expected either {'__schema': ...} or {'data': {'__schema': ...}}.",
            errors=[ParseError("Missing '__schema' key")],
        )

    def _field_dict_to_endpoint(
        self,
        field: dict[str, Any],
        method: HttpMethod,
        type_map: dict[str, dict[str, Any]],
    ) -> Endpoint:
        """Convert an introspection field dict to an Endpoint."""
        field_name = field.get("name", "unknown")
        description = field.get("description") or ""

        params: list[Parameter] = []
        for arg in field.get("args") or []:
            param = self._arg_dict_to_parameter(arg, type_map)
            params.append(param)

        request_body: RequestBody | None = None
        if params:
            props = {p.name: p.schema for p in params}
            required = [p.name for p in params if p.required]
            body_schema = SchemaRef(type="object", properties=props, required=required)
            request_body = RequestBody(
                content_type="application/json",
                schema=body_schema,
                required=bool(required),
                description="GraphQL operation variables",
            )

        return_schema = self._type_ref_to_schema_ref(
            field.get("type") or {}, type_map, seen=set()
        )
        responses = [
            Response(
                status_code="200",
                description="Successful GraphQL response",
                content_type="application/json",
                schema=return_schema,
            )
        ]

        is_deprecated = field.get("isDeprecated", False)
        tags = [method.value.lower()]
        metadata: dict[str, Any] = {"graphql_field": field_name}
        if method == HttpMethod.SUBSCRIPTION:
            metadata["subscription"] = True

        return Endpoint(
            path=f"{self._endpoint}/{field_name}",
            method=method,
            operation_id=field_name,
            summary=description or f"GraphQL {method.value.lower()} — {field_name}",
            description=description,
            parameters=params,
            request_body=request_body,
            responses=responses,
            tags=tags,
            deprecated=is_deprecated,
            metadata=metadata,
        )

    def _arg_dict_to_parameter(
        self,
        arg: dict[str, Any],
        type_map: dict[str, dict[str, Any]],
    ) -> Parameter:
        """Convert an introspection argument dict to a Parameter."""
        arg_name = arg.get("name", "")
        description = arg.get("description") or ""
        type_ref = arg.get("type") or {}
        is_required = type_ref.get("kind") == "NON_NULL"

        schema = self._type_ref_to_schema_ref(type_ref, type_map, seen=set())
        schema.description = description or schema.description

        default_value = arg.get("defaultValue")
        if default_value is not None:
            schema.default = default_value

        return Parameter(
            name=arg_name,
            location=ParameterLocation.BODY,
            schema=schema,
            required=is_required,
            description=description,
        )

    def _type_ref_to_schema_ref(
        self,
        type_ref: dict[str, Any],
        type_map: dict[str, dict[str, Any]],
        seen: set[str],
    ) -> SchemaRef:
        """Recursively convert an introspection type reference to a SchemaRef."""
        kind = type_ref.get("kind", "")
        name = type_ref.get("name")
        of_type = type_ref.get("ofType")

        if kind == "NON_NULL":
            return self._type_ref_to_schema_ref(of_type or {}, type_map, seen)

        if kind == "LIST":
            return SchemaRef(
                type="array",
                items=self._type_ref_to_schema_ref(of_type or {}, type_map, seen),
            )

        if kind == "SCALAR" and name:
            json_type = _BUILTIN_SCALAR_MAP.get(name, "string")
            fmt = _BUILTIN_SCALAR_FORMAT.get(name, "")
            return SchemaRef(type=json_type, format=fmt, ref_name=name)

        if kind == "ENUM" and name:
            full_type = type_map.get(name, {})
            enum_values = [
                ev.get("name", "") for ev in (full_type.get("enumValues") or [])
            ]
            return SchemaRef(
                type="string",
                enum=enum_values,
                description=full_type.get("description") or "",
                ref_name=name,
            )

        if kind in ("OBJECT", "INTERFACE") and name:
            if name in seen:
                return SchemaRef(type="object", ref_name=name)
            full_type = type_map.get(name, {})
            new_seen = seen | {name}
            props: dict[str, SchemaRef] = {}
            for field in full_type.get("fields") or []:
                fname = field.get("name", "")
                fschema = self._type_ref_to_schema_ref(
                    field.get("type") or {}, type_map, new_seen
                )
                fschema.description = field.get("description") or ""
                props[fname] = fschema
            return SchemaRef(
                type="object",
                properties=props,
                description=full_type.get("description") or "",
                ref_name=name,
            )

        if kind == "INPUT_OBJECT" and name:
            if name in seen:
                return SchemaRef(type="object", ref_name=name)
            full_type = type_map.get(name, {})
            new_seen = seen | {name}
            props = {}
            required_fields: list[str] = []
            for field in full_type.get("inputFields") or []:
                fname = field.get("name", "")
                fref = field.get("type") or {}
                fschema = self._type_ref_to_schema_ref(fref, type_map, new_seen)
                fschema.description = field.get("description") or ""
                props[fname] = fschema
                if fref.get("kind") == "NON_NULL":
                    required_fields.append(fname)
            return SchemaRef(
                type="object",
                properties=props,
                required=required_fields,
                description=full_type.get("description") or "",
                ref_name=name,
            )

        if kind == "UNION" and name:
            full_type = type_map.get(name, {})
            any_of = [
                self._type_ref_to_schema_ref(
                    {"kind": "OBJECT", "name": t.get("name"), "ofType": None},
                    type_map,
                    seen,
                )
                for t in (full_type.get("possibleTypes") or [])
            ]
            return SchemaRef(
                type="object",
                any_of=any_of,
                description=full_type.get("description") or "",
                ref_name=name,
            )

        # Fallback
        logger.debug("Unresolved type ref kind=%r name=%r — defaulting to string", kind, name)
        return SchemaRef(type="string")


# ---------------------------------------------------------------------------
# Public GraphQLParser
# ---------------------------------------------------------------------------


class GraphQLParser(BaseParser):
    """Parser for GraphQL schemas (SDL and introspection JSON).

    Args:
        graphql_endpoint: The HTTP path of the GraphQL endpoint that will be
            stored in the IR.  Defaults to ``"/graphql"``.

    Example::

        parser = GraphQLParser()
        spec = await parser.parse("schema.graphql")
        # or
        spec = await parser.parse("introspection.json")
    """

    def __init__(self, graphql_endpoint: str = "/graphql") -> None:
        self._graphql_endpoint = graphql_endpoint

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def detect(self, content: dict[str, Any]) -> bool:
        """Return ``True`` if *content* looks like a GraphQL introspection result."""
        if "__schema" in content:
            return True
        if "data" in content and isinstance(content["data"], dict):
            return "__schema" in content["data"]
        return False

    async def validate(self, source: str | Path, **_kwargs: Any) -> list[ParseError]:
        """Validate a GraphQL schema without producing full IR."""
        text = await self._load_source(source)
        format_, data = self._detect_format(text)

        if format_ == "introspection":
            assert data is not None
            return _IntrospectionParser(self._graphql_endpoint).validate(data)
        else:
            return _SDLParser(self._graphql_endpoint).validate(text)

    async def parse(self, source: str | Path, **kwargs: Any) -> APISpec:
        """Parse a GraphQL schema into an IR :class:`APISpec`.

        Args:
            source: File path, URL, or raw SDL/JSON string.
            **kwargs: Optional:

                * ``title`` (str) — API title.  Defaults to the filename
                  stem or ``"GraphQL API"``.
                * ``endpoint_url`` (str) — overrides the GraphQL HTTP endpoint
                  URL stored in the IR.
                * ``base_url`` (str) — base URL of the GraphQL server (e.g.
                  ``"https://api.example.com"``).

        Returns:
            Parsed :class:`~api2mcp.core.ir_schema.APISpec`.

        Raises:
            :class:`~api2mcp.core.exceptions.ParseException`: On invalid input.
            :class:`ImportError`: If ``graphql-core`` is not installed.
        """
        text = await self._load_source(source)

        # Determine title from kwargs or source path
        title: str = kwargs.get("title", "")
        if not title:
            if isinstance(source, Path):
                title = source.stem.replace("_", " ").replace("-", " ").title()
            elif isinstance(source, str) and not source.startswith(("http://", "https://")):
                stem = Path(source).stem
                title = stem.replace("_", " ").replace("-", " ").title()
            else:
                title = "GraphQL API"

        base_url: str = kwargs.get("base_url", "")
        endpoint_url: str = kwargs.get("endpoint_url", self._graphql_endpoint)
        gql_parser_endpoint = endpoint_url

        format_, data = self._detect_format(text)

        if format_ == "introspection":
            assert data is not None
            spec = _IntrospectionParser(gql_parser_endpoint).parse(data, title=title)
        else:
            spec = _SDLParser(gql_parser_endpoint).parse(text, title=title)

        # Attach server info if base_url was provided
        if base_url:
            gql_url = base_url.rstrip("/") + endpoint_url
            spec.servers = [ServerInfo(url=gql_url, description="GraphQL endpoint")]
            spec.base_url = gql_url

        return spec

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_format(
        text: str,
    ) -> tuple[str, dict[str, Any] | None]:
        """Detect whether *text* is SDL or an introspection JSON result.

        Returns:
            A ``(format, data)`` tuple where *format* is ``"sdl"`` or
            ``"introspection"`` and *data* is the parsed dict (introspection
            only; ``None`` for SDL).
        """
        stripped = text.lstrip()
        if stripped.startswith(("{", "[")):
            # Looks like JSON — try to parse
            try:
                data = json.loads(text)
                if isinstance(data, dict) and (
                    "__schema" in data
                    or ("data" in data and "__schema" in (data.get("data") or {}))
                ):
                    return "introspection", data
            except json.JSONDecodeError as exc:
                logger.debug("Ignoring GraphQL parse detail: %s", exc)

        return "sdl", None

    @staticmethod
    async def _load_source(source: str | Path) -> str:
        """Load source content from a file path or URL."""
        if isinstance(source, Path):
            if not source.exists():
                raise ParseException(f"File not found: {source}")
            return source.read_text(encoding="utf-8")

        if isinstance(source, str):
            if source.startswith(("http://", "https://")):
                async with httpx.AsyncClient() as client:
                    resp = await client.get(source, timeout=30, follow_redirects=True)
                    resp.raise_for_status()
                    return resp.text
            # Check if it's a file path or raw SDL/JSON string
            path = Path(source)
            if path.suffix in (".graphql", ".gql", ".json") and path.exists():
                return path.read_text(encoding="utf-8")
            # Treat as raw SDL/JSON content
            return source

        raise ParseException(f"Unsupported source type: {type(source).__name__}")
