# Contributing to API2MCP

Thank you for your interest in contributing! This guide explains how to set
up a development environment and submit changes.

---

## Development Setup

### 1. Fork and clone

```bash
git clone https://github.com/manavghosh/api2mcp
cd api2mcp
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
.venv\Scripts\activate         # Windows
```

### 3. Install in editable mode with dev dependencies

```bash
pip install -e ".[dev,docs,graphql]"
```

### 4. Install pre-commit hooks

```bash
pre-commit install
```

---

## Project Structure

```
api2mcp/
├── src/api2mcp/           # Main package
│   ├── cli/               # Click CLI commands
│   ├── core/              # IR schema and base types
│   ├── parsers/           # OpenAPI, GraphQL, Postman, Swagger parsers
│   ├── generators/        # MCP tool/server generator
│   ├── runtime/           # MCP server runtime
│   ├── auth/              # Authentication providers
│   ├── secrets/           # Secret management backends
│   ├── validation/        # Input validation and sanitisation
│   ├── ratelimit/         # Rate limiting middleware
│   ├── cache/             # Response caching
│   ├── pool/              # Connection pooling
│   ├── circuitbreaker/    # Circuit breaker
│   ├── hotreload/         # Dev server with file watching
│   ├── testing/           # MCPTestClient, snapshots, coverage
│   ├── templates/         # Template registry and installer
│   ├── plugins/           # Plugin system and hook manager
│   └── orchestration/     # LangGraph graphs and adapters
├── tests/
│   ├── unit/              # Unit tests (no external deps)
│   └── integration/       # Integration tests
├── docs/                  # Documentation (MkDocs)
├── schemas/               # JSON Schemas for VS Code
├── .vscode/               # VS Code workspace config
└── examples/              # Usage examples
```

---

## Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/ --no-cov

# Integration tests
pytest tests/integration/ -m integration --no-cov

# Specific module
pytest tests/unit/plugins/ --no-cov -v

# With coverage
pytest --cov=src/api2mcp --cov-report=html
```

---

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for formatting and linting.

```bash
# Format
ruff format src/ tests/

# Lint
ruff check src/ tests/

# Both (via pre-commit)
pre-commit run --all-files
```

### Style rules

- Python 3.11+
- Type hints on **all** function signatures
- `async`/`await` for all I/O operations
- Google-style docstrings
- No `print()` in library code — use `logging`
- No wildcard imports

---

## Adding a New Parser

1. Create `src/api2mcp/parsers/myformat.py`
2. Subclass `BaseParser` from `src/api2mcp/core/parser.py`
3. Implement `parse()`, `validate()`, and `detect()`
4. Register in `src/api2mcp/parsers/__init__.py`
5. Add unit tests in `tests/unit/parsers/test_myformat.py`
6. Add integration tests in `tests/integration/parsers/`

### Minimal parser skeleton

```python
from pathlib import Path
from api2mcp.core.ir_schema import APISpec
from api2mcp.core.parser import BaseParser, ParseError

class MyFormatParser(BaseParser):
    async def parse(self, source: str | Path, **kwargs) -> APISpec:
        ...

    async def validate(self, source: str | Path, **kwargs) -> list[ParseError]:
        ...

    def detect(self, content: dict) -> bool:
        return "myformat_key" in content
```

---

## Adding a New Plugin

See the [Plugin System](tutorials/orchestration.md) for the full plugin API.

```python
from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.hooks import POST_PARSE

class MyPlugin(BasePlugin):
    id = "my-plugin"
    name = "My Plugin"
    version = "1.0.0"
    description = "Does something useful"

    def setup(self, hook_manager):
        hook_manager.register_hook(POST_PARSE, self._on_post_parse, plugin_id=self.id)

    def _on_post_parse(self, *, api_spec, **kwargs):
        # Modify or inspect the spec
        pass
```

Register in `pyproject.toml`:

```toml
[project.entry-points."api2mcp.plugins"]
my-plugin = "my_package.plugin:MyPlugin"
```

---

## Documentation

Build the docs locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

Open `http://127.0.0.1:8000` in your browser.

---

## Submitting a Pull Request

1. Create a feature branch: `git checkout -b feat/my-feature`
2. Write code **and tests** (minimum 80% coverage for new modules)
3. Run `pre-commit run --all-files` and fix any issues
4. Run `pytest` and ensure all tests pass
5. Push and open a PR with a clear description

### PR checklist

- [ ] Tests added / updated
- [ ] Docstrings on public functions and classes
- [ ] `CHANGELOG.md` entry (if user-facing change)
- [ ] Documentation updated (if adding a new feature)

---

## Getting Help

- Open an issue on GitHub for bugs or feature requests
- Start a Discussion for questions and ideas
- Check existing issues and PRs before opening a new one
