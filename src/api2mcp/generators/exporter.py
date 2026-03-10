# SPDX-License-Identifier: MIT
"""Export generator — package a generated MCP server for distribution."""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_DOCKERFILE_TEMPLATE = """\
FROM python:3.11-slim
WORKDIR /app
COPY . /app/
RUN pip install --no-cache-dir api2mcp
EXPOSE 8000
CMD ["api2mcp", "serve", "/app", "--transport", "http", "--port", "8000"]
"""

_DOCKERIGNORE_TEMPLATE = """\
__pycache__/
*.pyc
*.pyo
.pytest_cache/
*.egg-info/
"""


def export_as_docker(server_dir: Path, output_dir: Path) -> Path:
    """Write a Dockerfile (and .dockerignore) to *output_dir*.

    Args:
        server_dir: Directory containing the generated MCP server.
        output_dir: Directory to write the Dockerfile into.

    Returns:
        Path to the created Dockerfile.
    """
    _ = server_dir  # reserved for future inclusion of server files in Docker context
    output_dir.mkdir(parents=True, exist_ok=True)
    dockerfile = output_dir / "Dockerfile"
    dockerfile.write_text(_DOCKERFILE_TEMPLATE, encoding="utf-8")
    dockerignore = output_dir / ".dockerignore"
    dockerignore.write_text(_DOCKERIGNORE_TEMPLATE, encoding="utf-8")
    logger.info("Exported Dockerfile to %s", dockerfile)
    return dockerfile


_SETUP_PY_TEMPLATE = """\
from setuptools import setup, find_packages
setup(
    name="{name}",
    version="0.1.0",
    packages=find_packages(),
    install_requires=["api2mcp"],
)
"""


def export_as_wheel(server_dir: Path, output_dir: Path) -> Path:
    """Create a wheel-like zip archive of *server_dir* with a setup.py stub.

    Args:
        server_dir:  Directory containing the generated MCP server.
        output_dir:  Directory to write the .whl file into.

    Returns:
        Path to the created .whl file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    name = server_dir.name.replace("-", "_").replace(" ", "_") or "mcp_server"
    wheel_path = output_dir / f"{name}-0.1.0-py3-none-any.whl"

    setup_py = _SETUP_PY_TEMPLATE.format(name=name)

    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in server_dir.rglob("*"):
            if f.is_file() and "__pycache__" not in str(f):
                zf.write(f, f.relative_to(server_dir))
        zf.writestr("setup.py", setup_py)

    logger.info("Exported wheel archive to %s", wheel_path)
    return wheel_path


def export_as_zip(server_dir: Path, output_path: Path) -> Path:
    """Create a self-contained zip archive of *server_dir*.

    Args:
        server_dir:  Directory containing the generated MCP server.
        output_path: Path for the output .zip file.

    Returns:
        Path to the created zip file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in server_dir.rglob("*"):
            if f.is_file() and "__pycache__" not in str(f):
                zf.write(f, f.relative_to(server_dir))
    logger.info("Exported zip archive to %s", output_path)
    return output_path
