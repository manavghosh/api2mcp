# SPDX-License-Identifier: MIT
"""Swagger 2.0 parser implementation (F3.2).

Detects Swagger 2.0 documents, converts them to OpenAPI 3.0 in-memory,
then delegates to the existing OpenAPIParser for IR generation.

Migration suggestions are surfaced via MigrationSuggestion objects that
callers can inspect after parsing.
"""

from __future__ import annotations

import copy
import json
import logging
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from api2mcp.core.exceptions import ParseError, ParseException
from api2mcp.core.ir_schema import APISpec
from api2mcp.core.parser import BaseParser

from .openapi import OpenAPIParser

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Migration suggestion model
# --------------------------------------------------------------------------- #


class MigrationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class MigrationSuggestion:
    """A single migration note produced during Swagger → OpenAPI 3.0 conversion."""

    category: str
    """Short category label, e.g. 'security', 'body-param', 'consumes'."""

    message: str
    """Human-readable description of the conversion performed or issue found."""

    path: str = ""
    """JSON-pointer-style location in the *original* Swagger doc, e.g. '/paths/~1users/post'."""

    severity: MigrationSeverity = MigrationSeverity.INFO


# --------------------------------------------------------------------------- #
#  Swagger 2.0 → OpenAPI 3.0 converter
# --------------------------------------------------------------------------- #


