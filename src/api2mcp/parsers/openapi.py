# SPDX-License-Identifier: MIT
"""OpenAPI 3.0/3.1 parser implementation.

Parses OpenAPI specifications into the IR (APISpec), handling:
- YAML and JSON formats
- $ref resolution with cycle detection (local + remote)
- OpenAPI 3.0.x and 3.1.x differences
- Authentication scheme extraction
- Schema validation against OpenAPI structure
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from api2mcp.core.exceptions import (
    CircularRefError,
    ParseError,
    ParseException,
    RefResolutionError,
    ValidationException,
)
from api2mcp.core.ir_schema import (
    APISpec,
    AuthScheme,
    AuthType,
    Endpoint,
    HttpMethod,
    ModelDef,
    Parameter,
    ParameterLocation,
    PaginationConfig,
    RequestBody,
    Response,
    SchemaRef,
    ServerInfo,
)
from api2mcp.core.parser import BaseParser

logger = logging.getLogger(__name__)

_VALID_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


# --------------------------------------------------------------------------- #
#  $ref Resolver
# --------------------------------------------------------------------------- #


class RefResolver:
    """Resolves $ref pointers in OpenAPI specs with cycle detection.

    Supports:
    - Local refs: #/components/schemas/User
    - File refs: ./models.yaml#/components/schemas/User
    - Remote refs: https://example.com/schemas.yaml#/Foo
    """

    def __init__(self, root_doc: dict[str, Any], base_path: Path | None = None) -> None:
        self._root = root_doc
        self._base_path = base_path
        self._external_cache: dict[str, dict[str, Any]] = {}

    def resolve(
        self, ref: str, visited: set[str] | None = None
    ) -> dict[str, Any]:
        """Resolve a $ref string to the target object.

        Args:
            ref: The $ref value (e.g., "#/components/schemas/User").
            visited: Set of refs already visited in this chain (cycle detection).

        Returns:
            The resolved dict.

        Raises:
            CircularRefError: If a cycle is detected.
            RefResolutionError: If the ref cannot be resolved.
        """
        if visited is None:
            visited = set()

        if ref in visited:
            raise CircularRefError(list(visited) + [ref])
        visited = visited | {ref}

        # Split into document part and JSON pointer part
        if "#" in ref:
            doc_part, pointer = ref.split("#", 1)
        else:
            doc_part, pointer = ref, ""

        # Get the document to resolve against
        if doc_part:
            doc = self._load_external(doc_part)
        else:
            doc = self._root

        # Navigate the JSON pointer
        target = self._navigate_pointer(doc, pointer, ref)

        # If target itself contains a $ref, resolve recursively
        if isinstance(target, dict) and "$ref" in target:
            return self.resolve(target["$ref"], visited)

        return target

    def resolve_all_refs(self, obj: Any, visited: set[str] | None = None) -> Any:
        """Recursively resolve all $ref occurrences in the given object.

        Args:
            obj: The object tree to resolve.
            visited: Cycle detection set.

        Returns:
            The fully resolved object tree.
        """
        if visited is None:
            visited = set()

        if isinstance(obj, dict):
            if "$ref" in obj:
                ref = obj["$ref"]
                if ref in visited:
                    # Return a placeholder to avoid infinite recursion
                    logger.warning("Circular $ref skipped: %s", ref)
                    return {"_circular_ref": ref}
                try:
                    resolved = self.resolve(ref, visited)
                except CircularRefError:
                    logger.warning("Circular $ref skipped: %s", ref)
                    return {"_circular_ref": ref}
                return self.resolve_all_refs(resolved, visited | {ref})
            return {
                key: self.resolve_all_refs(value, visited)
                for key, value in obj.items()
            }
        if isinstance(obj, list):
            return [self.resolve_all_refs(item, visited) for item in obj]
        return obj

    def _load_external(self, doc_path: str) -> dict[str, Any]:
        """Load an external document (file or URL)."""
        if doc_path in self._external_cache:
            return self._external_cache[doc_path]

        parsed_url = urlparse(doc_path)
        if parsed_url.scheme in ("http", "https"):
            doc = self._load_url(doc_path)
        elif self._base_path:
            file_path = self._base_path / doc_path
            doc = self._load_file(file_path)
        else:
            raise RefResolutionError(
                doc_path, f"Cannot resolve external ref without base path: {doc_path}"
            )

        self._external_cache[doc_path] = doc
        return doc

    def _load_file(self, path: Path) -> dict[str, Any]:
        """Load a YAML/JSON file."""
        if not path.exists():
            raise RefResolutionError(str(path), f"External ref file not found: {path}")
        text = path.read_text(encoding="utf-8")
        return _parse_yaml_or_json(text, str(path))

    def _load_url(self, url: str) -> dict[str, Any]:
        """Load a document from a URL (synchronous for simplicity in ref resolution)."""
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return _parse_yaml_or_json(resp.text, url)
        except httpx.HTTPError as exc:
            raise RefResolutionError(url, f"Failed to fetch remote ref: {exc}") from exc

    @staticmethod
    def _navigate_pointer(doc: dict[str, Any], pointer: str, original_ref: str) -> Any:
        """Navigate a JSON Pointer (RFC 6901) within a document."""
        if not pointer or pointer == "/":
            return doc

        # Remove leading slash
        parts = pointer.lstrip("/").split("/")
        current: Any = doc
        for part in parts:
            # Unescape JSON Pointer encoding
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                if part not in current:
                    raise RefResolutionError(
                        original_ref,
                        f"Pointer segment '{part}' not found. "
                        f"Available keys: {list(current.keys())}",
                    )
                current = current[part]
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError) as exc:
                    raise RefResolutionError(
                        original_ref,
                        f"Invalid array index '{part}' in $ref pointer",
                    ) from exc
            else:
                raise RefResolutionError(
                    original_ref,
                    f"Cannot navigate into non-container at '{part}'",
                )
        return current


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #


def _parse_yaml_or_json(text: str, source_name: str) -> dict[str, Any]:
    """Parse text as YAML or JSON, with error reporting."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        line = None
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1
        raise ParseException(
            f"Failed to parse {source_name}",
            errors=[ParseError(str(exc), line=line)],
        ) from exc

    if not isinstance(data, dict):
        raise ParseException(
            f"Expected mapping at root of {source_name}, got {type(data).__name__}"
        )
    return data


