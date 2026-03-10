# SPDX-License-Identifier: MIT
"""Postman Collection v2.1 parser implementation (F3.3).

Parses Postman Collection v2.1 JSON into the IR (APISpec).

Design decisions:
- Variables (``{{var}}``) are substituted during parsing — not stored in IR.
- Collection auth is mapped to IR AuthScheme and applied as a fallback when
  individual requests carry no auth.
- Folder hierarchy is flattened into endpoint tags so tool generators can
  group tools by folder.
- operation_id is derived from ``<folder>/<request_name>`` → snake_case.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from api2mcp.core.exceptions import ParseError, ParseException
from api2mcp.core.ir_schema import (
    APISpec,
    AuthScheme,
    AuthType,
    Endpoint,
    HttpMethod,
    Parameter,
    ParameterLocation,
    RequestBody,
    Response,
    SchemaRef,
    ServerInfo,
)
from api2mcp.core.parser import BaseParser

logger = logging.getLogger(__name__)

# Regex matching Postman variable placeholders: {{varName}}
_VAR_RE = re.compile(r"\{\{([^}]+)\}\}")

# Postman Collection v2.1 schema URL fragment (used for detection)
_SCHEMA_V21 = "v2.1"
_SCHEMA_V20 = "v2.0"

_HTTP_METHODS: frozenset[str] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
)


# --------------------------------------------------------------------------- #
#  Variable substitution
# --------------------------------------------------------------------------- #


def substitute_variables(text: str, variables: dict[str, str]) -> str:
    """Replace all ``{{varName}}`` placeholders in *text* with their values.

    Unknown variables are left as-is (e.g. ``{{unknownVar}}``).
    """
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        return variables.get(name, match.group(0))

    return _VAR_RE.sub(_replace, text)


def extract_variables(items: list[dict[str, Any]]) -> dict[str, str]:
    """Build a ``{name: value}`` dict from a Postman *variable* array."""
    result: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("key") or item.get("id") or ""
        value = item.get("value", "")
        if name:
            result[str(name)] = str(value) if value is not None else ""
    return result


# --------------------------------------------------------------------------- #
#  Auth parsing
# --------------------------------------------------------------------------- #


def _kv_list_to_dict(items: list[dict[str, Any]]) -> dict[str, str]:
    """Convert a Postman key-value list to a plain dict."""
    return {str(i.get("key", "")): str(i.get("value", "")) for i in items if isinstance(i, dict)}


def parse_auth(auth: dict[str, Any] | None) -> AuthScheme | None:
    """Convert a Postman auth object to an IR AuthScheme, or None."""
    if not auth or not isinstance(auth, dict):
        return None

    auth_type = str(auth.get("type", "")).lower()

    if auth_type == "bearer":
        bearer_items = auth.get("bearer", [])
        kv = _kv_list_to_dict(bearer_items if isinstance(bearer_items, list) else [])
        return AuthScheme(
            name="bearer",
            type=AuthType.HTTP_BEARER,
            scheme="bearer",
            bearer_format=kv.get("algorithm", ""),
        )

    if auth_type == "basic":
        return AuthScheme(name="basic", type=AuthType.HTTP_BASIC, scheme="basic")

    if auth_type in ("apikey", "api_key"):
        apikey_items = auth.get("apikey", auth.get("api_key", []))
        kv = _kv_list_to_dict(apikey_items if isinstance(apikey_items, list) else [])
        location = kv.get("in", "header")
        return AuthScheme(
            name="apiKey",
            type=AuthType.API_KEY,
            api_key_name=kv.get("key", ""),
            api_key_location=location,
        )

    if auth_type == "oauth2":
        return AuthScheme(
            name="oauth2",
            type=AuthType.OAUTH2,
            flows={},
        )

    # Unknown / noauth — skip
    return None


# --------------------------------------------------------------------------- #
#  URL utilities
# --------------------------------------------------------------------------- #


def _normalise_url_object(url_obj: dict[str, Any], variables: dict[str, str]) -> str:
    """Convert a Postman URL object to a normalised path string.

    Returns the path portion only (e.g. ``/api/users/:id``).
    Postman path variables use ``:name`` syntax in the path array.
    """
    raw = url_obj.get("raw", "")
    if raw:
        raw = substitute_variables(raw, variables)
        # Try to extract path from raw
        try:
            parsed = urlparse(raw if "://" in raw else f"https://placeholder{raw}")
            path = parsed.path or "/"
            return path
        except Exception as exc:
            logger.debug("Ignoring Postman parse detail: %s", exc)

    # Build from path array
    path_parts = url_obj.get("path", [])
    if isinstance(path_parts, list):
        parts: list[str] = []
        for p in path_parts:
            segment = substitute_variables(str(p), variables) if isinstance(p, str) else str(p)
            # Postman path variables: ":name" → "{name}"
            segment = re.sub(r"^:(.+)$", r"{\1}", segment)
            parts.append(segment)
        return "/" + "/".join(parts)

    return "/"


def _extract_base_url(url_obj: dict[str, Any] | str, variables: dict[str, str]) -> str:
    """Extract the base URL (scheme+host) from a Postman URL."""
    if isinstance(url_obj, str):
        raw = substitute_variables(url_obj, variables)
        try:
            p = urlparse(raw if "://" in raw else f"https://placeholder{raw}")
            if p.scheme and p.netloc and p.netloc != "placeholder":
                return urlunparse((p.scheme, p.netloc, "", "", "", ""))
        except Exception as exc:
            logger.debug("Ignoring Postman parse detail: %s", exc)
        return ""

    raw = url_obj.get("raw", "")
    if raw:
        raw = substitute_variables(raw, variables)
        try:
            p = urlparse(raw if "://" in raw else f"https://placeholder{raw}")
            if p.scheme and p.netloc and p.netloc != "placeholder":
                return urlunparse((p.scheme, p.netloc, "", "", "", ""))
        except Exception as exc:
            logger.debug("Ignoring Postman parse detail: %s", exc)

    protocol_parts = url_obj.get("protocol", "")
    host_parts = url_obj.get("host", [])
    host = ".".join(
        substitute_variables(h, variables) if isinstance(h, str) else str(h)
        for h in (host_parts if isinstance(host_parts, list) else [str(host_parts)])
    )
    if host and not host.startswith("{{"):
        scheme = substitute_variables(str(protocol_parts), variables) if protocol_parts else "https"
        return f"{scheme}://{host}"
    return ""


# --------------------------------------------------------------------------- #
#  Name → operation_id conversion
# --------------------------------------------------------------------------- #


def _to_operation_id(name: str, folder_path: list[str]) -> str:
    """Build a valid operation_id from folder path + request name.

    Example: folders=["Users", "Profile"], name="Get User" → "users_profile_get_user"
    """
    parts = [*folder_path, name]
    # Join, lowercase, replace non-alphanum with underscores
    combined = "_".join(p.strip() for p in parts if p.strip())
    op_id = re.sub(r"[^a-zA-Z0-9]+", "_", combined).strip("_").lower()
    # Ensure doesn't start with a digit
    if op_id and op_id[0].isdigit():
        op_id = "op_" + op_id
    return op_id or "unnamed_operation"


# --------------------------------------------------------------------------- #
#  Body parsing
# --------------------------------------------------------------------------- #


def _parse_body(body: dict[str, Any], variables: dict[str, str]) -> RequestBody | None:
    """Convert a Postman request body to an IR RequestBody, or None."""
    if not body or not isinstance(body, dict):
        return None

    mode = body.get("mode", "")

    if mode == "raw":
        raw_content = body.get("raw", "")
        raw_content = substitute_variables(raw_content, variables)

        # Infer content type from options
        options = body.get("options", {})
        language = options.get("raw", {}).get("language", "json") if isinstance(options, dict) else "json"
        content_type = "application/json" if language == "json" else "text/plain"

        # Try to infer schema from raw JSON
        schema = SchemaRef(type="string")
        if language == "json" and raw_content.strip():
            try:
                parsed = json.loads(raw_content)
                schema = _value_to_schema(parsed)
            except (json.JSONDecodeError, ValueError):
                schema = SchemaRef(type="object")

        return RequestBody(
            content_type=content_type,
            schema=schema,
            required=True,
        )

    if mode == "formdata":
        fields = body.get("formdata", [])
        properties: dict[str, SchemaRef] = {}
        required_props: list[str] = []
        for field_item in (fields if isinstance(fields, list) else []):
            if not isinstance(field_item, dict) or field_item.get("disabled"):
                continue
            fname = str(field_item.get("key", ""))
            if not fname:
                continue
            ftype = "string"
            if field_item.get("type") == "file":
                ftype = "string"  # binary as string for schema
            properties[fname] = SchemaRef(
                type=ftype,
                description=str(field_item.get("description", "")),
            )
            if field_item.get("required"):
                required_props.append(fname)

        schema = SchemaRef(
            type="object",
            properties=properties,
            required=required_props,
        )
        return RequestBody(
            content_type="multipart/form-data",
            schema=schema,
            required=True,
        )

    if mode == "urlencoded":
        fields = body.get("urlencoded", [])
        properties = {}
        for field_item in (fields if isinstance(fields, list) else []):
            if not isinstance(field_item, dict) or field_item.get("disabled"):
                continue
            fname = str(field_item.get("key", ""))
            if not fname:
                continue
            properties[fname] = SchemaRef(
                type="string",
                description=str(field_item.get("description", "")),
            )
        schema = SchemaRef(type="object", properties=properties)
        return RequestBody(
            content_type="application/x-www-form-urlencoded",
            schema=schema,
            required=True,
        )

    if mode == "graphql":
        return RequestBody(
            content_type="application/json",
            schema=SchemaRef(
                type="object",
                properties={
                    "query": SchemaRef(type="string"),
                    "variables": SchemaRef(type="object"),
                },
            ),
            required=True,
        )

    return None


def _value_to_schema(value: Any) -> SchemaRef:
    """Infer a SchemaRef from a Python value (JSON-derived)."""
    if isinstance(value, bool):
        return SchemaRef(type="boolean")
    if isinstance(value, int):
        return SchemaRef(type="integer")
    if isinstance(value, float):
        return SchemaRef(type="number")
    if isinstance(value, str):
        return SchemaRef(type="string")
    if isinstance(value, list):
        item_schema = _value_to_schema(value[0]) if value else SchemaRef(type="string")
        return SchemaRef(type="array", items=item_schema)
    if isinstance(value, dict):
        properties = {k: _value_to_schema(v) for k, v in value.items()}
        return SchemaRef(type="object", properties=properties)
    return SchemaRef(type="string")


# --------------------------------------------------------------------------- #
#  Request → Endpoint mapping
# --------------------------------------------------------------------------- #


def _parse_request(
    item: dict[str, Any],
    folder_path: list[str],
    variables: dict[str, str],
    collection_auth: AuthScheme | None,
) -> Endpoint | None:
    """Convert a Postman request item to an IR Endpoint, or None on failure."""
    request = item.get("request")
    if not isinstance(request, dict):
        return None

    name = str(item.get("name", "unnamed"))
    operation_id = _to_operation_id(name, folder_path)

    # Method
    raw_method = str(request.get("method", "GET")).upper()
    if raw_method not in _HTTP_METHODS:
        raw_method = "GET"
    method = HttpMethod(raw_method)

    # URL
    url_value = request.get("url", "")
    if isinstance(url_value, str):
        url_str = substitute_variables(url_value, variables)
        try:
            parsed = urlparse(url_str if "://" in url_str else f"https://placeholder{url_str}")
            path = parsed.path or "/"
        except Exception:
            path = "/"
    elif isinstance(url_value, dict):
        path = _normalise_url_object(url_value, variables)
    else:
        path = "/"

    # Parameters — query
    parameters: list[Parameter] = []
    url_obj = url_value if isinstance(url_value, dict) else {}
    query_items = url_obj.get("query", [])
    for q in (query_items if isinstance(query_items, list) else []):
        if not isinstance(q, dict) or q.get("disabled"):
            continue
        q_name = str(q.get("key", ""))
        if not q_name:
            continue
        q_desc = substitute_variables(str(q.get("description", "")), variables)
        parameters.append(
            Parameter(
                name=q_name,
                location=ParameterLocation.QUERY,
                schema=SchemaRef(type="string", description=q_desc),
                required=False,
                description=q_desc,
            )
        )

    # Parameters — path variables from URL object
    path_vars = url_obj.get("variable", [])
    for pv in (path_vars if isinstance(path_vars, list) else []):
        if not isinstance(pv, dict):
            continue
        pv_name = str(pv.get("key") or pv.get("id") or "")
        if not pv_name:
            continue
        pv_desc = substitute_variables(str(pv.get("description", "")), variables)
        parameters.append(
            Parameter(
                name=pv_name,
                location=ParameterLocation.PATH,
                schema=SchemaRef(type="string", description=pv_desc),
                required=True,
                description=pv_desc,
            )
        )

    # Also detect {param} in path and add if not already present
    existing_path_params = {p.name for p in parameters if p.location == ParameterLocation.PATH}
    for match in re.finditer(r"\{([^}]+)\}", path):
        pname = match.group(1)
        if pname not in existing_path_params:
            parameters.append(
                Parameter(
                    name=pname,
                    location=ParameterLocation.PATH,
                    schema=SchemaRef(type="string"),
                    required=True,
                )
            )
            existing_path_params.add(pname)

    # Parameters — headers (informational; skip standard headers)
    _SKIP_HEADERS = frozenset({
        "content-type", "accept", "authorization", "user-agent",
        "content-length", "host", "connection",
    })
    header_items = request.get("header", [])
    for h in (header_items if isinstance(header_items, list) else []):
        if not isinstance(h, dict) or h.get("disabled"):
            continue
        h_name = str(h.get("key", ""))
        if not h_name or h_name.lower() in _SKIP_HEADERS:
            continue
        h_desc = substitute_variables(str(h.get("description", "")), variables)
        parameters.append(
            Parameter(
                name=h_name,
                location=ParameterLocation.HEADER,
                schema=SchemaRef(type="string", description=h_desc),
                required=False,
                description=h_desc,
            )
        )

    # Request body
    body_obj = request.get("body")
    request_body = _parse_body(body_obj, variables) if isinstance(body_obj, dict) else None

    # Response — Postman stores example responses
    responses: list[Response] = []
    response_items = item.get("response", [])
    for resp in (response_items if isinstance(response_items, list) else []):
        if not isinstance(resp, dict):
            continue
        status = str(resp.get("status", "")).strip()
        code = str(resp.get("code", "200"))
        responses.append(
            Response(
                status_code=code,
                description=status,
            )
        )
    if not responses:
        responses.append(Response(status_code="200", description="OK"))

    # Tags from folder path
    tags = [folder_path[0]] if folder_path else []

    # Description
    desc_raw = request.get("description", "")
    if isinstance(desc_raw, dict):
        description = str(desc_raw.get("content", ""))
    else:
        description = substitute_variables(str(desc_raw), variables)

    # Auth — request-level overrides collection-level
    req_auth = parse_auth(request.get("auth"))
    effective_auth = req_auth or collection_auth
    security: list[dict[str, list[str]]] = []
    if effective_auth:
        security = [{effective_auth.name: []}]

    return Endpoint(
        path=path,
        method=method,
        operation_id=operation_id,
        summary=name,
        description=description,
        parameters=parameters,
        request_body=request_body,
        responses=responses,
        tags=tags,
        security=security,
        metadata={"folder": "/".join(folder_path) if folder_path else ""},
    )


# --------------------------------------------------------------------------- #
#  Recursive item walker
# --------------------------------------------------------------------------- #


def _walk_items(
    items: list[dict[str, Any]],
    folder_path: list[str],
    variables: dict[str, str],
    collection_auth: AuthScheme | None,
    endpoints: list[Endpoint],
    base_urls: set[str],
) -> None:
    """Recursively walk Postman items, building endpoints list in place."""
    for item in items:
        if not isinstance(item, dict):
            continue

        # Folder: has a nested "item" array
        if "item" in item:
            folder_name = str(item.get("name", ""))
            # Folder-level auth overrides collection-level for its children
            folder_auth = parse_auth(item.get("auth")) or collection_auth
            # Merge folder variables
            folder_vars = dict(variables)
            folder_var_list = item.get("variable", [])
            if isinstance(folder_var_list, list):
                folder_vars.update(extract_variables(folder_var_list))
            _walk_items(
                item["item"],
                [*folder_path, folder_name],
                folder_vars,
                folder_auth,
                endpoints,
                base_urls,
            )
            continue

        # Request item
        if "request" in item:
            ep = _parse_request(item, folder_path, variables, collection_auth)
            if ep is not None:
                endpoints.append(ep)

                # Track base URL from request URL
                url_val = item["request"].get("url", "")
                base = _extract_base_url(url_val, variables)
                if base:
                    base_urls.add(base)


# --------------------------------------------------------------------------- #
#  PostmanParser — public interface
# --------------------------------------------------------------------------- #


class PostmanParser(BaseParser):
    """Parse Postman Collection v2.1 files into an :class:`APISpec`.

    Supports:
    - Collection v2.1 (and v2.0 with a best-effort mapping)
    - Variable substitution (``{{varName}}``)
    - Folder hierarchy → endpoint tags
    - Collection / folder / request-level auth
    """

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def detect(self, content: dict[str, Any]) -> bool:
        """Return True if *content* looks like a Postman Collection."""
        # Must have "info" with a schema URL and an "item" array
        info = content.get("info")
        if not isinstance(info, dict):
            return False
        schema_url = str(info.get("schema", ""))
        has_schema = "getpostman.com" in schema_url or _SCHEMA_V21 in schema_url or _SCHEMA_V20 in schema_url
        has_items = "item" in content
        return has_schema and has_items

    async def validate(self, source: str | Path, **_kwargs: Any) -> list[ParseError]:
        """Validate a Postman Collection document.

        Returns a list of :class:`ParseError`; empty means valid.
        """
        errors: list[ParseError] = []
        try:
            doc = await self._load_doc(source)
        except ParseException as exc:
            if exc.errors:
                return list(exc.errors)
            return [ParseError(str(exc))]

        if not self.detect(doc):
            errors.append(
                ParseError(
                    "Document does not appear to be a Postman Collection v2.x "
                    "(expected 'info.schema' containing getpostman.com and an 'item' array)"
                )
            )

        info = doc.get("info", {})
        if not isinstance(info, dict) or not info.get("name"):
            errors.append(ParseError("Missing or empty 'info.name' field", path="/info/name"))

        if "item" not in doc:
            errors.append(ParseError("Missing required 'item' array", path="/item"))

        return errors

    async def parse(
        self,
        source: str | Path,
        *,
        title: str | None = None,
        **_kwargs: Any,
    ) -> APISpec:
        """Parse a Postman Collection and return an :class:`APISpec`.

        Args:
            source: File path or raw JSON string.
            title:  Override the collection name as the API title.

        Returns:
            Parsed :class:`APISpec` with ``source_format = "postman"``.

        Raises:
            ParseException: If the document cannot be parsed or is not a
                Postman Collection.
        """
        doc = await self._load_doc(source)

        info = doc.get("info", {})
        schema_url = info.get("schema", "") if isinstance(info, dict) else ""
        # Detect v1 format (no info.schema, has top-level 'requests' key)
        if "requests" in doc and not schema_url:
            raise ParseException(
                "Unsupported Postman Collection version (v1 detected). "
                "Please export your collection as v2.1 format."
            )

        if not self.detect(doc):
            raise ParseException(
                "PostmanParser requires a Postman Collection v2.x document "
                "(expected 'info.schema' containing getpostman.com)"
            )

        # --- Collection metadata ---
        info = doc.get("info", {})
        collection_name = title or str(info.get("name", "Postman Collection"))
        collection_desc = str(info.get("description", ""))
        collection_version = str(info.get("version", "1.0.0"))

        # --- Variables ---
        variables = extract_variables(doc.get("variable", []))

        # --- Collection-level auth ---
        collection_auth = parse_auth(doc.get("auth"))

        # --- Walk all items ---
        endpoints: list[Endpoint] = []
        base_urls: set[str] = set()
        _walk_items(
            doc.get("item", []),
            [],
            variables,
            collection_auth,
            endpoints,
            base_urls,
        )

        # --- Auth schemes ---
        auth_schemes: list[AuthScheme] = []
        if collection_auth:
            auth_schemes.append(collection_auth)
        # Deduplicate auth schemes from endpoints
        seen_auth: set[str] = {a.name for a in auth_schemes}
        for ep in endpoints:
            for sec in ep.security:
                for auth_name in sec:
                    if auth_name not in seen_auth:
                        # We can't reconstruct the full scheme here; add a placeholder
                        seen_auth.add(auth_name)

        # --- Servers ---
        servers: list[ServerInfo] = []
        for url in sorted(base_urls):
            servers.append(ServerInfo(url=url))
        base_url = servers[0].url if servers else ""

        return APISpec(
            title=collection_name,
            version=collection_version,
            description=collection_desc,
            base_url=base_url,
            servers=servers,
            endpoints=endpoints,
            auth_schemes=auth_schemes,
            models={},  # Postman has no explicit schema definitions
            source_format="postman",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_doc(self, source: str | Path) -> dict[str, Any]:
        """Load and parse a Postman Collection from various source types."""
        if isinstance(source, Path):
            if not source.exists():
                raise ParseException(f"File not found: {source}")
            text = source.read_text(encoding="utf-8")
            return self._parse_json(text, str(source))

        text = str(source)

        # Raw JSON string
        stripped = text.lstrip()
        if stripped.startswith("{"):
            return self._parse_json(text, "<string>")

        # File path string
        path = Path(text)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            return self._parse_json(content, str(path))

        raise ParseException(f"Cannot resolve source: {text!r}")

    @staticmethod
    def _parse_json(text: str, source_name: str) -> dict[str, Any]:
        """Parse JSON text into a dict."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseException(
                f"Failed to parse {source_name}: {exc}",
                errors=[ParseError(str(exc), line=exc.lineno, column=exc.colno)],
            ) from exc

        if not isinstance(data, dict):
            raise ParseException(
                f"Expected JSON object at root of {source_name}, got {type(data).__name__}"
            )
        return data
