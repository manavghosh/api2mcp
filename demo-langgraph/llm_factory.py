"""
LLM Factory — Multi-provider model selection for API2MCP LangGraph demos.

Supports three LLM providers configured via environment variables:

  LLM_PROVIDER    = anthropic | openai | google   (default: anthropic)
  LLM_MODEL       = <model name>                   (default: provider-specific)
  LLM_TEMPERATURE = 0.0–2.0                        (default: 0)

API key environment variables:
  ANTHROPIC_API_KEY  — required when LLM_PROVIDER=anthropic
  OPENAI_API_KEY     — required when LLM_PROVIDER=openai
  GOOGLE_API_KEY     — required when LLM_PROVIDER=google

Default models:
  anthropic → claude-opus-4-6
  openai    → gpt-4o
  google    → gemini-2.0-flash

Usage:
  from llm_factory import get_llm, print_provider_info
  model = get_llm()
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-6",
    "openai": "gpt-4o",
    "google": "gemini-2.0-flash",
}

_API_KEY_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}

_INSTALL_PACKAGES: dict[str, str] = {
    "anthropic": "langchain-anthropic",
    "openai": "langchain-openai",
    "google": "langchain-google-genai",
}

_KEY_URLS: dict[str, str] = {
    "anthropic": "https://console.anthropic.com/",
    "openai": "https://platform.openai.com/api-keys",
    "google": "https://aistudio.google.com/app/apikey",
}

# Strings that indicate the key is still a placeholder (not a real key)
_PLACEHOLDER_SUFFIXES = ("...",)
_PLACEHOLDER_VALUES = {"", "your-key-here", "CHANGE_ME", "sk-ant-api03-...", "sk-proj-...", "AIza..."}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_api_key(provider: str) -> str:
    """Return the API key for *provider*, exiting with a clear message if missing."""
    env_var = _API_KEY_VARS[provider]
    key = os.environ.get(env_var, "").strip()

    is_placeholder = (
        not key
        or key in _PLACEHOLDER_VALUES
        or any(key.endswith(s) for s in _PLACEHOLDER_SUFFIXES)
    )

    if is_placeholder:
        print(f"\n  ERROR: {env_var} is not set or is still a placeholder value.")
        print("  Steps to fix:")
        print("    1. Copy .env.example to .env  (if you haven't already)")
        print(f"    2. Set {env_var}=<your real key>")
        print(f"    3. Get a key at: {_KEY_URLS[provider]}")
        sys.exit(1)

    return key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_llm() -> "BaseChatModel":
    """Create and return an LLM instance based on environment configuration.

    Reads the following env vars:
      LLM_PROVIDER    — anthropic | openai | google  (default: anthropic)
      LLM_MODEL       — model name override           (default: provider-specific)
      LLM_TEMPERATURE — sampling temperature          (default: 0)

    Returns:
        A LangChain ``BaseChatModel`` ready for use with LangGraph.

    Raises:
        SystemExit(1) with a clear error message if:
          - ``LLM_PROVIDER`` is not supported
          - The required API key is missing or is a placeholder
          - The required ``langchain-*`` package is not installed
    """
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower().strip()
    model_name = os.environ.get("LLM_MODEL", "").strip() or _DEFAULT_MODELS.get(provider, "")
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0"))

    if provider not in _DEFAULT_MODELS:
        print(f"\n  ERROR: Unsupported LLM_PROVIDER={provider!r}")
        print(f"  Supported providers: {', '.join(_DEFAULT_MODELS)}")
        sys.exit(1)

    api_key = _validate_api_key(provider)

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            print(f"  ERROR: '{_INSTALL_PACKAGES[provider]}' is not installed.")
            print(f"  Run:  pip install {_INSTALL_PACKAGES[provider]}")
            sys.exit(1)
        return ChatAnthropic(  # type: ignore[return-value]
            model=model_name, temperature=temperature, api_key=api_key
        )

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            print(f"  ERROR: '{_INSTALL_PACKAGES[provider]}' is not installed.")
            print(f"  Run:  pip install {_INSTALL_PACKAGES[provider]}")
            sys.exit(1)
        return ChatOpenAI(  # type: ignore[return-value]
            model=model_name, temperature=temperature, api_key=api_key
        )

    if provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            print(f"  ERROR: '{_INSTALL_PACKAGES[provider]}' is not installed.")
            print(f"  Run:  pip install {_INSTALL_PACKAGES[provider]}")
            sys.exit(1)
        return ChatGoogleGenerativeAI(  # type: ignore[return-value]
            model=model_name, temperature=temperature, google_api_key=api_key
        )

    # Unreachable — guarded above, but satisfies type checkers
    print(f"\n  ERROR: Unhandled provider: {provider!r}")  # pragma: no cover
    sys.exit(1)  # pragma: no cover


def print_provider_info() -> None:
    """Print the active LLM provider and model without revealing the key value."""
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower().strip()
    model = os.environ.get("LLM_MODEL", "").strip() or _DEFAULT_MODELS.get(provider, "unknown")
    env_var = _API_KEY_VARS.get(provider, "UNKNOWN_API_KEY")
    key_present = bool(os.environ.get(env_var, "").strip())
    print(f"  LLM provider : {provider}")
    print(f"  Model        : {model}")
    print(f"  API key env  : {env_var} ({'✓ set' if key_present else '✗ NOT SET'})")
