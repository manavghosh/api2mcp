# SPDX-License-Identifier: MIT
"""LLM Factory for API2MCP orchestration layer.

Provides a provider-agnostic way to instantiate any LangChain-compatible
chat model for use with the LangGraph graph patterns (ReactiveGraph,
PlannerGraph, ConversationalGraph).

Supported providers
-------------------
- **anthropic** — Claude models via ``langchain-anthropic``
- **openai**    — GPT models via ``langchain-openai``
- **google**    — Gemini models via ``langchain-google-genai``

Configuration
-------------
All parameters can be supplied explicitly or read from environment variables:

======================  ======================  =============================
Parameter               Env var                 Default
======================  ======================  =============================
``provider``            ``LLM_PROVIDER``        ``"anthropic"``
``model``               ``LLM_MODEL``           provider's flagship model
``temperature``         ``LLM_TEMPERATURE``     ``0``
``api_key``             provider-specific key   *(required — no default)*
======================  ======================  =============================

Provider API-key environment variables:

- ``ANTHROPIC_API_KEY`` — https://console.anthropic.com/
- ``OPENAI_API_KEY``    — https://platform.openai.com/api-keys
- ``GOOGLE_API_KEY``    — https://aistudio.google.com/app/apikey

Usage::

    from api2mcp.orchestration.llm import LLMFactory

    # Use environment variables
    model = LLMFactory.create()

    # Explicit provider + model
    model = LLMFactory.create(provider="openai", model="gpt-4o-mini")

    # Google Gemini, explicit temperature
    model = LLMFactory.create(provider="google", model="gemini-2.0-flash", temperature=0.3)

    # Pass to any graph
    from api2mcp import ReactiveGraph, MCPToolRegistry
    graph = ReactiveGraph(model, registry, api_name="github")
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

#: Default model per provider — always the current flagship model.
PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "google": "gemini-2.0-flash",
}

#: Environment variable that holds the API key for each provider.
PROVIDER_API_KEY_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}

#: pip package that must be installed for each provider.
PROVIDER_PACKAGES: dict[str, str] = {
    "anthropic": "langchain-anthropic",
    "openai": "langchain-openai",
    "google": "langchain-google-genai",
}

#: Console URL for obtaining an API key per provider.
PROVIDER_KEY_URLS: dict[str, str] = {
    "anthropic": "https://console.anthropic.com/",
    "openai": "https://platform.openai.com/api-keys",
    "google": "https://aistudio.google.com/app/apikey",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMConfigError(ValueError):
    """Raised when the LLM provider/model/key configuration is invalid.

    Unlike a raw ``ValueError``, this carries a :attr:`hint` attribute with
    actionable instructions for the operator.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\n  Hint: {self.hint}" if self.hint else base


# ---------------------------------------------------------------------------
# LLMFactory
# ---------------------------------------------------------------------------


