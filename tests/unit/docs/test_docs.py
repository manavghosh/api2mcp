"""Unit tests for F7.3 Documentation Site.

Validates:
- All required doc files exist with the correct structure
- mkdocs.yml is valid YAML referencing real files
- No broken internal links (relative links point to existing files)
- Code examples in Getting Started are syntactically correct Python
- Contributing guide covers required sections
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[3]
_DOCS = _ROOT / "docs"
_MKDOCS_YML = _ROOT / "mkdocs.yml"


# ---------------------------------------------------------------------------
# Required file manifest
# ---------------------------------------------------------------------------

_REQUIRED_FILES = [
    _MKDOCS_YML,
    _DOCS / "index.md",
    _DOCS / "getting-started.md",
    _DOCS / "contributing.md",
    _DOCS / "tutorials" / "basic.md",
    _DOCS / "tutorials" / "auth.md",
    _DOCS / "tutorials" / "orchestration.md",
    _DOCS / "tutorials" / "multi-api.md",
    _DOCS / "reference" / "cli.md",
    _DOCS / "reference" / "config.md",
    _DOCS / "reference" / "api" / "index.md",
    _DOCS / "examples" / "github.md",
    _DOCS / "examples" / "stripe.md",
    _DOCS / "examples" / "multi-api.md",
    _ROOT / ".github" / "workflows" / "docs.yml",
]


@pytest.mark.parametrize("path", _REQUIRED_FILES, ids=[p.name for p in _REQUIRED_FILES])
def test_required_file_exists(path: Path) -> None:
    assert path.exists(), f"Required documentation file missing: {path}"


@pytest.mark.parametrize("path", _REQUIRED_FILES, ids=[p.name for p in _REQUIRED_FILES])
def test_required_file_not_empty(path: Path) -> None:
    assert path.stat().st_size > 0, f"Documentation file is empty: {path}"


# ---------------------------------------------------------------------------
# mkdocs.yml structure
# ---------------------------------------------------------------------------


def test_mkdocs_yml_is_valid_yaml() -> None:
    content = _MKDOCS_YML.read_text(encoding="utf-8")
    config = yaml.safe_load(content)
    assert isinstance(config, dict)


def test_mkdocs_yml_has_site_name() -> None:
    config = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    assert "site_name" in config
    assert config["site_name"]


def test_mkdocs_yml_uses_material_theme() -> None:
    config = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    assert config.get("theme", {}).get("name") == "material"


def test_mkdocs_yml_has_nav() -> None:
    config = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    assert "nav" in config
    assert len(config["nav"]) > 0


def test_mkdocs_yml_has_plugins() -> None:
    config = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))
    plugins = config.get("plugins", [])
    plugin_names = []
    for p in plugins:
        if isinstance(p, str):
            plugin_names.append(p)
        elif isinstance(p, dict):
            plugin_names.extend(p.keys())
    assert "search" in plugin_names
    assert "mkdocstrings" in plugin_names


def test_mkdocs_yml_nav_files_exist() -> None:
    """Every .md file referenced in nav must exist on disk."""
    config = yaml.safe_load(_MKDOCS_YML.read_text(encoding="utf-8"))

    def _collect_md_paths(nav_item) -> list[str]:
        paths: list[str] = []
        if isinstance(nav_item, dict):
            for v in nav_item.values():
                paths.extend(_collect_md_paths(v))
        elif isinstance(nav_item, list):
            for item in nav_item:
                paths.extend(_collect_md_paths(item))
        elif isinstance(nav_item, str) and nav_item.endswith(".md"):
            paths.append(nav_item)
        return paths

    md_paths = _collect_md_paths(config.get("nav", []))
    missing = [p for p in md_paths if not (_DOCS / p).exists()]
    assert missing == [], f"Nav references missing files: {missing}"


# ---------------------------------------------------------------------------
# Content structure checks
# ---------------------------------------------------------------------------


def test_index_has_quick_example() -> None:
    content = (_DOCS / "index.md").read_text(encoding="utf-8")
    assert "api2mcp generate" in content


def test_getting_started_has_five_minute_quickstart() -> None:
    content = (_DOCS / "getting-started.md").read_text(encoding="utf-8")
    # Should have numbered steps
    assert "## 1." in content or "## Step 1" in content


def test_getting_started_covers_install() -> None:
    content = (_DOCS / "getting-started.md").read_text(encoding="utf-8")
    assert "pip install" in content


def test_getting_started_covers_generate() -> None:
    content = (_DOCS / "getting-started.md").read_text(encoding="utf-8")
    assert "api2mcp generate" in content


def test_getting_started_covers_serve() -> None:
    content = (_DOCS / "getting-started.md").read_text(encoding="utf-8")
    assert "api2mcp serve" in content


def test_tutorial_basic_has_code_blocks() -> None:
    content = (_DOCS / "tutorials" / "basic.md").read_text(encoding="utf-8")
    assert "```" in content


def test_tutorial_auth_covers_api_key() -> None:
    content = (_DOCS / "tutorials" / "auth.md").read_text(encoding="utf-8")
    assert "api_key" in content.lower() or "API Key" in content


def test_tutorial_auth_covers_oauth2() -> None:
    content = (_DOCS / "tutorials" / "auth.md").read_text(encoding="utf-8")
    assert "oauth2" in content.lower() or "OAuth" in content


def test_tutorial_orchestration_covers_langgraph() -> None:
    content = (_DOCS / "tutorials" / "orchestration.md").read_text(encoding="utf-8")
    assert "LangGraph" in content or "langgraph" in content


def test_tutorial_orchestration_covers_all_graph_types() -> None:
    content = (_DOCS / "tutorials" / "orchestration.md").read_text(encoding="utf-8")
    assert "ReactiveGraph" in content
    assert "PlannerGraph" in content
    assert "ConversationalGraph" in content


def test_tutorial_multi_api_mentions_namespacing() -> None:
    content = (_DOCS / "tutorials" / "multi-api.md").read_text(encoding="utf-8")
    # Should mention the colon namespace pattern
    assert "github:" in content or "colon" in content


def test_reference_cli_covers_all_commands() -> None:
    content = (_DOCS / "reference" / "cli.md").read_text(encoding="utf-8")
    for cmd in ("generate", "serve", "validate", "wizard", "template"):
        assert f"api2mcp {cmd}" in content, f"CLI reference missing '{cmd}' command"


def test_reference_config_covers_all_keys() -> None:
    content = (_DOCS / "reference" / "config.md").read_text(encoding="utf-8")
    for key in ("output", "host", "port", "transport", "log_level"):
        assert key in content, f"Config reference missing key '{key}'"


def test_examples_github_has_code() -> None:
    content = (_DOCS / "examples" / "github.md").read_text(encoding="utf-8")
    assert "```python" in content or "```bash" in content


def test_examples_stripe_has_code() -> None:
    content = (_DOCS / "examples" / "stripe.md").read_text(encoding="utf-8")
    assert "```python" in content or "```bash" in content


def test_contributing_covers_required_sections() -> None:
    content = (_DOCS / "contributing.md").read_text(encoding="utf-8")
    required = ["Setup", "Tests", "Style", "Pull Request"]
    for section in required:
        assert section in content, f"Contributing guide missing section about '{section}'"


# ---------------------------------------------------------------------------
# Python code block syntax validation
# ---------------------------------------------------------------------------


def _extract_python_blocks(md_path: Path) -> list[str]:
    """Extract all ```python code blocks from a Markdown file, dedented."""
    import textwrap
    content = md_path.read_text(encoding="utf-8")
    pattern = re.compile(r"```python\n(.*?)```", re.DOTALL)
    return [textwrap.dedent(block) for block in pattern.findall(content)]


_PYTHON_DOCS = [
    _DOCS / "getting-started.md",
    _DOCS / "tutorials" / "basic.md",
    _DOCS / "tutorials" / "auth.md",
    _DOCS / "tutorials" / "orchestration.md",
    _DOCS / "tutorials" / "multi-api.md",
    _DOCS / "examples" / "github.md",
    _DOCS / "examples" / "stripe.md",
    _DOCS / "examples" / "multi-api.md",
    _DOCS / "contributing.md",
]


@pytest.mark.parametrize("doc_path", _PYTHON_DOCS, ids=[p.name for p in _PYTHON_DOCS])
def test_python_code_blocks_are_syntactically_valid(doc_path: Path) -> None:
    """All ```python code blocks must parse without SyntaxError."""
    blocks = _extract_python_blocks(doc_path)
    for i, block in enumerate(blocks):
        try:
            ast.parse(block)
        except SyntaxError as exc:
            pytest.fail(
                f"SyntaxError in Python block {i + 1} of {doc_path.name}: {exc}\n"
                f"--- Block ---\n{block}"
            )


# ---------------------------------------------------------------------------
# Internal link validation
# ---------------------------------------------------------------------------


def _extract_md_links(md_path: Path) -> list[tuple[str, str]]:
    """Return (link_text, href) pairs for all Markdown links in the file."""
    content = md_path.read_text(encoding="utf-8")
    # Match [text](href) but not ![alt](img)
    pattern = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
    return pattern.findall(content)


def test_no_broken_internal_links() -> None:
    """Every relative .md link in the docs must point to an existing file."""
    broken: list[str] = []

    for md_file in _DOCS.rglob("*.md"):
        for _text, href in _extract_md_links(md_file):
            # Skip external URLs and anchors-only
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # Strip anchor
            href_no_anchor = href.split("#")[0]
            if not href_no_anchor:
                continue
            # Resolve relative to the containing file's directory
            target = (md_file.parent / href_no_anchor).resolve()
            if not target.exists():
                broken.append(f"{md_file.relative_to(_ROOT)} → {href}")

    assert broken == [], "Broken internal links found:\n" + "\n".join(broken)


# ---------------------------------------------------------------------------
# CI workflow validation
# ---------------------------------------------------------------------------


def test_ci_docs_workflow_is_valid_yaml() -> None:
    path = _ROOT / ".github" / "workflows" / "docs.yml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(config, dict)


def test_ci_docs_workflow_has_build_job() -> None:
    path = _ROOT / ".github" / "workflows" / "docs.yml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = config.get("jobs", {})
    assert "build" in jobs


def test_ci_docs_workflow_has_deploy_job() -> None:
    path = _ROOT / ".github" / "workflows" / "docs.yml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = config.get("jobs", {})
    assert "deploy" in jobs


def test_ci_docs_workflow_build_uses_mkdocs() -> None:
    path = _ROOT / ".github" / "workflows" / "docs.yml"
    content = path.read_text(encoding="utf-8")
    assert "mkdocs build" in content
