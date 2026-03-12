# API2MCP

> Universal API to MCP Server Converter with LangGraph Orchestration

[![CI](https://github.com/manavghosh/api2mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/manavghosh/api2mcp/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/api2mcp)](https://pypi.org/project/api2mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/api2mcp)](https://pypi.org/project/api2mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Coverage](https://codecov.io/gh/manavghosh/api2mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/manavghosh/api2mcp)

Convert any REST/GraphQL API into a fully functional MCP (Model Context Protocol) server, and orchestrate intelligent multi-API workflows using LangGraph.

API2MCP v0.1.0 is a complete framework, not a preview. Here's what's available today:

Core Pipeline
- OpenAPI 3.0/3.1, Swagger 2.0, GraphQL SDL, and Postman Collection parsers
- MCP Tool Generator with full JSON Schema type mapping
- Streamable HTTP and stdio transports (MCP spec 2025-03-26 compliant)

Security & Infrastructure
- Authentication: API key, Bearer, Basic, OAuth 2.0 (client credentials + PKCE)
- Secret management: environment variables, OS keychain, HashiCorp Vault, AWS Secrets Manager, encrypted file store
- Input validation: SQL injection and command injection protection
- Rate limiting (token bucket, per-tool configurable), circuit breaker, connection pooling, response caching (memory and Redis)

LangGraph Orchestration
- ReactiveGraph, PlannerGraph, ConversationalGraph
- MCP Tool Adapter (MCP → LangChain StructuredTool) with colon namespacing
- Checkpointing: MemorySaver, SqliteSaver, PostgresSaver
- End-to-end streaming via LangGraph astream_events v2
- Multi-model support: Anthropic, OpenAI, Google Gemini

Developer Experience
- Interactive setup wizard (`api2mcp wizard`)
- Hot reload dev server (`api2mcp dev`)
- In-process testing framework (MCPTestClient, CoverageReporter)
- VS Code integration (launch configs, tasks, schema validation)
- Plugin system with lifecycle hooks, template registry, CLI export and diff commands


## Features

- 🔄 **Automatic Conversion**: OpenAPI, GraphQL, Postman → MCP Server
- 🔐 **Enterprise Security**: OAuth 2.0, API keys, secret management
- 🧠 **Intelligent Orchestration**: LangGraph-powered multi-API workflows
- 💾 **State Persistence**: Checkpoint-based workflow recovery
- 🔌 **Extensible**: Plugin architecture for custom integrations

## Quick Start

```bash
# Install
pip install api2mcp

# Generate MCP server from OpenAPI spec
api2mcp generate --spec openapi.yaml --output ./server

# Run the server
api2mcp serve ./server
```

## LangGraph 1.0 Orchestration

```python
from api2mcp import MCPToolRegistry, PlannerGraph
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.sqlite import SqliteSaver

# Register MCP servers
registry = MCPToolRegistry()
await registry.connect_server("github", github_config)
await registry.connect_server("jira", jira_config)

# Create orchestrator with official checkpointer
orchestrator = PlannerGraph(
    model=ChatAnthropic(model="claude-sonnet-4-5-20250929"),
    tool_registry=registry,
    api_names=["github", "jira"],
    checkpointer=SqliteSaver.from_conn_string("workflows.db"),
    execution_mode="mixed"  # parallel for independent steps
)

# Run complex workflow
result = await orchestrator.run(
    "Sync all GitHub bugs to Jira project SUPPORT"
)
```

## Documentation

- [Getting Started](./docs/getting-started.md)
- [Configuration Reference](./docs/reference/config.md)
- [CLI Reference](./docs/reference/cli.md)
- [Orchestration Tutorial](./docs/tutorials/orchestration.md)
- [Contributing Guide](./docs/contributing.md)

## Development

### Prerequisites

- Python 3.11+
- [pip](https://pip.pypa.io/) or any PEP 517-compatible build tool

### Setup

```bash
# Clone and install in editable mode with dev dependencies
git clone https://github.com/manavghosh/api2mcp.git
cd api2mcp
pip install -e ".[dev]"
```

### Optional extras

```bash
pip install -e ".[dev,graphql]"    # add GraphQL parser support
pip install -e ".[dev,postgres]"   # add PostgreSQL checkpointer
pip install -e ".[dev,docs]"       # add MkDocs documentation tooling
```

### Running tests

```bash
pytest                        # run full test suite
pytest tests/unit/            # unit tests only
pytest -m "not e2e"           # skip end-to-end tests
pytest --no-cov               # skip coverage (faster)
```

### Linting and type-checking

```bash
ruff check .                  # lint
ruff format .                 # format
mypy src/                     # type-check
```

### Building the package

```bash
pip install build
python -m build               # produces dist/*.whl and dist/*.tar.gz
```

### Building the documentation site

```bash
pip install -e ".[docs]"
mkdocs serve                  # live-reload preview at http://127.0.0.1:8000
mkdocs build --strict         # static build into site/
```

## Project Structure

```
api2mcp/
├── src/api2mcp/         # Source code
│   ├── orchestration/   # LangGraph integration
│   │   ├── adapters/    # MCP-to-LangChain adapters
│   │   ├── graphs/      # Workflow patterns
│   │   └── state/       # State management
│   └── ...
├── tests/               # Test suite
├── docs/                # Documentation source (MkDocs)
├── examples/            # Usage examples
└── demo/                # Runnable demos
```

## Acknowledgements

API2MCP was built with the assistance of [Claude](https://claude.ai) (Anthropic). The product vision, architecture decisions, specifications, and every design trade-off were directed by the project author. Claude served as the implementation tool — the same way a framework or a compiler is a tool.

Key open source projects that power API2MCP:

| Project | Role |
|---------|------|
| [LangGraph](https://github.com/langchain-ai/langgraph) | Orchestration graph engine |
| [MCP SDK](https://github.com/modelcontextprotocol/python-sdk) | Model Context Protocol runtime |
| [Pydantic](https://docs.pydantic.dev/) | Data validation |
| [httpx](https://www.python-httpx.org/) | Async HTTP client |
| [Click](https://click.palletsprojects.com/) | CLI framework |
| [Rich](https://rich.readthedocs.io/) | Terminal output |
| [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) | Documentation site |

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](./CONTRIBUTING.md) and our [Code of Conduct](./CODE_OF_CONDUCT.md) before submitting a pull request.

## License

MIT License - see [LICENSE](./LICENSE) for details.