class LLMFactory:
    """Provider-agnostic factory for LangChain chat models.

    All class methods read configuration from environment variables by default
    and accept explicit keyword arguments that take precedence.

    .. code-block:: python

        # Simplest: reads LLM_PROVIDER / LLM_MODEL / <PROVIDER>_API_KEY from env
        model = LLMFactory.create()

        # Explicit provider override
        model = LLMFactory.create(provider="openai", model="gpt-4o-mini")
    """

    @classmethod
    def create(
        cls,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        api_key: str | None = None,
    ) -> BaseChatModel:
        """Instantiate a chat model for the requested provider.

        Parameters
        ----------
        provider:
            LLM provider — ``"anthropic"``, ``"openai"``, or ``"google"``.
            Defaults to the ``LLM_PROVIDER`` environment variable, which itself
            defaults to ``"anthropic"``.
        model:
            Model name (e.g. ``"claude-opus-4-6"``, ``"gpt-4o"``,
            ``"gemini-2.0-flash"``).  Defaults to the ``LLM_MODEL``
            environment variable; falls back to the provider's flagship model.
        temperature:
            Sampling temperature ``0.0``–``2.0``.  Defaults to the
            ``LLM_TEMPERATURE`` environment variable; falls back to ``0``.
        api_key:
            API key for the provider.  Defaults to the provider-specific
            environment variable (e.g. ``ANTHROPIC_API_KEY``).

        Returns
        -------
        BaseChatModel
            A LangChain-compatible chat model ready for use with LangGraph.

        Raises
        ------
        LLMConfigError
            If the provider is unsupported, the API key is missing, or the
            required ``langchain-*`` package is not installed.
        """
        resolved_provider = (
            (provider or os.environ.get("LLM_PROVIDER", "anthropic")).lower().strip()
        )
        resolved_model = (
            model
            or os.environ.get("LLM_MODEL", "").strip()
            or PROVIDER_DEFAULT_MODELS.get(resolved_provider, "")
        )
        resolved_temperature = (
            temperature
            if temperature is not None
            else float(os.environ.get("LLM_TEMPERATURE", "0"))
        )

        if resolved_provider not in PROVIDER_DEFAULT_MODELS:
            supported = ", ".join(sorted(PROVIDER_DEFAULT_MODELS))
            raise LLMConfigError(
                f"Unsupported LLM provider: {resolved_provider!r}",
                hint=f"Set LLM_PROVIDER to one of: {supported}",
            )

        resolved_api_key = api_key or cls._resolve_api_key(resolved_provider)

        logger.debug(
            "LLMFactory.create: provider=%s model=%s temperature=%s",
            resolved_provider,
            resolved_model,
            resolved_temperature,
        )

        if resolved_provider == "anthropic":
            return cls._make_anthropic(resolved_model, resolved_temperature, resolved_api_key)
        if resolved_provider == "openai":
            return cls._make_openai(resolved_model, resolved_temperature, resolved_api_key)
        if resolved_provider == "google":
            return cls._make_google(resolved_model, resolved_temperature, resolved_api_key)

        # Unreachable — guarded above
        raise LLMConfigError(f"Unhandled provider: {resolved_provider!r}")  # pragma: no cover

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @staticmethod
    def supported_providers() -> list[str]:
        """Return the list of supported provider names."""
        return sorted(PROVIDER_DEFAULT_MODELS.keys())

    @staticmethod
    def default_model(provider: str) -> str:
        """Return the default model name for *provider*.

        Raises :class:`LLMConfigError` for unknown providers.
        """
        provider = provider.lower().strip()
        if provider not in PROVIDER_DEFAULT_MODELS:
            raise LLMConfigError(
                f"Unknown provider: {provider!r}",
                hint=f"Supported: {', '.join(sorted(PROVIDER_DEFAULT_MODELS))}",
            )
        return PROVIDER_DEFAULT_MODELS[provider]

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_api_key(provider: str) -> str:
        """Return the API key from the environment; raise LLMConfigError if absent."""
        env_var = PROVIDER_API_KEY_VARS[provider]
        key = os.environ.get(env_var, "").strip()
        if not key:
            raise LLMConfigError(
                f"API key for provider {provider!r} is not set.",
                hint=(
                    f"Set the {env_var} environment variable. "
                    f"Get a key at: {PROVIDER_KEY_URLS[provider]}"
                ),
            )
        return key

    @staticmethod
    def _make_anthropic(model: str, temperature: float, api_key: str) -> BaseChatModel:
        try:
            from langchain_anthropic import (
                ChatAnthropic,  # type: ignore[import-not-found]
            )
        except ImportError as exc:
            raise LLMConfigError(
                "langchain-anthropic is not installed.",
                hint="Run: pip install langchain-anthropic  (or: pip install 'api2mcp[anthropic]')",
            ) from exc
        return ChatAnthropic(  # type: ignore[return-value]
            model=model, temperature=temperature, api_key=api_key
        )

    @staticmethod
    def _make_openai(model: str, temperature: float, api_key: str) -> BaseChatModel:
        try:
            from langchain_openai import ChatOpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise LLMConfigError(
                "langchain-openai is not installed.",
                hint="Run: pip install langchain-openai  (or: pip install 'api2mcp[openai]')",
            ) from exc
        return ChatOpenAI(  # type: ignore[return-value]
            model=model, temperature=temperature, api_key=api_key
        )

    @staticmethod
    def _make_google(model: str, temperature: float, api_key: str) -> BaseChatModel:
        try:
            from langchain_google_genai import (
                ChatGoogleGenerativeAI,  # type: ignore[import-not-found]
            )
        except ImportError as exc:
            raise LLMConfigError(
                "langchain-google-genai is not installed.",
                hint="Run: pip install langchain-google-genai  (or: pip install 'api2mcp[google]')",
            ) from exc
        return ChatGoogleGenerativeAI(  # type: ignore[return-value]
            model=model, temperature=temperature, google_api_key=api_key
        )
