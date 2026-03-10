"""Unit tests for LLMFactory and LLMConfigError."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api2mcp.orchestration.llm import LLMConfigError, LLMFactory


# ---------------------------------------------------------------------------
# LLMConfigError
# ---------------------------------------------------------------------------


class TestLLMConfigError:
    def test_message_only(self) -> None:
        exc = LLMConfigError("bad provider")
        assert str(exc) == "bad provider"
        assert exc.hint == ""

    def test_message_with_hint(self) -> None:
        exc = LLMConfigError("missing key", hint="set ANTHROPIC_API_KEY")
        assert "missing key" in str(exc)
        assert "set ANTHROPIC_API_KEY" in str(exc)

    def test_is_value_error(self) -> None:
        exc = LLMConfigError("x")
        assert isinstance(exc, ValueError)


# ---------------------------------------------------------------------------
# LLMFactory.supported_providers / default_model
# ---------------------------------------------------------------------------


class TestLLMFactoryMeta:
    def test_supported_providers(self) -> None:
        providers = LLMFactory.supported_providers()
        assert "anthropic" in providers
        assert "openai" in providers
        assert "google" in providers

    def test_default_model_anthropic(self) -> None:
        assert LLMFactory.default_model("anthropic") == "claude-sonnet-4-6"

    def test_default_model_openai(self) -> None:
        assert LLMFactory.default_model("openai") == "gpt-4o"

    def test_default_model_google(self) -> None:
        assert LLMFactory.default_model("google") == "gemini-2.0-flash"

    def test_default_model_unknown_raises(self) -> None:
        with pytest.raises(LLMConfigError, match="Unknown provider"):
            LLMFactory.default_model("bogus")


# ---------------------------------------------------------------------------
# LLMFactory._resolve_api_key
# ---------------------------------------------------------------------------


class TestResolveApiKey:
    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(LLMConfigError, match="not set"):
            LLMFactory._resolve_api_key("anthropic")

    def test_present_key_returned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        assert LLMFactory._resolve_api_key("anthropic") == "sk-ant-test"

    def test_whitespace_only_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        with pytest.raises(LLMConfigError, match="not set"):
            LLMFactory._resolve_api_key("anthropic")


# ---------------------------------------------------------------------------
# LLMFactory.create — provider validation
# ---------------------------------------------------------------------------


class TestLLMFactoryCreate:
    def test_unsupported_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        with pytest.raises(LLMConfigError, match="Unsupported LLM provider"):
            LLMFactory.create(provider="cohere", api_key="x")

    def test_env_provider_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_openai", return_value=mock_model) as mock_make:
            result = LLMFactory.create()
        mock_make.assert_called_once()
        assert result is mock_model

    def test_explicit_provider_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_anthropic", return_value=mock_model) as mock_make:
            result = LLMFactory.create(provider="anthropic")
        mock_make.assert_called_once()
        assert result is mock_model

    def test_explicit_api_key_bypasses_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_anthropic", return_value=mock_model):
            result = LLMFactory.create(provider="anthropic", api_key="sk-explicit")
        assert result is mock_model

    def test_temperature_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_anthropic", return_value=mock_model) as mock_make:
            LLMFactory.create(provider="anthropic")
        _, temperature, _ = mock_make.call_args[0]
        assert temperature == pytest.approx(0.7)

    def test_explicit_temperature_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_TEMPERATURE", "0.9")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_anthropic", return_value=mock_model) as mock_make:
            LLMFactory.create(provider="anthropic", temperature=0.2)
        _, temperature, _ = mock_make.call_args[0]
        assert temperature == pytest.approx(0.2)

    def test_model_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "claude-opus-4-6")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_anthropic", return_value=mock_model) as mock_make:
            LLMFactory.create(provider="anthropic")
        model_name, _, _ = mock_make.call_args[0]
        assert model_name == "claude-opus-4-6"


# ---------------------------------------------------------------------------
# LLMFactory.create — provider dispatch
# ---------------------------------------------------------------------------


class TestLLMFactoryDispatch:
    def test_anthropic_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_anthropic", return_value=mock_model) as mock_make:
            result = LLMFactory.create(provider="anthropic")
        mock_make.assert_called_once()
        assert result is mock_model

    def test_openai_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_openai", return_value=mock_model) as mock_make:
            result = LLMFactory.create(provider="openai")
        mock_make.assert_called_once()
        assert result is mock_model

    def test_google_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "AIza-test")
        mock_model = MagicMock()
        with patch.object(LLMFactory, "_make_google", return_value=mock_model) as mock_make:
            result = LLMFactory.create(provider="google")
        mock_make.assert_called_once()
        assert result is mock_model


# ---------------------------------------------------------------------------
# LLMFactory._make_* — missing package raises LLMConfigError
# ---------------------------------------------------------------------------


class TestLLMFactoryMakeProviders:
    def test_make_anthropic_import_error(self) -> None:
        with patch.dict("sys.modules", {"langchain_anthropic": None}):
            with pytest.raises(LLMConfigError, match="langchain-anthropic"):
                LLMFactory._make_anthropic("claude-sonnet-4-6", 0.0, "key")

    def test_make_openai_import_error(self) -> None:
        with patch.dict("sys.modules", {"langchain_openai": None}):
            with pytest.raises(LLMConfigError, match="langchain-openai"):
                LLMFactory._make_openai("gpt-4o", 0.0, "key")

    def test_make_google_import_error(self) -> None:
        with patch.dict("sys.modules", {"langchain_google_genai": None}):
            with pytest.raises(LLMConfigError, match="langchain-google-genai"):
                LLMFactory._make_google("gemini-2.0-flash", 0.0, "key")