def _detect_openapi_version(doc: dict[str, Any]) -> tuple[int, int, int] | None:
    """Extract the OpenAPI version tuple, or None if not an OpenAPI doc."""
    raw = doc.get("openapi", "")
    if not isinstance(raw, str):
        return None
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", raw)
    if not match:
        match = re.match(r"^(\d+)\.(\d+)$", raw)
        if not match:
            return None
        return int(match[1]), int(match[2]), 0
    return int(match[1]), int(match[2]), int(match[3])


_PAGINATION_PARAM_PATTERNS: dict[str, list[str]] = {
    "offset": ["offset"],
    "cursor": ["cursor", "after", "before", "page_token", "next_token"],
    "page": ["page", "page_number"],
    "limit": ["limit", "per_page", "page_size", "count", "size"],
}


def _detect_pagination(params: list[Parameter]) -> PaginationConfig | None:
    """Heuristic pagination detection from parameter names."""
    param_names = {p.name.lower() for p in params}
    limit_param = ""
    for name in _PAGINATION_PARAM_PATTERNS["limit"]:
        if name in param_names:
            limit_param = name
            break

    if not limit_param:
        return None

    for name in _PAGINATION_PARAM_PATTERNS["cursor"]:
        if name in param_names:
            return PaginationConfig(
                style="cursor", cursor_param=name, limit_param=limit_param
            )

    for name in _PAGINATION_PARAM_PATTERNS["offset"]:
        if name in param_names:
            return PaginationConfig(
                style="offset", page_param=name, limit_param=limit_param
            )

    for name in _PAGINATION_PARAM_PATTERNS["page"]:
        if name in param_names:
            return PaginationConfig(
                style="page", page_param=name, limit_param=limit_param
            )

    return None


# --------------------------------------------------------------------------- #
#  Schema Conversion
# --------------------------------------------------------------------------- #


