# Configuration Reference

API2MCP reads configuration from `.api2mcp.yaml` (or `.api2mcp.yml`) in the
current directory or any parent directory. CLI flags always take precedence.

---

## File Discovery

API2MCP searches for a config file starting at the current working directory
and walking up to the filesystem root. The first file found wins.

```
./
├── .api2mcp.yaml      ← found here
├── src/
│   └── ...
```

---

## Top-Level Keys

```yaml
output: ./generated        # Output directory for generated files
host: 127.0.0.1            # MCP server bind address
port: 8000                 # MCP server port
transport: http            # Transport: "http" or "stdio"
log_level: info            # Logging level
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `output` | `string` | `generated` | Output directory for `api2mcp generate` |
| `host` | `string` | `127.0.0.1` | Bind address for `api2mcp serve` |
| `port` | `integer` | `8000` | Port for `api2mcp serve` |
| `transport` | `"http"` \| `"stdio"` | `http` | MCP transport protocol |
| `log_level` | `string` | `info` | Log level: `debug`, `info`, `warning`, `error`, `critical` |

---

## Environment Variable Interpolation

Use `${VAR}` syntax to read values from the environment:

```yaml
auth:
  type: api_key
  key_env: ${MY_API_KEY_VAR}    # reads MY_API_KEY_VAR from environment
host: ${MCP_HOST:-127.0.0.1}   # with default fallback
```

---

## Auth Configuration

### API Key

```yaml
auth:
  type: api_key
  location: header         # "header", "query", or "cookie"
  name: X-API-Key          # header/param name
  key_env: MY_API_KEY      # environment variable containing the key
```

### Bearer Token

```yaml
auth:
  type: bearer
  token_env: MY_BEARER_TOKEN
```

### HTTP Basic

```yaml
auth:
  type: basic
  username_env: API_USERNAME
  password_env: API_PASSWORD
```

### OAuth 2.0

```yaml
auth:
  type: oauth2
  flow: client_credentials    # "client_credentials" | "authorization_code"
  token_url: https://auth.example.com/token
  client_id_env: OAUTH_CLIENT_ID
  client_secret_env: OAUTH_CLIENT_SECRET
  scopes: [read, write]
```

---

## Secrets Configuration

```yaml
secrets:
  backend: env              # "env" | "aws" | "vault" | "keychain" | "encrypted_file"

  # AWS Secrets Manager
  region: us-east-1
  secret_id: my-app/api-key

  # HashiCorp Vault
  addr: https://vault.example.com
  path: secret/data/my-secret
  token_env: VAULT_TOKEN

  # Encrypted file
  file: ~/.api2mcp/secrets.enc
  key_env: ENCRYPTION_KEY
```

---

## Rate Limiting

```yaml
rate_limit:
  strategy: sliding_window    # "fixed_window" | "sliding_window" | "token_bucket"
  requests_per_second: 10
  requests_per_minute: 100
  requests_per_hour: 1000
  retry_after: true
```

---

## Input Validation

```yaml
validation:
  max_string_length: 10000
  max_array_items: 1000
  max_object_depth: 10
  sanitize_strings: true
```

---

## Caching

```yaml
cache:
  backend: memory             # "memory" | "redis" | "disk"
  ttl_seconds: 300
  max_size: 1000

  # Redis
  redis_url: redis://localhost:6379/0
```

---

## Connection Pooling

```yaml
pool:
  max_connections: 100
  keepalive_expiry: 30
  connect_timeout: 10
  read_timeout: 30
```

---

## Complete Example

```yaml
output: ./generated
host: 0.0.0.0
port: 8000
transport: http
log_level: info

auth:
  type: bearer
  token_env: GITHUB_TOKEN

rate_limit:
  strategy: sliding_window
  requests_per_minute: 60
  retry_after: true

validation:
  max_string_length: 50000
  sanitize_strings: true

cache:
  backend: memory
  ttl_seconds: 60
```

---

## VS Code Support

API2MCP ships a JSON Schema for `.api2mcp.yaml` at `schemas/api2mcp-config.schema.json`.
Install the [Red Hat YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)
and the schema is applied automatically via `.vscode/settings.json`.

You get autocomplete and inline validation:

```yaml
transport: http  # ← autocomplete shows "http" and "stdio"
port: 99999      # ← validation error: must be ≤ 65535
```
