# IR Schema Reference

The Intermediate Representation (IR) is the central data structure in API2MCP. Every parser outputs an `APISpec` IR, and every generator consumes it. This decoupling means adding a new parser or generator requires zero changes to the other side.

```
OpenAPI Spec ─┐                              ┌─> MCP Server code
GraphQL Spec ─┼─> Parser ─> APISpec (IR) ─> Generator ─┤
Postman Spec ─┘                              └─> LangGraph tools
```

**Source:** `src/api2mcp/core/ir_schema.py`

## Design Decisions

- GraphQL queries/mutations map to `Endpoint` with `method=QUERY`/`MUTATION`
- GraphQL fragments are resolved during parsing, not stored in the IR
- Postman variables are substituted during parsing, not stored in the IR
- Pagination patterns are auto-detected and stored for smart tool generation
- All `$ref` pointers are resolved inline; the original ref name is preserved in `ref_name`

---

## Type Hierarchy

```
APISpec                           # Top-level container
├── title: str
├── version: str
├── description: str
├── base_url: str                 # Primary server URL
├── source_format: str            # "openapi3.0", "openapi3.1", "graphql"
│
├── servers: list[ServerInfo]
│   ├── url: str
│   ├── description: str
│   └── variables: dict
│
├── endpoints: list[Endpoint]
│   ├── path: str                 # "/pets/{petId}"
│   ├── method: HttpMethod        # GET, POST, QUERY, MUTATION, etc.
│   ├── operation_id: str         # "listPets"
│   ├── summary: str
│   ├── description: str
│   ├── tags: list[str]
│   ├── security: list[dict]
│   ├── deprecated: bool
│   ├── metadata: dict
│   │
│   ├── parameters: list[Parameter]
│   │   ├── name: str
│   │   ├── location: ParameterLocation   # path, query, header, cookie, body
│   │   ├── schema: SchemaRef
│   │   ├── required: bool
│   │   ├── description: str
│   │   ├── deprecated: bool
│   │   └── example: Any
│   │
│   ├── request_body: RequestBody | None
│   │   ├── content_type: str     # "application/json", "multipart/form-data"
│   │   ├── schema: SchemaRef
│   │   ├── required: bool
│   │   └── description: str
│   │
│   ├── responses: list[Response]
│   │   ├── status_code: str      # "200", "default"
│   │   ├── description: str
│   │   ├── content_type: str
│   │   └── schema: SchemaRef | None
│   │
│   └── pagination: PaginationConfig | None
│       ├── style: str            # "offset", "cursor", "page"
│       ├── page_param: str
│       ├── limit_param: str
│       ├── cursor_param: str
│       └── next_field: str
│
├── auth_schemes: list[AuthScheme]
│   ├── name: str                 # "bearerAuth", "apiKeyAuth"
│   ├── type: AuthType            # apiKey, http_basic, http_bearer, oauth2, openIdConnect
│   ├── description: str
│   ├── api_key_name: str         # For apiKey: "X-API-Key"
│   ├── api_key_location: str     # For apiKey: "header", "query", "cookie"
│   ├── scheme: str               # For http: "basic", "bearer"
│   ├── bearer_format: str        # For http bearer: "JWT"
│   ├── flows: dict               # For oauth2: flow configurations
│   └── openid_connect_url: str   # For openIdConnect
│
├── models: dict[str, ModelDef]
│   ├── name: str                 # "Pet", "Error"
│   ├── schema: SchemaRef
│   └── description: str
│
└── metadata: dict                # openapi_version, tags, external_docs
```

---

## Enums

### HttpMethod

Standard HTTP methods plus GraphQL virtual methods.

| Value | Usage |
|-------|-------|
| `GET`, `POST`, `PUT`, `PATCH`, `DELETE` | REST operations |
| `HEAD`, `OPTIONS`, `TRACE` | REST utility methods |
| `QUERY`, `MUTATION` | GraphQL virtual methods |

### ParameterLocation

Where in the HTTP request a parameter is sent.

| Value | Description |
|-------|-------------|
| `path` | URL path segment (`/pets/{petId}`) |
| `query` | Query string (`?limit=10`) |
| `header` | HTTP header (`X-API-Key: ...`) |
| `cookie` | Cookie (`session=abc`) |
| `body` | GraphQL variables |

### AuthType

| Value | Description |
|-------|-------------|
| `apiKey` | API key in header, query, or cookie |
| `http_basic` | HTTP Basic authentication |
| `http_bearer` | HTTP Bearer token (e.g., JWT) |
| `oauth2` | OAuth 2.0 with flows |
| `openIdConnect` | OpenID Connect discovery |

### SchemaType

Standard JSON Schema types.

| Value |
|-------|
| `string`, `integer`, `number`, `boolean`, `array`, `object`, `null` |

---

## SchemaRef (Recursive Schema Type)