def _schema_to_ir(
    raw: dict[str, Any], resolver: RefResolver, ref_name: str = ""
) -> SchemaRef:
    """Convert an OpenAPI/JSON Schema dict to an IR SchemaRef."""
    if "$ref" in raw:
        resolved = resolver.resolve(raw["$ref"])
        name = raw["$ref"].rsplit("/", 1)[-1]
        return _schema_to_ir(resolved, resolver, ref_name=name)

    schema_type = raw.get("type", "")
    # OpenAPI 3.1: type can be a list like ["string", "null"]
    nullable = False
    if isinstance(schema_type, list):
        nullable = "null" in schema_type
        non_null = [t for t in schema_type if t != "null"]
        schema_type = non_null[0] if non_null else "string"

    # OpenAPI 3.0 nullable field
    if raw.get("nullable"):
        nullable = True

    sr = SchemaRef(
        type=schema_type,
        description=raw.get("description", ""),
        format=raw.get("format", ""),
        enum=raw.get("enum", []),
        default=raw.get("default"),
        nullable=nullable,
        ref_name=ref_name,
        pattern=raw.get("pattern", ""),
        min_length=raw.get("minLength"),
        max_length=raw.get("maxLength"),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
        example=raw.get("example"),
    )

    # Required fields (for object type)
    sr.required = raw.get("required", [])

    # Properties
    if "properties" in raw:
        sr.properties = {
            name: _schema_to_ir(prop_schema, resolver)
            for name, prop_schema in raw["properties"].items()
        }

    # Array items
    if "items" in raw:
        sr.items = _schema_to_ir(raw["items"], resolver)

    # additionalProperties
    ap = raw.get("additionalProperties")
    if isinstance(ap, dict):
        sr.additional_properties = _schema_to_ir(ap, resolver)
    elif isinstance(ap, bool):
        sr.additional_properties = ap

    # Composition
    if "oneOf" in raw:
        sr.one_of = [_schema_to_ir(s, resolver) for s in raw["oneOf"]]
    if "anyOf" in raw:
        sr.any_of = [_schema_to_ir(s, resolver) for s in raw["anyOf"]]
    if "allOf" in raw:
        sr.all_of = [_schema_to_ir(s, resolver) for s in raw["allOf"]]

    return sr


# --------------------------------------------------------------------------- #
#  Auth Extraction
# --------------------------------------------------------------------------- #


def _extract_auth_schemes(
    security_schemes: dict[str, Any], resolver: RefResolver
) -> list[AuthScheme]:
    """Extract authentication schemes from OpenAPI securitySchemes."""
    schemes: list[AuthScheme] = []
    for name, raw in security_schemes.items():
        if "$ref" in raw:
            raw = resolver.resolve(raw["$ref"])

        scheme_type = raw.get("type", "")
        if scheme_type == "apiKey":
            schemes.append(
                AuthScheme(
                    name=name,
                    type=AuthType.API_KEY,
                    description=raw.get("description", ""),
                    api_key_name=raw.get("name", ""),
                    api_key_location=raw.get("in", "header"),
                )
            )
        elif scheme_type == "http":
            http_scheme = raw.get("scheme", "").lower()
            if http_scheme == "basic":
                auth_type = AuthType.HTTP_BASIC
            else:
                auth_type = AuthType.HTTP_BEARER
            schemes.append(
                AuthScheme(
                    name=name,
                    type=auth_type,
                    description=raw.get("description", ""),
                    scheme=http_scheme,
                    bearer_format=raw.get("bearerFormat", ""),
                )
            )
        elif scheme_type == "oauth2":
            schemes.append(
                AuthScheme(
                    name=name,
                    type=AuthType.OAUTH2,
                    description=raw.get("description", ""),
                    flows=raw.get("flows", {}),
                )
            )
        elif scheme_type == "openIdConnect":
            schemes.append(
                AuthScheme(
                    name=name,
                    type=AuthType.OPENID_CONNECT,
                    description=raw.get("description", ""),
                    openid_connect_url=raw.get("openIdConnectUrl", ""),
                )
            )
        else:
            logger.warning("Unknown security scheme type '%s' for '%s'", scheme_type, name)
    return schemes


# --------------------------------------------------------------------------- #
#  Structural Validation — delegates to core.validator
# --------------------------------------------------------------------------- #

from api2mcp.core.validator import validate_openapi_structure as _validate_structure  # noqa: E402


# --------------------------------------------------------------------------- #
#  OpenAPI Parser
# --------------------------------------------------------------------------- #