class SwaggerConverter:
    """Convert a Swagger 2.0 document dict to an OpenAPI 3.0 document dict.

    Usage::

        converter = SwaggerConverter()
        oas3_doc, suggestions = converter.convert(swagger_doc)
    """

    def __init__(self) -> None:
        self._suggestions: list[MigrationSuggestion] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def convert(
        self, swagger: dict[str, Any]
    ) -> tuple[dict[str, Any], list[MigrationSuggestion]]:
        """Convert *swagger* (Swagger 2.0 dict) to an OpenAPI 3.0.3 dict.

        Returns ``(oas3_doc, suggestions)``.
        """
        self._suggestions = []
        doc: dict[str, Any] = {}

        doc["openapi"] = "3.0.3"
        doc["info"] = copy.deepcopy(swagger.get("info", {"title": "API", "version": "1.0.0"}))

        # servers block
        doc["servers"] = self._build_servers(swagger)

        # components (definitions + securityDefinitions)
        components: dict[str, Any] = {}
        if "definitions" in swagger:
            components["schemas"] = self._rewrite_refs(
                copy.deepcopy(swagger["definitions"])
            )
        if "securityDefinitions" in swagger:
            components["securitySchemes"] = self._convert_security_definitions(
                swagger["securityDefinitions"]
            )
        if components:
            doc["components"] = components

        # paths
        global_consumes: list[str] = swagger.get("consumes", ["application/json"])
        global_produces: list[str] = swagger.get("produces", ["application/json"])
        if "paths" in swagger:
            doc["paths"] = self._convert_paths(
                swagger["paths"], global_consumes, global_produces
            )

        # top-level security
        if "security" in swagger:
            doc["security"] = copy.deepcopy(swagger["security"])

        # tags
        if "tags" in swagger:
            doc["tags"] = copy.deepcopy(swagger["tags"])

        # externalDocs
        if "externalDocs" in swagger:
            doc["externalDocs"] = copy.deepcopy(swagger["externalDocs"])

        return doc, list(self._suggestions)

    # ------------------------------------------------------------------
    # servers
    # ------------------------------------------------------------------

    def _build_servers(self, swagger: dict[str, Any]) -> list[dict[str, Any]]:
        """Build OAS3 servers array from host/basePath/schemes."""
        host: str = swagger.get("host", "localhost")
        base_path: str = swagger.get("basePath", "/")
        schemes: list[str] = swagger.get("schemes", ["https"])

        servers = []
        for scheme in schemes:
            url = f"{scheme}://{host}{base_path}"
            servers.append({"url": url})

        if not servers:
            servers = [{"url": "/"}]

        if "host" in swagger or "basePath" in swagger or "schemes" in swagger:
            self._suggestions.append(
                MigrationSuggestion(
                    category="servers",
                    message=(
                        f"Swagger 'host', 'basePath', and 'schemes' converted to "
                        f"OAS3 servers: {[s['url'] for s in servers]}"
                    ),
                    severity=MigrationSeverity.INFO,
                )
            )
        return servers

    # ------------------------------------------------------------------
    # $ref rewriting
    # ------------------------------------------------------------------

    def _rewrite_refs(self, obj: Any) -> Any:
        """Recursively rewrite '#/definitions/X' refs to '#/components/schemas/X'."""
        if isinstance(obj, dict):
            result: dict[str, Any] = {}
            for k, v in obj.items():
                if k == "$ref" and isinstance(v, str):
                    result[k] = v.replace("#/definitions/", "#/components/schemas/")
                else:
                    result[k] = self._rewrite_refs(v)
            return result
        if isinstance(obj, list):
            return [self._rewrite_refs(item) for item in obj]
        return obj

    # ------------------------------------------------------------------
    # paths
    # ------------------------------------------------------------------

    def _convert_paths(
        self,
        paths: dict[str, Any],
        global_consumes: list[str],
        global_produces: list[str],
    ) -> dict[str, Any]:
        """Convert each path item and its operations."""
        oas3_paths: dict[str, Any] = {}
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                oas3_paths[path] = path_item
                continue
            oas3_path_item: dict[str, Any] = {}
            # path-level params (not body)
            if "parameters" in path_item:
                converted, _ = self._split_parameters(path_item["parameters"])
                if converted:
                    oas3_path_item["parameters"] = self._rewrite_refs(converted)

            for method in (
                "get", "post", "put", "patch", "delete", "head", "options", "trace"
            ):
                if method not in path_item:
                    continue
                op = path_item[method]
                if not isinstance(op, dict):
                    oas3_path_item[method] = op
                    continue
                op_consumes = op.get("consumes", global_consumes)
                op_produces = op.get("produces", global_produces)
                oas3_op = self._convert_operation(
                    op,
                    op_consumes,
                    op_produces,
                    swagger_path=f"/paths/{path.replace('/', '~1')}/{method}",
                )
                oas3_path_item[method] = oas3_op

            oas3_paths[path] = oas3_path_item
        return oas3_paths

    def _convert_operation(
        self,
        op: dict[str, Any],
        consumes: list[str],
        produces: list[str],
        swagger_path: str,
    ) -> dict[str, Any]:
        """Convert a single Swagger operation to OAS3."""
        oas3_op: dict[str, Any] = {}
        # scalar fields
        for key in ("summary", "description", "operationId", "deprecated", "tags", "security", "externalDocs"):
            if key in op:
                oas3_op[key] = copy.deepcopy(op[key])

        # parameters (non-body)
        raw_params: list[dict[str, Any]] = op.get("parameters", [])
        non_body_params, body_params = self._split_parameters(raw_params)
        if non_body_params:
            oas3_op["parameters"] = self._rewrite_refs(non_body_params)

        # requestBody from body parameter
        if body_params:
            oas3_op["requestBody"] = self._body_params_to_request_body(
                body_params, consumes, swagger_path
            )

        # responses
        if "responses" in op:
            oas3_op["responses"] = self._convert_responses(
                op["responses"], produces, swagger_path
            )

        return oas3_op

    # ------------------------------------------------------------------
    # parameters
    # ------------------------------------------------------------------

    def _split_parameters(
        self, params: list[Any]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split parameters into non-body and body lists."""
        non_body: list[dict[str, Any]] = []
        body: list[dict[str, Any]] = []
        for p in params:
            if not isinstance(p, dict):
                non_body.append(p)
                continue
            loc = p.get("in", "")
            if loc == "body":
                body.append(p)
            elif loc == "formData":
                # treat formData as body for OAS3
                body.append(p)
            else:
                converted = self._convert_parameter(p)
                non_body.append(converted)
        return non_body, body

    def _convert_parameter(self, param: dict[str, Any]) -> dict[str, Any]:
        """Convert a non-body Swagger parameter to OAS3 format."""
        result: dict[str, Any] = {}
        for key in ("name", "in", "description", "required", "allowEmptyValue"):
            if key in param:
                result[key] = param[key]

        # In Swagger 2.0, schema-like fields (type, format, enum, items, …)
        # live directly on the parameter; in OAS3 they belong inside "schema".
        schema_keys = {"type", "format", "enum", "items", "default", "minimum",
                       "maximum", "minLength", "maxLength", "pattern",
                       "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                       "minItems", "maxItems", "uniqueItems"}
        schema: dict[str, Any] = {}
        for key in schema_keys:
            if key in param:
                schema[key] = param[key]
        if schema:
            result["schema"] = self._rewrite_refs(schema)
        elif "schema" in param:
            result["schema"] = self._rewrite_refs(copy.deepcopy(param["schema"]))

        return result

    # ------------------------------------------------------------------
    # body params → requestBody
    # ------------------------------------------------------------------

    def _body_params_to_request_body(
        self,
        body_params: list[dict[str, Any]],
        consumes: list[str],
        swagger_path: str,
    ) -> dict[str, Any]:
        """Convert Swagger body / formData parameters to OAS3 requestBody."""
        # Swagger allows at most one body parameter; formData params are merged.
        form_data_params = [p for p in body_params if p.get("in") == "formData"]
        body_param = next((p for p in body_params if p.get("in") == "body"), None)

        request_body: dict[str, Any] = {"content": {}}

        if body_param:
            schema = self._rewrite_refs(
                copy.deepcopy(body_param.get("schema", {"type": "object"}))
            )
            required = body_param.get("required", False)
            if required:
                request_body["required"] = True
            description = body_param.get("description")
            if description:
                request_body["description"] = description

            media_types = consumes if consumes else ["application/json"]
            for mt in media_types:
                request_body["content"][mt] = {"schema": schema}

            self._suggestions.append(
                MigrationSuggestion(
                    category="body-param",
                    message=(
                        f"Body parameter '{body_param.get('name', 'body')}' converted "
                        f"to requestBody with content-types: {media_types}"
                    ),
                    path=swagger_path,
                    severity=MigrationSeverity.INFO,
                )
            )

        elif form_data_params:
            # merge all formData into a single object schema
            properties: dict[str, Any] = {}
            required_props: list[str] = []
            for p in form_data_params:
                prop_schema: dict[str, Any] = {}
                for key in ("type", "format", "description", "enum", "default"):
                    if key in p:
                        prop_schema[key] = p[key]
                if not prop_schema:
                    prop_schema = {"type": "string"}
                properties[p["name"]] = prop_schema
                if p.get("required"):
                    required_props.append(p["name"])

            schema = {"type": "object", "properties": properties}
            if required_props:
                schema["required"] = required_props  # type: ignore[assignment]

            # choose content-type: if consumes contains multipart/form-data use that
            is_multipart = any("multipart" in mt for mt in consumes)
            media_type = "multipart/form-data" if is_multipart else "application/x-www-form-urlencoded"
            request_body["content"][media_type] = {"schema": schema}

            self._suggestions.append(
                MigrationSuggestion(
                    category="form-data",
                    message=(
                        f"{len(form_data_params)} formData parameter(s) merged into "
                        f"requestBody with content-type '{media_type}'"
                    ),
                    path=swagger_path,
                    severity=MigrationSeverity.INFO,
                )
            )

        return request_body

    # ------------------------------------------------------------------
    # responses
    # ------------------------------------------------------------------

    def _convert_responses(
        self,
        responses: dict[str, Any],
        produces: list[str],
        swagger_path: str,  # noqa: ARG002  (reserved for future suggestion context)
    ) -> dict[str, Any]:
        """Convert Swagger response objects to OAS3 format."""
        oas3_responses: dict[str, Any] = {}
        for status_code, resp in responses.items():
            if not isinstance(resp, dict):
                oas3_responses[status_code] = resp
                continue
            oas3_resp: dict[str, Any] = {}
            if "description" in resp:
                oas3_resp["description"] = resp["description"]
            else:
                oas3_resp["description"] = ""

            if "schema" in resp:
                schema = self._rewrite_refs(copy.deepcopy(resp["schema"]))
                media_types = produces if produces else ["application/json"]
                oas3_resp["content"] = {mt: {"schema": schema} for mt in media_types}

            if "headers" in resp:
                oas3_resp["headers"] = self._convert_response_headers(resp["headers"])

            oas3_responses[status_code] = oas3_resp

        return oas3_responses

    def _convert_response_headers(
        self, headers: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert Swagger response header objects to OAS3 format."""
        result: dict[str, Any] = {}
        for name, hdr in headers.items():
            if not isinstance(hdr, dict):
                result[name] = hdr
                continue
            oas3_hdr: dict[str, Any] = {}
            if "description" in hdr:
                oas3_hdr["description"] = hdr["description"]
            schema: dict[str, Any] = {}
            for key in ("type", "format", "enum", "default"):
                if key in hdr:
                    schema[key] = hdr[key]
            if schema:
                oas3_hdr["schema"] = schema
            result[name] = oas3_hdr
        return result

    # ------------------------------------------------------------------
    # securityDefinitions
    # ------------------------------------------------------------------

    def _convert_security_definitions(
        self, sec_defs: dict[str, Any]
    ) -> dict[str, Any]:
        """Convert Swagger securityDefinitions to OAS3 securitySchemes."""
        schemes: dict[str, Any] = {}
        for name, defn in sec_defs.items():
            if not isinstance(defn, dict):
                schemes[name] = defn
                continue
            oas3_scheme: dict[str, Any] = {}
            sw_type: str = defn.get("type", "")

            if sw_type == "apiKey":
                oas3_scheme["type"] = "apiKey"
                oas3_scheme["in"] = defn.get("in", "header")
                oas3_scheme["name"] = defn.get("name", name)

            elif sw_type == "basic":
                oas3_scheme["type"] = "http"
                oas3_scheme["scheme"] = "basic"
                self._suggestions.append(
                    MigrationSuggestion(
                        category="security",
                        message=(
                            f"Security definition '{name}' converted from Swagger "
                            f"'basic' to OAS3 'http' with scheme 'basic'"
                        ),
                        severity=MigrationSeverity.INFO,
                    )
                )

            elif sw_type == "oauth2":
                oas3_scheme["type"] = "oauth2"
                oas3_scheme["flows"] = self._convert_oauth2_flows(defn)
                self._suggestions.append(
                    MigrationSuggestion(
                        category="security",
                        message=(
                            f"OAuth2 security definition '{name}' converted to OAS3 flows. "
                            f"Verify scope descriptions manually."
                        ),
                        severity=MigrationSeverity.WARNING,
                    )
                )

            else:
                # Unknown type — pass through with a warning
                oas3_scheme = copy.deepcopy(defn)
                self._suggestions.append(
                    MigrationSuggestion(
                        category="security",
                        message=f"Unknown security type '{sw_type}' for '{name}' — passed through unchanged.",
                        severity=MigrationSeverity.WARNING,
                    )
                )

            if "description" in defn:
                oas3_scheme["description"] = defn["description"]

            schemes[name] = oas3_scheme
        return schemes

    def _convert_oauth2_flows(self, defn: dict[str, Any]) -> dict[str, Any]:
        """Map Swagger oauth2 flow to OAS3 flows object."""
        flows: dict[str, Any] = {}
        flow_name: str = defn.get("flow", "")
        scopes: dict[str, str] = defn.get("scopes", {})
        auth_url: str = defn.get("authorizationUrl", "")
        token_url: str = defn.get("tokenUrl", "")

        # Swagger flow names → OAS3 flow keys
        flow_map = {
            "implicit": "implicit",
            "password": "password",
            "application": "clientCredentials",
            "accessCode": "authorizationCode",
        }
        oas3_flow_key = flow_map.get(flow_name, flow_name)
        oas3_flow: dict[str, Any] = {"scopes": scopes}
        if auth_url:
            oas3_flow["authorizationUrl"] = auth_url
        if token_url:
            oas3_flow["tokenUrl"] = token_url
        flows[oas3_flow_key] = oas3_flow
        return flows


# --------------------------------------------------------------------------- #
#  SwaggerParser — public interface
# --------------------------------------------------------------------------- #


class SwaggerParser(BaseParser):
    """Parse Swagger 2.0 specifications by converting to OAS3 and delegating.

    After calling :meth:`parse`, the migration suggestions from the last
    conversion are available via :attr:`last_suggestions`.
    """

    def __init__(self) -> None:
        self._openapi_parser = OpenAPIParser()
        self.last_suggestions: list[MigrationSuggestion] = []

    # ------------------------------------------------------------------
    # BaseParser interface
    # ------------------------------------------------------------------

    def detect(self, content: dict[str, Any]) -> bool:
        """Return True if *content* looks like a Swagger 2.0 document."""
        return content.get("swagger") == "2.0"

    async def validate(self, source: str | Path, **_kwargs: Any) -> list[ParseError]:
        """Validate a Swagger 2.0 document.

        Checks that the document is parseable and contains ``swagger: "2.0"``.
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
                    "Document does not contain 'swagger: \"2.0\"'. "
                    "Use OpenAPIParser for OpenAPI 3.x documents."
                )
            )

        if "info" not in doc:
            errors.append(ParseError("Missing required 'info' field"))

        if "paths" not in doc:
            errors.append(ParseError("Missing required 'paths' field", path="/paths"))

        return errors

    async def parse(
        self,
        source: str | Path,
        *,
        title: str | None = None,
        **kwargs: Any,
    ) -> APISpec:
        """Parse a Swagger 2.0 document and return an :class:`APISpec`.

        The document is converted in-memory to OAS3 then processed by
        :class:`OpenAPIParser`.  Migration suggestions are stored in
        :attr:`last_suggestions`.

        Args:
            source: File path, raw YAML/JSON string, or URL string.
            title:  Override the API title.
            **kwargs: Forwarded to the underlying :class:`OpenAPIParser`.

        Returns:
            Parsed :class:`APISpec`.

        Raises:
            ParseException: If the document cannot be parsed.
        """
        swagger_doc = await self._load_doc(source)

        if not self.detect(swagger_doc):
            raise ParseException(
                "SwaggerParser requires a Swagger 2.0 document "
                "(expected 'swagger: \"2.0\"' at the root)"
            )

        converter = SwaggerConverter()
        oas3_doc, suggestions = converter.convert(swagger_doc)
        self.last_suggestions = suggestions

        if title is not None:
            oas3_doc.setdefault("info", {})["title"] = title

        # Write the converted doc to a temp file so OpenAPIParser can load it.
        # (OpenAPIParser._load_source only accepts file paths or HTTP URLs, not raw strings.)
        oas3_yaml = yaml.dump(oas3_doc, allow_unicode=True, sort_keys=False)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(oas3_yaml)
            tmp_path = Path(tmp.name)
        try:
            spec = await self._openapi_parser.parse(tmp_path, **kwargs)
        finally:
            tmp_path.unlink(missing_ok=True)

        # Annotate so callers know where this came from
        spec.source_format = "swagger"
        return spec

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_doc(self, source: str | Path) -> dict[str, Any]:
        """Load and parse a Swagger 2.0 document from various source types."""
        if isinstance(source, Path):
            if not source.exists():
                raise ParseException(f"File not found: {source}")
            text = source.read_text(encoding="utf-8")
            return self._parse_text(text, str(source))

        text = str(source)

        # JSON string
        if text.lstrip().startswith("{"):
            try:
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ParseException("Expected JSON object at root")
                return data
            except json.JSONDecodeError as exc:
                raise ParseException(f"Invalid JSON: {exc}") from exc

        # YAML/JSON string (may start with "swagger:")
        if "\n" in text or text.strip().startswith("swagger"):
            return self._parse_text(text, "<string>")

        # Otherwise treat as a file path
        path = Path(text)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            return self._parse_text(content, str(path))

        raise ParseException(f"Cannot resolve source: {text!r}")

    @staticmethod
    def _parse_text(text: str, source_name: str) -> dict[str, Any]:
        """Parse YAML or JSON text into a dict."""
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
