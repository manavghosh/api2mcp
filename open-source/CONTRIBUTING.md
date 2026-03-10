# Contributing to API2MCP

Thank you for your interest in contributing! API2MCP is an open source project and
welcomes contributions of all kinds — bug fixes, new features, documentation
improvements, and community support.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Documentation](#documentation)
- [Release Process](#release-process)

---

## Code of Conduct

By participating in this project you agree to abide by the
[Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

---

## Ways to Contribute

- **Fix a bug** — Search open issues labeled `bug` and pick one up
- **Add a feature** — Check `help wanted` or `enhancement` issues
- **Improve docs** — Fix typos, clarify explanations, add examples
- **Write tests** — Increase coverage for under-tested modules
- **Triage issues** — Help reproduce bugs and add missing information
- **Review PRs** — Comment on open pull requests
- **Good first issue** — New contributor? Filter by the `good first issue` label

---

## Getting Started

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/api2mcp.git
cd api2mcp
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows
```

### 3. Install in editable mode with all dev extras

```bash
pip install -e ".[dev,openai,google]"
```

### 4. Verify the test suite passes

```bash
pytest
```

All tests should pass before you start making changes.

---

## Development Workflow

1. **Create a branch** from `main` for your change:

   ```bash
   git checkout -b fix/short-description
   git checkout -b feat/short-description
   git checkout -b docs/short-description
   ```

2. **Make your changes** following the [Coding Standards](#coding-standards) below.

3. **Write or update tests** — every change must include tests (see [Testing Requirements](#testing-requirements)).

4. **Run the full quality check locally** before pushing:

   ```bash
   pytest                          # all tests must pass
   ruff check src/ tests/          # zero lint errors
   mypy src/                       # zero type errors
   bandit -r src/ -ll              # no high-severity security issues
   ```

5. **Commit** with a clear, conventional commit message:

   ```
   fix(parser): handle missing operationId in OpenAPI 3.1
   feat(orchestration): add retry backoff for tool call failures
   docs(readme): add quickstart for GraphQL APIs
   ```

6. **Push** and open a Pull Request against `main`.

---

## Coding Standards

- **Python 3.11+** — use modern syntax (match, `X | Y` unions, `Self`, etc.)
- **Type hints everywhere** — all function signatures must be fully typed
- **Async/await** for all I/O operations — no blocking calls in async context
- **PEP 8** formatting — enforced by `ruff`
- **Pydantic v2** for all data validation and serialization models
- **No print statements** in library code — use `logging` or the `rich` console from `cli/output.py`
- **No hardcoded secrets** — use environment variables; document them

### Import order (enforced by ruff)

```python
# 1. Standard library
import asyncio
from typing import Any

# 2. Third-party
import httpx
from pydantic import BaseModel

# 3. Local
from api2mcp.core import IRSpec
```

---

## Testing Requirements

All contributions must include tests. The project targets:

- **80% overall coverage** (currently 81.65%)
- **100% coverage** for security-critical paths (auth, validation, secrets)

### Test locations

| What you changed | Where to add tests |
|------------------|--------------------|
| `src/api2mcp/parsers/` | `tests/unit/parsers/` |
| `src/api2mcp/generators/` | `tests/unit/generators/` |
| `src/api2mcp/orchestration/` | `tests/unit/orchestration/` |
| `src/api2mcp/cli/commands/` | `tests/unit/cli/` |
| `src/api2mcp/auth/` | `tests/unit/auth/` |
| Cross-component | `tests/integration/` |

### Running specific tests

```bash
pytest tests/unit/parsers/ -v
pytest tests/unit/orchestration/test_reactive_graph.py -v
pytest --cov=src/api2mcp --cov-report=term-missing
```

---

## Submitting a Pull Request

1. Ensure all CI checks pass (tests, lint, type check, security scan)
2. Fill in the pull request template completely
3. Link the related issue: `Fixes #123` or `Closes #456`
4. Add a clear description of **what** changed and **why**
5. Keep PRs focused — one feature or fix per PR
6. Be responsive to reviewer feedback — address comments within a week

### PR title format

Follow the same conventional commit format:

```
fix: correct JSON encoding of nested tool arguments
feat: add Postman collection v2.1 parser
docs: add tutorial for multi-API orchestration
chore: bump httpx to 0.28.1
```

---

## Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template. Include:

- API2MCP version (`api2mcp --version`)
- Python version (`python --version`)
- Operating system
- Minimal reproduction steps
- Expected vs actual behaviour
- Relevant logs or error messages

---

## Requesting Features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template.
Before opening, search existing issues to avoid duplicates.

For large changes (new graph patterns, new parsers, protocol changes), open a
**Discussion** first to align on design before writing code.

---

## Documentation

Documentation lives in `docs/` and is built with MkDocs. To preview locally:

```bash
pip install mkdocs-material
mkdocs serve
```

Then open `http://localhost:8000`.

Documentation PRs are very welcome — typo fixes, new examples, and tutorials all
count as valuable contributions.

---

## Release Process

Releases are managed by the maintainers. If you believe a fix is urgent, tag your
PR with `release-blocker` and ping a maintainer.

Version numbers follow [Semantic Versioning](https://semver.org):

- `PATCH` (0.1.x) — backwards-compatible bug fixes
- `MINOR` (0.x.0) — new backwards-compatible features
- `MAJOR` (x.0.0) — breaking changes

---

## Questions?

- **GitHub Discussions** — for general questions and ideas
- **Issues** — for bugs and feature requests
- **Pull Requests** — for code contributions

We appreciate every contribution, large or small. Thank you for helping make
API2MCP better for everyone.