class OpenAPIParser(BaseParser):
    """Parser for OpenAPI 3.0.x and 3.1.x specifications."""

    def detect(self, content: dict[str, Any]) -> bool:
        """Return True if content looks like an OpenAPI 3.x document."""
        version = _detect_openapi_version(content)
        return version is not None and version[0] == 3

    async def validate(
        self, source: str | Path, **kwargs: Any
    ) -> list[ParseError]:
        """Validate an OpenAPI spec without producing full IR."""
        text = await self._load_source(source)
        doc = _parse_yaml_or_json(text, str(source))

        errors = _validate_structure(doc)

        version = _detect_openapi_version(doc)
        if version is None:
            errors.append(ParseError("Not a valid OpenAPI document (missing 'openapi' field)"))
        elif version[0] != 3:
            errors.append(
                ParseError(
                    f"Unsupported OpenAPI version: {doc.get('openapi')}. "
                    f"Only 3.0.x and 3.1.x are supported."
                )
            )

        return errors

    async def parse(self, source: str | Path, **kwargs: Any) -> APISpec:
        """Parse an OpenAPI 3.0/3.1 spec into an IR APISpec.

        Args:
            source: Path to the spec file, or a URL.
            **kwargs: Options:
                - resolve_external_refs (bool): Whether to resolve external $refs.
                  Defaults to True.

        Returns:
            Parsed APISpec.

        Raises:
            ParseException: On invalid input.
            ValidationException: On structural validation failure.
        """
        # Emit PRE_PARSE hook (optional — plugins may not be loaded)
        try:
            from api2mcp.plugins import get_hook_manager
            from api2mcp.plugins.hooks import PRE_PARSE
            await get_hook_manager().emit(PRE_PARSE, path=str(source))
        except Exception:  # noqa: BLE001
            pass  # plugins are optional

        text = await self._load_source(source)
        doc = _parse_yaml_or_json(text, str(source))

        # Detect version
        version = _detect_openapi_version(doc)
        if version is None or version[0] != 3:
            raise ParseException(
                f"Not an OpenAPI 3.x document. Found: {doc.get('openapi', 'missing')}"
            )

        # Validate structure
        errors = _validate_structure(doc)
        hard_errors = [e for e in errors if e.severity == "error"]
        if hard_errors:
            raise ValidationException(
                f"OpenAPI validation failed with {len(hard_errors)} error(s)",
                errors=hard_errors,
            )
        for w in errors:
            if w.severity == "warning":
                logger.warning("Validation warning: %s", w)

        # Determine base path for external $ref resolution
        base_path: Path | None = None
        if isinstance(source, Path):
            base_path = source.parent
        elif isinstance(source, str) and not source.startswith(("http://", "https://")):
            base_path = Path(source).parent

        # Set up ref resolver
        resolver = RefResolver(doc, base_path)

        # Determine source format
        is_31 = version >= (3, 1, 0)
        source_format = "openapi3.1" if is_31 else "openapi3.0"

        # Extract info
        info = doc.get("info", {})
        title = info.get("title", "Untitled API")
        api_version = info.get("version", "0.0.0")
        description = info.get("description", "")

        # Extract servers
        servers = self._parse_servers(doc.get("servers", []))
        base_url = servers[0].url if servers else ""

        # Extract security schemes
        components = doc.get("components", {})
        security_schemes_raw = components.get("securitySchemes", {})
        auth_schemes = _extract_auth_schemes(security_schemes_raw, resolver)

        # Extract models (components/schemas)
        models = self._parse_models(components.get("schemas", {}), resolver)

        # Extract endpoints from paths
        global_security = doc.get("security", [])
        endpoints = self._parse_paths(
            doc.get("paths", {}), resolver, global_security
        )

        # OpenAPI 3.1: also extract from webhooks
        if is_31 and "webhooks" in doc:
            webhook_endpoints = self._parse_paths(
                doc["webhooks"], resolver, global_security, is_webhook=True
            )
            endpoints.extend(webhook_endpoints)

        api_spec = APISpec(
            title=title,
            version=api_version,
            description=description,
            base_url=base_url,
            servers=servers,
            endpoints=endpoints,
            auth_schemes=auth_schemes,
            models=models,
            metadata={
                "openapi_version": doc.get("openapi", ""),
                "external_docs": doc.get("externalDocs", {}),
                "tags": doc.get("tags", []),
            },
            source_format=source_format,
        )

        # Emit POST_PARSE hook
        try:
            from api2mcp.plugins import get_hook_manager
            from api2mcp.plugins.hooks import POST_PARSE
            await get_hook_manager().emit(POST_PARSE, api_spec=api_spec)
        except Exception:  # noqa: BLE001
            pass

        return api_spec

    # ------------------------------------------------------------------ #
    #  Internal parsing helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_servers(raw_servers: list[dict[str, Any]]) -> list[ServerInfo]:
        """Parse the servers array."""
        servers: list[ServerInfo] = []
        for srv in raw_servers:
            if not isinstance(srv, dict):
                continue
            servers.append(
                ServerInfo(
                    url=srv.get("url", ""),
                    description=srv.get("description", ""),
                    variables=srv.get("variables", {}),
                )
            )
        return servers

    @staticmethod
    def _parse_models(
        schemas: dict[str, Any], resolver: RefResolver
    ) -> dict[str, ModelDef]:
        """Parse components/schemas into ModelDef dict."""
        models: dict[str, ModelDef] = {}
        for name, schema_raw in schemas.items():
            if "$ref" in schema_raw:
                schema_raw = resolver.resolve(schema_raw["$ref"])
            models[name] = ModelDef(
                name=name,
                schema=_schema_to_ir(schema_raw, resolver, ref_name=name),
                description=schema_raw.get("description", ""),
            )
        return models

    def _parse_paths(
        self,
        paths: dict[str, Any],
        resolver: RefResolver,
        global_security: list[dict[str, list[str]]],
        is_webhook: bool = False,
    ) -> list[Endpoint]:
        """Parse paths object into list of Endpoint."""
        endpoints: list[Endpoint] = []
        op_id_counter: dict[str, int] = {}

        for path_key, path_item_raw in paths.items():
            if not isinstance(path_item_raw, dict):
                continue

            # Resolve $ref at path item level
            if "$ref" in path_item_raw:
                path_item_raw = resolver.resolve(path_item_raw["$ref"])

            # Path-level parameters
            path_level_params = path_item_raw.get("parameters", [])

            for method_str in _VALID_HTTP_METHODS:
                if method_str not in path_item_raw:
                    continue

                operation = path_item_raw[method_str]
                if not isinstance(operation, dict):
                    continue

                endpoint = self._parse_operation(
                    path=path_key,
                    method_str=method_str,
                    operation=operation,
                    path_level_params=path_level_params,
                    resolver=resolver,
                    global_security=global_security,
                    op_id_counter=op_id_counter,
                    is_webhook=is_webhook,
                )
                endpoints.append(endpoint)

        return endpoints

    def _parse_operation(
        self,
        path: str,
        method_str: str,
        operation: dict[str, Any],
        path_level_params: list[dict[str, Any]],
        resolver: RefResolver,
        global_security: list[dict[str, list[str]]],
        op_id_counter: dict[str, int],
        is_webhook: bool,
    ) -> Endpoint:
        """Parse a single operation into an Endpoint."""
        method = HttpMethod(method_str.upper())

        # Generate operation ID
        op_id = operation.get("operationId", "")
        if not op_id:
            op_id = self._generate_operation_id(method_str, path, op_id_counter)

        # Merge path-level + operation-level parameters
        params = self._merge_parameters(
            path_level_params,
            operation.get("parameters", []),
            resolver,
        )

        # Request body
        request_body = self._parse_request_body(
            operation.get("requestBody"), resolver
        )

        # Responses
        responses = self._parse_responses(operation.get("responses", {}), resolver)

        # Security (operation-level overrides global)
        security = operation.get("security", global_security)

        # Detect pagination
        pagination = _detect_pagination(params)

        metadata: dict[str, Any] = {}
        if is_webhook:
            metadata["webhook"] = True

        return Endpoint(
            path=path,
            method=method,
            operation_id=op_id,
            summary=operation.get("summary", ""),
            description=operation.get("description", ""),
            parameters=params,
            request_body=request_body,
            responses=responses,
            tags=operation.get("tags", []),
            security=security,
            deprecated=operation.get("deprecated", False),
            pagination=pagination,
            metadata=metadata,
        )

    @staticmethod
    def _generate_operation_id(
        method: str, path: str, counter: dict[str, int]
    ) -> str:
        """Generate an operation ID from method + path when operationId is missing."""
        # Convert /users/{user_id}/repos to users_user_id_repos
        clean = path.strip("/").replace("{", "").replace("}", "")
        segments = [s for s in clean.split("/") if s]
        candidate = f"{method}_{'_'.join(segments)}" if segments else method

        # Handle collisions
        if candidate in counter:
            counter[candidate] += 1
            return f"{candidate}_{counter[candidate]}"
        counter[candidate] = 0
        return candidate

    @staticmethod
    def _merge_parameters(
        path_params: list[dict[str, Any]],
        op_params: list[dict[str, Any]],
        resolver: RefResolver,
    ) -> list[Parameter]:
        """Merge path-level and operation-level parameters.

        Operation params override path params when name+in match.
        """
        # Build index of path params
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for raw in path_params:
            if "$ref" in raw:
                raw = resolver.resolve(raw["$ref"])
            key = (raw.get("name", ""), raw.get("in", ""))
            merged[key] = raw

        # Operation params override
        for raw in op_params:
            if "$ref" in raw:
                raw = resolver.resolve(raw["$ref"])
            key = (raw.get("name", ""), raw.get("in", ""))
            merged[key] = raw

        # Convert to IR
        result: list[Parameter] = []
        for raw in merged.values():
            location_str = raw.get("in", "query")
            try:
                location = ParameterLocation(location_str)
            except ValueError:
                logger.warning("Unknown parameter location '%s', defaulting to query", location_str)
                location = ParameterLocation.QUERY

            schema_raw = raw.get("schema", {"type": "string"})
            schema = _schema_to_ir(schema_raw, resolver)

            result.append(
                Parameter(
                    name=raw.get("name", ""),
                    location=location,
                    schema=schema,
                    required=raw.get("required", location == ParameterLocation.PATH),
                    description=raw.get("description", ""),
                    deprecated=raw.get("deprecated", False),
                    example=raw.get("example"),
                )
            )
        return result

    @staticmethod
    def _parse_request_body(
        raw: dict[str, Any] | None, resolver: RefResolver
    ) -> RequestBody | None:
        """Parse requestBody into IR RequestBody."""
        if raw is None:
            return None

        if "$ref" in raw:
            raw = resolver.resolve(raw["$ref"])

        content = raw.get("content", {})
        if not content:
            return None

        # Prefer application/json, fall back to first content type
        if "application/json" in content:
            ct = "application/json"
            media = content[ct]
        else:
            ct = next(iter(content))
            media = content[ct]

        schema_raw = media.get("schema", {"type": "object"})
        schema = _schema_to_ir(schema_raw, resolver)

        return RequestBody(
            content_type=ct,
            schema=schema,
            required=raw.get("required", False),
            description=raw.get("description", ""),
        )

    @staticmethod
    def _parse_responses(
        raw_responses: dict[str, Any], resolver: RefResolver
    ) -> list[Response]:
        """Parse responses object into list of IR Response."""
        responses: list[Response] = []
        for status_code, resp_raw in raw_responses.items():
            if "$ref" in resp_raw:
                resp_raw = resolver.resolve(resp_raw["$ref"])

            content = resp_raw.get("content", {})
            content_type = ""
            schema: SchemaRef | None = None

            if content:
                # Prefer application/json
                if "application/json" in content:
                    content_type = "application/json"
                    media = content[content_type]
                else:
                    content_type = next(iter(content))
                    media = content[content_type]

                if "schema" in media:
                    schema = _schema_to_ir(media["schema"], resolver)

            responses.append(
                Response(
                    status_code=str(status_code),
                    description=resp_raw.get("description", ""),
                    content_type=content_type,
                    schema=schema,
                )
            )
        return responses

    # ------------------------------------------------------------------ #
    #  Source loading
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _load_source(source: str | Path) -> str:
        """Load spec content from a file path or URL."""
        if isinstance(source, Path):
            path = source
        elif source.startswith(("http://", "https://")):
            async with httpx.AsyncClient() as client:
                resp = await client.get(source, timeout=30, follow_redirects=True)
                resp.raise_for_status()
                return resp.text
        else:
            path = Path(source)

        if not path.exists():
            raise ParseException(f"File not found: {path}")
        return path.read_text(encoding="utf-8")
