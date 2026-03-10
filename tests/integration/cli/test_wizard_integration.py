"""Integration tests for F6.1 interactive wizard — full flow with mock inputs."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from api2mcp.cli.main import cli

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_MINIMAL_SPEC: dict = {
    "openapi": "3.0.3",
    "info": {"title": "Wizard Test API", "version": "2.0.0"},
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "summary": "List items",
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/items/{id}": {
            "get": {
                "operationId": "getItem",
                "summary": "Get item",
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {"200": {"description": "OK"}},
            }
        },
    },
}


@pytest.fixture()
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "openapi.yaml"
    path.write_text(yaml.dump(_MINIMAL_SPEC), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Full wizard flow
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_wizard_full_flow_stdio(spec_file: Path, tmp_path: Path) -> None:
    """Complete wizard: pre-select spec, skip step 1, confirm generation."""
    out = tmp_path / "wizard_out"

    # Inputs for each interactive step that remains:
    #   Step 2: no input (auto validation + display)
    #   Step 3: "1\n"  → no auth
    #   Step 4: "\n"   → accept default server name
    #            "1\n" → stdio transport
    #            f"{out}\n" → output directory
    #   Step 5: no input (preview display)
    #   Step 6: "y\n"  → confirm
    wizard_input = "\n".join(["1", "", "1", str(out), "y"]) + "\n"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(spec_file)],
        input=wizard_input,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (out / "server.py").exists()
    assert (out / "spec.yaml").exists()


@pytest.mark.integration
def test_wizard_full_flow_cancelled(spec_file: Path, tmp_path: Path) -> None:
    """User says N at confirmation — no files written."""
    out = tmp_path / "wizard_cancelled"

    wizard_input = "\n".join(["1", "", "1", str(out), "n"]) + "\n"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(spec_file)],
        input=wizard_input,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert not out.exists() or not (out / "server.py").exists()


@pytest.mark.integration
def test_wizard_presets_both_spec_and_output(spec_file: Path, tmp_path: Path) -> None:
    """Both --spec and --output pre-set: output dir is shown as default in step 4."""
    out = tmp_path / "preset_out"

    # Step 3: no auth (1)
    # Step 4: name="" (default), transport=1 (stdio), output="" (accept pre-set default)
    # Step 6: y
    wizard_input = "\n".join(["1", "", "1", "", "y"]) + "\n"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(spec_file), "--output", str(out)],
        input=wizard_input,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (out / "server.py").exists()


@pytest.mark.integration
def test_wizard_http_transport(spec_file: Path, tmp_path: Path) -> None:
    """Choose HTTP transport — host/port prompts appear."""
    out = tmp_path / "http_out"

    # Step 3: no auth (1)
    # Step 4: name="", transport=2 (http), host="127.0.0.1", port="9090", out_dir
    # Step 6: y
    wizard_input = "\n".join(["1", "", "2", "127.0.0.1", "9090", str(out), "y"]) + "\n"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(spec_file)],
        input=wizard_input,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (out / "server.py").exists()


@pytest.mark.integration
def test_wizard_with_api_key_auth(spec_file: Path, tmp_path: Path) -> None:
    """Choose API key auth — env var prompt appears."""
    out = tmp_path / "auth_out"

    # Step 3: auth=2 (api_key), env_var=MY_KEY
    # Step 4: name="", transport=1 (stdio), out_dir
    # Step 6: y
    wizard_input = "\n".join(["2", "MY_API_KEY", "", "1", str(out), "y"]) + "\n"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(spec_file)],
        input=wizard_input,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (out / "server.py").exists()


@pytest.mark.integration
def test_wizard_server_name_in_output(spec_file: Path, tmp_path: Path) -> None:
    """Custom server name appears in generated server.py."""
    out = tmp_path / "named_out"
    custom_name = "my_custom_server"

    wizard_input = "\n".join(["1", custom_name, "1", str(out), "y"]) + "\n"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(spec_file)],
        input=wizard_input,
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    server_code = (out / "server.py").read_text()
    assert custom_name in server_code


@pytest.mark.integration
def test_wizard_spec_detection_in_cwd(tmp_path: Path) -> None:
    """When no --spec given, wizard auto-detects spec in CWD."""
    spec = tmp_path / "openapi.yaml"
    spec.write_text(yaml.dump(_MINIMAL_SPEC), encoding="utf-8")
    out = tmp_path / "detected_out"

    # Step 1: select candidate "1" (auto-detected)
    # Step 3: no auth (1)
    # Step 4: name="", transport=1, out_dir
    # Step 6: y
    wizard_input = "\n".join(["1", "1", "", "1", str(out), "y"]) + "\n"

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Copy spec into the isolated filesystem cwd
        import shutil

        shutil.copy(spec, Path.cwd() / "openapi.yaml")
        result = runner.invoke(
            cli,
            ["wizard"],
            input=wizard_input,
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_wizard_nonexistent_spec_exits_nonzero(tmp_path: Path) -> None:
    """Passing a nonexistent --spec path should fail at the Click level."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["wizard", "--spec", str(tmp_path / "nope.yaml")],
    )
    assert result.exit_code != 0
