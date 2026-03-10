# SPDX-License-Identifier: MIT
"""Authentication framework for API2MCP.

Provides pluggable auth providers that inject credentials into outgoing
HTTP requests made by the MCP runtime.
"""

from api2mcp.auth.base import AuthProvider, RequestContext
from api2mcp.auth.factory import build_auth_provider
from api2mcp.auth.providers.api_key import APIKeyProvider
from api2mcp.auth.providers.basic import BasicAuthProvider
from api2mcp.auth.providers.bearer import BearerTokenProvider
from api2mcp.auth.providers.custom import CustomAuthProvider
from api2mcp.auth.providers.oauth2 import OAuth2Config, OAuth2Provider
from api2mcp.auth.token_store import TokenEntry, TokenStore

__all__ = [
    # Base
    "AuthProvider",
    "RequestContext",
    # Providers
    "APIKeyProvider",
    "BasicAuthProvider",
    "BearerTokenProvider",
    "CustomAuthProvider",
    "OAuth2Config",
    "OAuth2Provider",
    # Token store
    "TokenEntry",
    "TokenStore",
    # Factory
    "build_auth_provider",
]
