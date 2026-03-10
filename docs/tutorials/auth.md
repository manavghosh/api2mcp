# Tutorial: Authentication Setup

API2MCP supports all major authentication patterns. This tutorial covers
two distinct authentication concerns:

1. **Downloading a protected spec** — getting the OpenAPI/Swagger file when
   it sits behind an auth wall (covered first, because it comes before generation)
2. **Runtime API auth** — configuring credentials so the running MCP server
   can call the API on every tool invocation

---

## Authentication Methods (Runtime)

| Method | Config key | Use when |
|--------|-----------|----------|
| API Key (header/query) | `api_key` | Simple single-key APIs |
| HTTP Bearer | `bearer` | JWT / token-based APIs |
| HTTP Basic | `basic` | Legacy APIs |
| OAuth 2.0 Client Credentials | `oauth2` | Stripe, Salesforce, B2B machine-to-machine |
| OAuth 2.0 Authorization Code | `oauth2` | GitHub, Google, Microsoft (user-delegated) |

---

## 0. Before You Generate — Downloading a Protected Spec

`api2mcp generate` needs the spec file before it can do anything. Most APIs
publish their OpenAPI spec publicly, but some protect it behind the same auth
wall as the API itself.

> **Important:** Spec download auth and runtime API auth are completely
> separate. You only need to handle spec download auth once. Runtime auth
> is configured in `.api2mcp.yaml` and handled automatically on every call.

### Public spec — no auth needed

```bash
api2mcp generate https://api.example.com/openapi.json --output ./my-server
```

### Spec behind a Bearer token

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/openapi.json -o spec.json

api2mcp generate spec.json --output ./my-server
```

### Spec behind an API key

```bash
# In a header
curl -s -H "X-API-Key: $API_KEY" \
  https://api.example.com/openapi.json -o spec.json

# Or as a query parameter
curl -s "https://api.example.com/openapi.json?api_key=$API_KEY" -o spec.json

api2mcp generate spec.json --output ./my-server
```

### Spec behind OAuth 2.0 Client Credentials

```bash
# Step 1: Get an access token
TOKEN=$(curl -s -X POST "$TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$OAUTH_CLIENT_ID" \
  -d "client_secret=$OAUTH_CLIENT_SECRET" \
  -d "scope=read:api" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Step 2: Download the spec
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/openapi.json -o spec.json

# Step 3: Generate
api2mcp generate spec.json --output ./my-server
```

### Spec behind OAuth 2.0 Authorization Code (user login)

```bash
# Use the wizard — it opens a browser tab, handles the redirect,
# captures the token, and stores it in the OS keychain automatically
api2mcp wizard --spec https://api.example.com/openapi.json

# Or if you already have a user token from a prior login
curl -s -H "Authorization: Bearer $USER_TOKEN" \
  https://api.example.com/openapi.json -o spec.json

api2mcp generate spec.json --output ./my-server
```

### Spec on an internal / VPN-only network

```bash
# 1. Connect to VPN
# 2. Download the spec
curl -s -H "Authorization: Bearer $TOKEN" \
  https://internal.corp.example.com/openapi.json -o spec.json

# 3. Generate locally — the ./my-server directory is self-contained
api2mcp generate spec.json --output ./my-server

# VPN is only needed again at runtime, when tools make calls to the real API
```

### Always validate after downloading

A common failure is getting back an HTML login page instead of a spec because
the credentials were wrong or expired. Catch this before generating:

```bash
api2mcp validate spec.json
```

If validation fails with a parse error, the downloaded file is not a valid
OpenAPI spec. Check your credentials and re-download.

---

## 1. API Key Authentication

### Spec detection

API2MCP automatically detects API key auth from the OpenAPI spec:

```yaml
components:
  securitySchemes:
    ApiKeyAuth:
      type: apiKey
      in: header
      name: X-API-Key
security:
  - ApiKeyAuth: []
```

### Runtime configuration

Set the key via environment variable or `.api2mcp.yaml`:

```bash
export API2MCP_API_KEY="sk-your-key-here"
```

```yaml
# .api2mcp.yaml
auth:
  type: api_key
  key_env: API2MCP_API_KEY   # reads from environment
  location: header
  name: X-API-Key
```

---

## 2. Bearer Token Authentication

```yaml
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
```

```yaml
# .api2mcp.yaml
auth:
  type: bearer
  token_env: MY_API_TOKEN
```

---

## 3. OAuth 2.0

### Client credentials flow

```yaml
# .api2mcp.yaml
auth:
  type: oauth2
  flow: client_credentials
  token_url: https://auth.example.com/oauth/token
  client_id_env: OAUTH_CLIENT_ID
  client_secret_env: OAUTH_CLIENT_SECRET
  scopes:
    - read:api
    - write:api
```

### Authorization code flow

```yaml
auth:
  type: oauth2
  flow: authorization_code
  authorization_url: https://auth.example.com/oauth/authorize
  token_url: https://auth.example.com/oauth/token
  client_id_env: OAUTH_CLIENT_ID
  client_secret_env: OAUTH_CLIENT_SECRET
  redirect_uri: http://localhost:8000/callback
```

---

## 4. Secret Management

API2MCP integrates with multiple secret backends to avoid hardcoding credentials.

### Environment variables (default)

```bash
export MY_API_KEY="secret"
```

```yaml
auth:
  type: api_key
  key_env: MY_API_KEY
```

### AWS Secrets Manager

```bash
pip install "api2mcp[aws]"
```

```yaml
secrets:
  backend: aws
  region: us-east-1
  secret_id: my-app/api-key
```

### HashiCorp Vault

```bash
pip install "api2mcp[vault]"
```

```yaml
secrets:
  backend: vault
  addr: https://vault.example.com
  path: secret/data/api-key
  token_env: VAULT_TOKEN
```

### System keychain

```yaml
secrets:
  backend: keychain
  service: api2mcp
  username: default
```

---

## 5. Input Validation

API2MCP validates and sanitises all incoming tool arguments before they are
forwarded to the upstream API.

```python
# Validation is automatic — no extra configuration needed.
# All parameters are validated against the OpenAPI schema.
```

To configure custom validation:

```yaml
validation:
  max_string_length: 10000
  max_array_items: 1000
  sanitize_strings: true   # strip control characters
```

---

## 6. Rate Limiting

Protect upstream APIs from overload:

```yaml
rate_limit:
  strategy: sliding_window
  requests_per_second: 10
  requests_per_minute: 100
  retry_after: true   # send Retry-After header on 429
```

---

## Next Steps

- [LangGraph Orchestration](orchestration.md) — use authenticated servers in workflows
- [Configuration Reference](../reference/config.md) — full auth config options
