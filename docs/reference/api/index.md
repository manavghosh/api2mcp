# API Reference

Auto-generated reference documentation for all public API2MCP classes and functions.

---

## Core

### `api2mcp.core.ir_schema`

::: api2mcp.core.ir_schema
    options:
      members:
        - APISpec
        - Endpoint
        - Parameter
        - RequestBody
        - Response
        - SchemaRef
        - AuthScheme
        - HttpMethod
        - ParameterLocation

---

## Parsers

### `api2mcp.parsers.openapi`

::: api2mcp.parsers.openapi.OpenAPIParser

### `api2mcp.parsers.graphql`

::: api2mcp.parsers.graphql.GraphQLParser

### `api2mcp.parsers.postman`

::: api2mcp.parsers.postman.PostmanParser

---

## Generators

### `api2mcp.generators.tool`

::: api2mcp.generators.tool
    options:
      members:
        - ToolGenerator
        - MCPToolDef

---

## Testing

### `api2mcp.testing`

::: api2mcp.testing
    options:
      members:
        - MCPTestClient
        - ToolResult
        - CoverageReporter
        - CoverageReport
        - SnapshotStore
        - MockResponseGenerator
        - MockScenario

---

## Plugins

### `api2mcp.plugins`

::: api2mcp.plugins
    options:
      members:
        - BasePlugin
        - HookManager
        - PluginManager
        - PluginLoader
        - PluginSandbox

---

## Templates

### `api2mcp.templates`

::: api2mcp.templates
    options:
      members:
        - TemplateManifest
        - TemplateRegistry
        - TemplateInstaller

---

## Orchestration

### `api2mcp.orchestration.adapters`

::: api2mcp.orchestration.adapters.base.MCPToolAdapter

::: api2mcp.orchestration.adapters.registry.MCPToolRegistry

### Graphs

::: api2mcp.orchestration.graphs.reactive.ReactiveGraph

::: api2mcp.orchestration.graphs.planner.PlannerGraph

::: api2mcp.orchestration.graphs.conversational.ConversationalGraph