`SchemaRef` is the most important type in the IR. It appears everywhere schemas are used: parameters, request bodies, responses, and model definitions. It maps directly to JSON Schema.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | JSON Schema type (`"string"`, `"object"`, etc.) |
| `description` | `str` | Human-readable description |
| `properties` | `dict[str, SchemaRef]` | Object properties (recursive) |
| `items` | `SchemaRef \| None` | Array item schema |
| `required` | `list[str]` | Required property names |
| `enum` | `list[Any]` | Allowed values |
| `format` | `str` | Format hint: `date-time`, `email`, `uri`, `int32`, `int64`, `binary` |
| `default` | `Any` | Default value |
| `nullable` | `bool` | Whether the field can be null |
| `additional_properties` | `SchemaRef \| bool \| None` | For map/dictionary types |
| `one_of` | `list[SchemaRef]` | Union: exactly one must match |
| `any_of` | `list[SchemaRef]` | Union: one or more must match |
| `all_of` | `list[SchemaRef]` | Intersection: all must match (inheritance) |
| `ref_name` | `str` | Original `$ref` name for traceability (e.g., `"Pet"`) |
| `pattern` | `str` | Regex pattern constraint |
| `min_length` | `int \| None` | Minimum string length |
| `max_length` | `int \| None` | Maximum string length |
| `minimum` | `float \| None` | Minimum numeric value |
| `maximum` | `float \| None` | Maximum numeric value |
| `example` | `Any` | Example value |

### to_json_schema()

Converts the `SchemaRef` back to a standard JSON Schema dict. Used by the MCP Tool Generator to produce `input_schema` for MCP tool definitions.

```python
schema_ref = SchemaRef(
    type="object",
    properties={
        "name": SchemaRef(type="string"),
        "age": SchemaRef(type="integer", minimum=0),
    },
    required=["name"],
)

json_schema = schema_ref.to_json_schema()
# {
#     "type": "object",
#     "properties": {
#         "name": {"type": "string"},
#         "age": {"type": "integer", "minimum": 0}
#     },
#     "required": ["name"]
# }
```

---

## Parser Interface

All parsers implement `BaseParser` (defined in `src/api2mcp/core/parser.py`):

```python
class BaseParser(ABC):

    @abstractmethod
    async def parse(self, source: str | Path, **kwargs) -> APISpec:
        """Parse a spec file/URL and return the IR."""
        ...

    @abstractmethod
    async def validate(self, source: str | Path, **kwargs) -> list[ParseError]:
        """Validate a spec without producing full IR. Returns errors (empty = valid)."""
        ...

    @abstractmethod
    def detect(self, content: dict[str, Any]) -> bool:
        """Check if this parser handles the given content."""
        ...
```

### Current Parsers

| Parser | Source Format | `source_format` value |
|--------|-------------|----------------------|
| `OpenAPIParser` | OpenAPI 3.0.x | `"openapi3.0"` |
| `OpenAPIParser` | OpenAPI 3.1.x | `"openapi3.1"` |
| (planned) `GraphQLParser` | GraphQL SDL | `"graphql"` |
| (planned) `PostmanParser` | Postman Collection | `"postman"` |
| (planned) `SwaggerParser` | Swagger 2.0 | `"swagger2.0"` |

---

## Usage Examples

### Parse an OpenAPI spec

```python
import asyncio
from pathlib import Path
from api2mcp.parsers.openapi import OpenAPIParser

async def main():
    parser = OpenAPIParser()
    spec = await parser.parse(Path("petstore.yaml"))

    print(spec.title)           # "Petstore"
    print(spec.version)         # "1.0.0"
    print(spec.source_format)   # "openapi3.0"
    print(len(spec.endpoints))  # 4

asyncio.run(main())
```

### Access endpoints and parameters

```python
for ep in spec.endpoints:
    print(f"{ep.method.value} {ep.path} ({ep.operation_id})")
    for param in ep.parameters:
        print(f"  {param.name} [{param.location.value}] required={param.required}")
    if ep.pagination:
        print(f"  pagination: {ep.pagination.style}")
```

### Access auth schemes

```python
for auth in spec.auth_schemes:
    print(f"{auth.name}: {auth.type.value}")
    if auth.type == AuthType.API_KEY:
        print(f"  key={auth.api_key_name} in={auth.api_key_location}")
    elif auth.type == AuthType.HTTP_BEARER:
        print(f"  format={auth.bearer_format}")
```

### Access models and convert to JSON Schema

```python
for name, model in spec.models.items():
    print(f"Model: {name}")
    json_schema = model.schema.to_json_schema()
    print(f"  JSON Schema: {json_schema}")
```

### Validate without parsing

```python
errors = await parser.validate(Path("petstore.yaml"))
if errors:
    for err in errors:
        print(f"[{err.severity}] {err.message} at {err.path}")
else:
    print("Valid!")
```

---

## How Downstream Components Use the IR

### MCP Tool Generator (F1.2)

Consumes `APISpec.endpoints` to generate MCP tool definitions:
- `endpoint.operation_id` becomes the tool name
- `endpoint.parameters` + `endpoint.request_body` become `input_schema` (via `to_json_schema()`)
- `endpoint.responses` inform the tool's return type documentation
- `endpoint.pagination` triggers auto-pagination tool wrappers

### MCP Tool Adapter (F5.1)

Bridges MCP tools to LangChain `StructuredTool` using the same schema:
- `SchemaRef.to_json_schema()` produces the Pydantic model for tool arguments
- `ref_name` is used for readable tool descriptions

### Tool Registry (F5.2)

Uses `APISpec` metadata for tool discovery:
- `endpoint.tags` map to tool categories
- `endpoint.security` determines which auth scheme to attach
- Colon namespacing: `{server_name}:{operation_id}` (e.g., `github:list_issues`)

---

## Sample IR Output

See `examples/sample-IR.md` for a complete JSON dump of the Petstore spec parsed into IR.
