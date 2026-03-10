# SPDX-License-Identifier: MIT
"""Secret management for API2MCP.

Provides pluggable backends for storing and retrieving API credentials,
with automatic log masking to prevent accidental secret exposure.
"""

from api2mcp.secrets.base import SecretProvider
from api2mcp.secrets.factory import (
    FallbackChainProvider,
    build_fallback_chain,
    build_secret_provider,
)
from api2mcp.secrets.masking import (
    MaskingFilter,
    SecretRegistry,
    install_global_mask_filter,
    mask,
)
from api2mcp.secrets.providers.aws import AWSSecretsManagerProvider
from api2mcp.secrets.providers.encrypted_file import EncryptedFileProvider
from api2mcp.secrets.providers.env import EnvironmentProvider
from api2mcp.secrets.providers.keychain import KeychainProvider
from api2mcp.secrets.providers.vault import VaultProvider

__all__ = [
    # Base
    "SecretProvider",
    # Providers
    "AWSSecretsManagerProvider",
    "EncryptedFileProvider",
    "EnvironmentProvider",
    "KeychainProvider",
    "VaultProvider",
    # Factory
    "FallbackChainProvider",
    "build_fallback_chain",
    "build_secret_provider",
    # Masking
    "MaskingFilter",
    "SecretRegistry",
    "install_global_mask_filter",
    "mask",
]
