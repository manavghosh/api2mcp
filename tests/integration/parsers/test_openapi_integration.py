"""Integration tests for OpenAPI parser with real-world-style specs (TASK-010).

These tests exercise the full parsing pipeline including $ref resolution,
complex schemas, and edge cases found in real API specs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from api2mcp.parsers.openapi import OpenAPIParser

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"

pytestmark = pytest.mark.integration


class TestMultiFileRefResolution:
    """Test parsing specs that reference external files."""

    @pytest.mark.asyncio
    async def test_external_file_ref(self, tmp_path: Path) -> None:
        # Create a shared schema file
        models_file = tmp_path / "models.yaml"
        models_file.write_text(
            """
User:
  type: object
  required:
    - id
    - email
  properties:
    id:
      type: integer
    email:
      type: string
      format: email
    name:
      type: string
""",
            encoding="utf-8",
        )

        # Create main spec referencing the external file
        spec_file = tmp_path / "api.yaml"
        spec_file.write_text(
            """
openapi: "3.0.3"
info:
  title: External Ref Test
  version: "1.0.0"
paths:
  /users:
    get:
      operationId: listUsers
      responses:
        "200":
          description: User list
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: "models.yaml#/User"
""",
            encoding="utf-8",
        )

        parser = OpenAPIParser()
        spec = await parser.parse(spec_file)

        assert len(spec.endpoints) == 1
        ep = spec.endpoints[0]
        resp = next(r for r in ep.responses if r.status_code == "200")
        assert resp.schema is not None
        assert resp.schema.items is not None
        assert resp.schema.items.type == "object"
        assert "email" in resp.schema.items.properties


class TestComplexSchemas:
    """Test parsing of complex schema patterns."""

    @pytest.mark.asyncio
    async def test_deeply_nested_objects(self) -> None:
        spec_yaml = """
openapi: "3.0.3"
info:
  title: Nested Test
  version: "1.0"
paths:
  /reports:
    get:
      operationId: getReport
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Report"
components:
  schemas:
    Report:
      type: object
      properties:
        metadata:
          type: object
          properties:
            author:
              $ref: "#/components/schemas/Author"
            tags:
              type: array
              items:
                type: string
    Author:
      type: object
      properties:
        name:
          type: string
        address:
          type: object
          properties:
            city:
              type: string
            country:
              type: string
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        report = spec.models["Report"]
        metadata = report.schema.properties["metadata"]
        author = metadata.properties["author"]
        assert author.type == "object"
        assert "name" in author.properties
        assert "address" in author.properties
        city = author.properties["address"].properties["city"]
        assert city.type == "string"

    @pytest.mark.asyncio
    async def test_all_of_composition(self) -> None:
        spec_yaml = """
openapi: "3.0.3"
info:
  title: Composition Test
  version: "1.0"
paths:
  /items:
    get:
      operationId: getItem
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ExtendedItem"
components:
  schemas:
    BaseItem:
      type: object
      properties:
        id:
          type: integer
    ExtendedItem:
      allOf:
        - $ref: "#/components/schemas/BaseItem"
        - type: object
          properties:
            name:
              type: string
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        extended = spec.models["ExtendedItem"]
        assert len(extended.schema.all_of) == 2


class TestEdgeCases:
    """Edge cases encountered in real-world specs."""

    @pytest.mark.asyncio
    async def test_no_servers(self) -> None:
        spec_yaml = """
openapi: "3.0.3"
info:
  title: No Servers
  version: "1.0"
paths:
  /test:
    get:
      operationId: test
      responses:
        "200":
          description: OK
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        assert spec.base_url == ""
        assert spec.servers == []

    @pytest.mark.asyncio
    async def test_empty_responses(self) -> None:
        spec_yaml = """
openapi: "3.0.3"
info:
  title: Empty Response
  version: "1.0"
paths:
  /ping:
    get:
      operationId: ping
      responses:
        "204":
          description: No content
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        ep = spec.endpoints[0]
        resp = ep.responses[0]
        assert resp.status_code == "204"
        assert resp.schema is None

    @pytest.mark.asyncio
    async def test_multiple_content_types(self) -> None:
        spec_yaml = """
openapi: "3.0.3"
info:
  title: Multi Content
  version: "1.0"
paths:
  /upload:
    post:
      operationId: upload
      requestBody:
        content:
          multipart/form-data:
            schema:
              type: object
              properties:
                file:
                  type: string
                  format: binary
      responses:
        "200":
          description: OK
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        ep = spec.endpoints[0]
        assert ep.request_body is not None
        assert ep.request_body.content_type == "multipart/form-data"

    @pytest.mark.asyncio
    async def test_path_level_parameters(self) -> None:
        """Parameters defined at path level apply to all operations."""
        spec_yaml = """
openapi: "3.0.3"
info:
  title: Path Params
  version: "1.0"
paths:
  /orgs/{orgId}/members:
    parameters:
      - name: orgId
        in: path
        required: true
        schema:
          type: string
    get:
      operationId: listMembers
      parameters:
        - name: limit
          in: query
          schema:
            type: integer
      responses:
        "200":
          description: OK
    post:
      operationId: addMember
      requestBody:
        content:
          application/json:
            schema:
              type: object
      responses:
        "201":
          description: Created
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        get_ep = next(e for e in spec.endpoints if e.operation_id == "listMembers")
        # Should have both path-level orgId and operation-level limit
        param_names = {p.name for p in get_ep.parameters}
        assert "orgId" in param_names
        assert "limit" in param_names

        post_ep = next(e for e in spec.endpoints if e.operation_id == "addMember")
        # Should inherit path-level orgId
        param_names = {p.name for p in post_ep.parameters}
        assert "orgId" in param_names

    @pytest.mark.asyncio
    async def test_oauth2_auth_scheme(self) -> None:
        spec_yaml = """
openapi: "3.0.3"
info:
  title: OAuth Test
  version: "1.0"
paths:
  /test:
    get:
      operationId: test
      responses:
        "200":
          description: OK
components:
  securitySchemes:
    oauth:
      type: oauth2
      flows:
        authorizationCode:
          authorizationUrl: https://example.com/auth
          tokenUrl: https://example.com/token
          scopes:
            read: Read access
            write: Write access
    openid:
      type: openIdConnect
      openIdConnectUrl: https://example.com/.well-known/openid-configuration
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(spec_yaml)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        assert len(spec.auth_schemes) == 2
        oauth = next(a for a in spec.auth_schemes if a.name == "oauth")
        assert oauth.type.value == "oauth2"
        assert "authorizationCode" in oauth.flows

        openid = next(a for a in spec.auth_schemes if a.name == "openid")
        assert openid.type.value == "openIdConnect"
        assert "well-known" in openid.openid_connect_url

    @pytest.mark.asyncio
    async def test_json_format_spec(self) -> None:
        """Parse a spec in JSON format."""
        import json

        spec_dict = {
            "openapi": "3.0.3",
            "info": {"title": "JSON Spec", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(spec_dict, f)
            f.flush()
            parser = OpenAPIParser()
            spec = await parser.parse(Path(f.name))

        assert spec.title == "JSON Spec"
        assert len(spec.endpoints) == 1
