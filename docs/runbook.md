# API2MCP Runbook — Use Cases & Implementation Guide

This runbook is the operational reference for every use case that API2MCP
supports. Each section describes the problem, when to apply it, the exact
configuration and commands, and working code samples.

**Contents**

1. [Basic API Conversion](#1-basic-api-conversion)
   - 1.1 [OpenAPI 3.x → MCP Server](#11-openapi-3x--mcp-server)
   - 1.2 [GraphQL Schema → MCP Server](#12-graphql-schema--mcp-server)
   - 1.3 [Swagger 2.0 Legacy API → MCP Server](#13-swagger-20-legacy-api--mcp-server)
   - 1.4 [Postman Collection → MCP Server](#14-postman-collection--mcp-server)
   - 1.5 [Auto-Detect API Format](#15-auto-detect-api-format)
- [Before You Generate — Downloading a Protected Spec](#before-you-generate--downloading-a-protected-spec)
   - [Scenario A — Public spec URL](#scenario-a--public-spec-url-no-auth-required)
   - [Scenario B — Bearer token or API key](#scenario-b--spec-behind-a-bearer-token-or-api-key)
   - [Scenario C — OAuth 2.0 Client Credentials](#scenario-c--spec-behind-oauth-20-client-credentials)
   - [Scenario D — OAuth 2.0 Authorization Code](#scenario-d--spec-behind-oauth-20-authorization-code-user-login)
   - [Scenario E — HTTP Basic Auth](#scenario-e--spec-behind-http-basic-auth)
   - [Scenario F — Internal / VPN-only spec](#scenario-f--internal--vpn-only-spec)
2. [Authentication Patterns](#2-authentication-patterns)
   - 2.1 [API Key (Header / Query / Cookie)](#21-api-key-header--query--cookie)
   - 2.2 [Bearer Token](#22-bearer-token)
   - 2.3 [HTTP Basic Auth](#23-http-basic-auth)
   - 2.4 [OAuth 2.0 — Client Credentials](#24-oauth-20--client-credentials)
   - 2.5 [OAuth 2.0 — Authorization Code](#25-oauth-20--authorization-code)
3. [Secret Management Backends](#3-secret-management-backends)
   - 3.1 [Environment Variables (Default)](#31-environment-variables-default)
   - 3.2 [AWS Secrets Manager](#32-aws-secrets-manager)
   - 3.3 [HashiCorp Vault](#33-hashicorp-vault)
   - 3.4 [OS Keychain](#34-os-keychain)
   - 3.5 [Encrypted File](#35-encrypted-file)
4. [Reliability & Performance](#4-reliability--performance)
   - 4.1 [Rate Limiting](#41-rate-limiting)
   - 4.2 [Response Caching](#42-response-caching)
   - 4.3 [Circuit Breaker](#43-circuit-breaker)
   - 4.4 [Connection Pooling](#44-connection-pooling)
   - 4.5 [Input Validation & Sanitization](#45-input-validation--sanitization)
5. [Development Workflow](#5-development-workflow)
   - 5.1 [Hot Reload Dev Server](#51-hot-reload-dev-server)
   - 5.2 [Interactive Wizard Setup](#52-interactive-wizard-setup)
   - 5.3 [VS Code Integration](#53-vs-code-integration)
   - 5.4 [Validating a Spec Without Generating](#54-validating-a-spec-without-generating)
   - 5.5 [Testing MCP Servers with MCPTestClient](#55-testing-mcp-servers-with-mcptestclient)
   - 5.6 [Snapshot Testing for Regression Detection](#56-snapshot-testing-for-regression-detection)
6. [Deployment Scenarios](#6-deployment-scenarios)
   - 6.1 [Local Development (stdio Transport)](#61-local-development-stdio-transport)
   - 6.2 [Network Server (HTTP Transport)](#62-network-server-http-transport)
   - 6.3 [Docker Container Deployment](#63-docker-container-deployment)
   - 6.4 [CI/CD Pipeline Integration](#64-cicd-pipeline-integration)
   - 6.5 [Multi-Environment Config (dev / staging / prod)](#65-multi-environment-config-dev--staging--prod)
7. [LangGraph Orchestration](#7-langgraph-orchestration)
   - 7.1 [Reactive Agent — Single API](#71-reactive-agent--single-api)
   - 7.2 [Planner Graph — Sequential Workflow](#72-planner-graph--sequential-workflow)
   - 7.3 [Planner Graph — Parallel Execution](#73-planner-graph--parallel-execution)
   - 7.4 [Multi-API Orchestration](#74-multi-api-orchestration)
   - 7.5 [Conversational Agent with Memory](#75-conversational-agent-with-memory)
   - 7.6 [Human-in-the-Loop Approval](#76-human-in-the-loop-approval)
   - 7.7 [Streaming Real-Time Output](#77-streaming-real-time-output)
   - 7.8 [Checkpointed & Resumable Workflows](#78-checkpointed--resumable-workflows)
8. [Real-World Integration Scenarios](#8-real-world-integration-scenarios)
   - 8.1 [GitHub DevOps Automation](#81-github-devops-automation)
   - 8.2 [Stripe Payment Processing](#82-stripe-payment-processing)
   - 8.3 [GitHub + Stripe Billing Reconciliation](#83-github--stripe-billing-reconciliation)
   - 8.4 [GitHub + Slack Notifications](#84-github--slack-notifications)
   - 8.5 [Internal Enterprise API Gateway](#85-internal-enterprise-api-gateway)
   - 8.6 [AWS Cloud Infrastructure Management](#86-aws-cloud-infrastructure-management)
   - 8.7 [CRM Automation (Salesforce + Email)](#87-crm-automation-salesforce--email)
   - 8.8 [Database API Proxy](#88-database-api-proxy)
9. [Extending API2MCP](#9-extending-api2mcp)
   - 9.1 [Install a Community Template](#91-install-a-community-template)
   - 9.2 [Build and Publish a Template](#92-build-and-publish-a-template)
   - 9.3 [Write a Custom Plugin](#93-write-a-custom-plugin)
   - 9.4 [Write a Custom Parser](#94-write-a-custom-parser)
10. [Observability & Troubleshooting](#10-observability--troubleshooting)
    - 10.1 [Structured Logging](#101-structured-logging)
    - 10.2 [Workflow Streaming Observability](#102-workflow-streaming-observability)
    - 10.3 [Common Errors and Fixes](#103-common-errors-and-fixes)

---

## 1. Basic API Conversion

### 1.1 OpenAPI 3.x → MCP Server

**Problem:** You have a REST API described by an OpenAPI 3.x YAML or JSON file
and want to expose its endpoints as MCP tools that any MCP-compatible AI agent
can call.

**When to use:** Any modern REST API that ships an OpenAPI 3.x spec — GitHub,
Stripe, Twilio, your own microservices, etc.

**Steps:**

```bash
# 1. Validate the spec first
api2mcp validate openapi.yaml

# 2. Generate the MCP server
api2mcp generate openapi.yaml --output ./my-server

# 3. Start the server
api2mcp serve ./my-server --port 8000
```

**Generated layout:**

```
my-server/
├── server.py          # Runnable MCP server
├── spec.yaml          # Copy of the processed IR
├── tools/             # One module per endpoint group
└── .api2mcp.yaml      # Inherited config
```

**Configuration (`.api2mcp.yaml`):**

```yaml
output: ./my-server
host: 127.0.0.1
port: 8000
transport: http
log_level: info
```

**Override the base URL (useful for staging/prod):**

```bash
api2mcp generate openapi.yaml \
  --output ./my-server \
  --base-url https://staging.api.example.com/v2
```

---

### 1.2 GraphQL Schema → MCP Server

**Problem:** Your API exposes a GraphQL endpoint (`.graphql` or `.sdl` file)
instead of REST, and you want each query and mutation available as an MCP tool.

**When to use:** GraphQL APIs such as GitHub's GraphQL API v4, Shopify Storefront
API, internal data-mesh services.

**Prerequisites:**

```bash
pip install "api2mcp[graphql]"
```

**Steps:**

```bash
# Validate
api2mcp validate schema.graphql

# Generate (format auto-detected from extension)
api2mcp generate schema.graphql --output ./graphql-server

# Serve
api2mcp serve ./graphql-server --port 8001
```

**Force GraphQL format if the file extension is ambiguous:**

```bash
api2mcp generate api.json --format graphql --output ./graphql-server
```

**What gets created:** Every Query field becomes a read-only MCP tool; every
Mutation field becomes a write MCP tool. Subscriptions are skipped.

---

### 1.3 Swagger 2.0 Legacy API → MCP Server

**Problem:** You have an older API spec in Swagger 2.0 format (often exported
from legacy tools, IBM API Connect, or AWS API Gateway) and want to modernise
it into an MCP server without manually upgrading the spec.

**When to use:** Any `swagger: "2.0"` document.

**Steps:**

```bash
# API2MCP detects "swagger: 2.0" automatically
api2mcp validate swagger.yaml
api2mcp generate swagger.yaml --output ./legacy-server

api2mcp serve ./legacy-server
```

**Explicit format flag:**

```bash
api2mcp generate swagger.yaml --format swagger --output ./legacy-server
```

**Note:** The Swagger parser internally upgrades the spec to the internal
Intermediate Representation (IR), so the resulting MCP server behaves
identically to one generated from OpenAPI 3.x.

---

### 1.4 Postman Collection → MCP Server

**Problem:** Your team's API documentation lives in a Postman Collection
(`collection.json`), not a formal spec file. You want to convert it directly
without creating an OpenAPI file first.

**When to use:** Teams that use Postman as the primary API documentation tool,
rapid prototyping, private APIs without public specs.

**Steps:**

```bash
# Export collection from Postman as Collection v2.1 JSON
api2mcp validate collection.json
api2mcp generate collection.json --output ./postman-server
api2mcp serve ./postman-server
```

**Explicit format flag:**

```bash
api2mcp generate collection.json --format postman --output ./postman-server
```

**Tip:** Postman environment variables in the collection (e.g. `{{baseUrl}}`)
are resolved using the `--base-url` flag:

```bash
api2mcp generate collection.json \
  --base-url https://api.example.com \
  --output ./postman-server
```

---

### 1.5 Auto-Detect API Format

**Problem:** You receive a spec file from a third party and are unsure which
format it uses (OpenAPI 3, Swagger 2, GraphQL, Postman).

**When to use:** Always — API2MCP auto-detects by default. This use case
documents how to rely on and verify that auto-detection.

**How detection works:**

| Signal | Format |
|--------|--------|
| `openapi: 3.x.y` in YAML/JSON | OpenAPI 3.x |
| `swagger: "2.0"` in YAML/JSON | Swagger 2.0 |
| `info.collection` in JSON | Postman Collection |
| `type Query {` or `.graphql` extension | GraphQL SDL |

**Steps:**

```bash
# Validate — the parser type is reported in the output
api2mcp --log-level info validate unknown-spec.yaml

# Generate with auto-detection
api2mcp generate unknown-spec.yaml --output ./auto-server
```

**Override if auto-detection is wrong:**

```bash
api2mcp generate ambiguous.json --format openapi --output ./server
```

---

## Before You Generate — Downloading a Protected Spec

`api2mcp generate` reads a spec file (local path or public URL). If the spec
itself is publicly accessible, no special handling is needed. However, some
enterprise APIs and internal services protect their OpenAPI spec behind
authentication — the same auth wall as the API endpoints themselves.

This section covers how to obtain the spec file in every scenario before
running `api2mcp generate`.

> **Key distinction:** Authentication for *downloading the spec* and
> authentication for *calling the API at runtime* are completely independent.
> This section covers only spec download. Runtime auth is covered in
> [Section 2 — Authentication Patterns](#2-authentication-patterns).

---

### Scenario A — Public spec URL (no auth required)

Most APIs publish their spec publicly. Pass the URL directly:

```bash
api2mcp generate https://petstore3.swagger.io/api/v3/openapi.json --output ./petstore
api2mcp generate https://api.example.com/openapi.yaml --output ./my-server
```

No credentials needed. API2MCP downloads and parses in one step.

---

### Scenario B — Spec behind a Bearer token or API key

Some APIs require a token even to read the spec. Download it manually first,
then generate from the local file.

**Bearer token:**

```bash
curl -s \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  https://api.example.com/openapi.json \
  -o spec.json

api2mcp generate spec.json --output ./my-server
```

**API key in header:**

```bash
curl -s \
  -H "X-API-Key: $API_KEY" \
  https://api.example.com/openapi.json \
  -o spec.json

api2mcp generate spec.json --output ./my-server
```

**API key in query parameter:**

```bash
curl -s \
  "https://api.example.com/openapi.json?api_key=$API_KEY" \
  -o spec.json

api2mcp generate spec.json --output ./my-server
```

---

### Scenario C — Spec behind OAuth 2.0 Client Credentials

Use your OAuth client credentials to fetch a token first, then use that token
to download the spec.

```bash
# Step 1: Exchange client credentials for an access token
TOKEN=$(curl -s -X POST "$TOKEN_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$OAUTH_CLIENT_ID" \
  -d "client_secret=$OAUTH_CLIENT_SECRET" \
  -d "scope=read:api" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Step 2: Download the spec using the token
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  https://api.example.com/openapi.json \
  -o spec.json

# Step 3: Generate the MCP server from the local file
api2mcp generate spec.json --output ./my-server
```

**Windows PowerShell equivalent:**

```powershell
# Step 1: Fetch token
$body = @{
    grant_type    = "client_credentials"
    client_id     = $env:OAUTH_CLIENT_ID
    client_secret = $env:OAUTH_CLIENT_SECRET
    scope         = "read:api"
}
$response = Invoke-RestMethod -Uri $env:TOKEN_URL -Method Post -Body $body
$token = $response.access_token

# Step 2: Download spec
Invoke-WebRequest `
    -Uri "https://api.example.com/openapi.json" `
    -Headers @{ Authorization = "Bearer $token" } `
    -OutFile spec.json

# Step 3: Generate
api2mcp generate spec.json --output ./my-server
```

---

### Scenario D — Spec behind OAuth 2.0 Authorization Code (user login)

For APIs where a human must log in via a browser (GitHub OAuth Apps, Google,
Microsoft), obtain the token interactively first.

```bash
# Option 1: Use the api2mcp wizard — handles the browser flow automatically
# Run once to authenticate; the wizard saves the token to the OS keychain
api2mcp wizard --spec https://api.example.com/openapi.json

# Option 2: If you already have a user access token from a prior login
curl -s \
  -H "Authorization: Bearer $USER_ACCESS_TOKEN" \
  https://api.example.com/openapi.json \
  -o spec.json

api2mcp generate spec.json --output ./my-server
```

---

### Scenario E — Spec behind HTTP Basic Auth

```bash
curl -s \
  -u "$USERNAME:$PASSWORD" \
  https://api.example.com/openapi.json \
  -o spec.json

api2mcp generate spec.json --output ./my-server
```

---

### Scenario F — Internal / VPN-only spec

If the spec is only reachable from inside a corporate network or VPN:

1. Connect to the VPN
2. Download the spec with any of the curl commands above
3. Copy the local `spec.json` to your working machine
4. Run `api2mcp generate spec.json --output ./my-server` locally

The generated `./my-server` directory contains a copy of the spec (`spec.yaml`)
and does not need VPN access after generation. Only at runtime, when tools are
called and the MCP server proxies requests to the real API, does VPN access
need to be restored.

---

### After downloading — verify the spec is valid

Before generating, confirm the downloaded file is a valid OpenAPI spec and
not an HTML error page (a common failure mode when auth is rejected):

```bash
api2mcp validate spec.json
```

If validation fails with a parse error, the likely cause is that the server
returned an HTML login page or a JSON error body instead of the spec. Check
that your credentials are correct and that the token has not expired.

---

## 2. Authentication Patterns

### 2.1 API Key (Header / Query / Cookie)

**Problem:** The target API requires a secret key passed in a header (e.g.
`X-API-Key`), a query parameter (e.g. `?api_key=...`), or a cookie.

**When to use:** OpenWeatherMap, many SaaS data APIs, most internal corporate
APIs.

**`.api2mcp.yaml`:**

```yaml
auth:
  type: api_key
  location: header          # "header" | "query" | "cookie"
  name: X-API-Key           # header or parameter name
  key_env: OPENWEATHER_KEY  # env var that holds the secret
```

**Set the secret:**

```bash
export OPENWEATHER_KEY="your-secret-key"
api2mcp serve ./weather-server
```

**Query parameter variant:**

```yaml
auth:
  type: api_key
  location: query
  name: api_key
  key_env: WEATHER_API_KEY
```

**Cookie variant:**

```yaml
auth:
  type: api_key
  location: cookie
  name: session_token
  key_env: SESSION_TOKEN
```

---

### 2.2 Bearer Token

**Problem:** The API uses HTTP Bearer token authentication (JWT or opaque token).

**When to use:** GitHub REST API, Linear, Notion, most modern SaaS APIs.

**`.api2mcp.yaml`:**

```yaml
auth:
  type: bearer
  token_env: GITHUB_TOKEN
```

**Set the secret:**

```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
api2mcp serve ./github-server
```

**Full example with rate limiting:**

```yaml
auth:
  type: bearer
  token_env: GITHUB_TOKEN

rate_limit:
  strategy: sliding_window
  requests_per_minute: 60
  retry_after: true
```

---

### 2.3 HTTP Basic Auth

**Problem:** The target API uses HTTP Basic authentication (username + password).

**When to use:** Legacy APIs, JIRA on-premise, Jenkins, Nexus repository, many
internal services.

**`.api2mcp.yaml`:**

```yaml
auth:
  type: basic
  username_env: JIRA_USERNAME
  password_env: JIRA_API_TOKEN
```

**Set the secrets:**

```bash
export JIRA_USERNAME="alice@example.com"
export JIRA_API_TOKEN="your-jira-api-token"
api2mcp serve ./jira-server
```

---

### 2.4 OAuth 2.0 — Client Credentials

**Problem:** The API uses OAuth 2.0 with the client credentials grant, meaning
you authenticate server-to-server with a client ID and secret.

**When to use:** Stripe, Salesforce, Auth0 machine-to-machine, most B2B APIs,
Google service accounts.

**`.api2mcp.yaml`:**

```yaml
auth:
  type: oauth2
  flow: client_credentials
  token_url: https://accounts.example.com/oauth/token
  client_id_env: OAUTH_CLIENT_ID
  client_secret_env: OAUTH_CLIENT_SECRET
  scopes: [read:data, write:data]
```

**Set the secrets:**

```bash
export OAUTH_CLIENT_ID="your-client-id"
export OAUTH_CLIENT_SECRET="your-client-secret"
api2mcp serve ./api-server
```

API2MCP automatically requests a new access token when the current one expires,
so you never need to manage token refresh manually.

---

### 2.5 OAuth 2.0 — Authorization Code

**Problem:** The API requires a user to log in via a browser (authorization code
grant), such as GitHub OAuth Apps or Google APIs with user-delegated access.

**When to use:** APIs where you need to act on behalf of a specific user,
not as a machine account.

**`.api2mcp.yaml`:**

```yaml
auth:
  type: oauth2
  flow: authorization_code
  token_url: https://github.com/login/oauth/access_token
  authorization_url: https://github.com/login/oauth/authorize
  client_id_env: GITHUB_CLIENT_ID
  client_secret_env: GITHUB_CLIENT_SECRET
  scopes: [repo, read:user]
  redirect_uri: http://localhost:8080/callback
```

**Obtain and store the initial token:**

```bash
# Run the wizard — it opens the browser for the OAuth flow automatically
api2mcp wizard --spec github-openapi.yaml
```

The wizard guides you through the browser redirect, captures the authorization
code, exchanges it for an access token, and stores it securely in the OS
keychain.

---

## 3. Secret Management Backends

### 3.1 Environment Variables (Default)

**Problem:** You need a simple, portable way to inject secrets without any
external infrastructure.

**When to use:** Local development, CI/CD pipelines, Docker environments,
any context where secrets are already injected as environment variables.

**`.api2mcp.yaml`:**

```yaml
secrets:
  backend: env

auth:
  type: bearer
  token_env: MY_SERVICE_TOKEN   # just reference the env var name
```

**Using the `${VAR}` interpolation syntax anywhere in the config:**

```yaml
host: ${MCP_HOST:-127.0.0.1}   # with fallback default
port: ${MCP_PORT:-8000}
auth:
  type: api_key
  key_env: ${API_KEY_VAR_NAME}
```

---

### 3.2 AWS Secrets Manager

**Problem:** Your organisation stores all secrets in AWS Secrets Manager and
you want API2MCP to pull them at startup without ever touching environment
variables.

**When to use:** AWS-hosted infrastructure, compliance-regulated environments,
teams with centralised secret rotation policies.

**Prerequisites:**

```bash
pip install "api2mcp[aws]"
```

**`.api2mcp.yaml`:**

```yaml
secrets:
  backend: aws
  region: us-east-1
  secret_id: myapp/production/github-token   # ARN or name

auth:
  type: bearer
  token_env: GITHUB_TOKEN   # key inside the Secrets Manager secret JSON
```

**IAM permissions required:**

```json
{
  "Effect": "Allow",
  "Action": ["secretsmanager:GetSecretValue"],
  "Resource": "arn:aws:secretsmanager:us-east-1:123456789:secret:myapp/*"
}
```

The AWS SDK uses the standard credential chain (instance role, `~/.aws/credentials`,
environment variables), so no additional configuration is needed in most cases.

---

### 3.3 HashiCorp Vault

**Problem:** Secrets are stored in a HashiCorp Vault cluster and should be
fetched at runtime rather than baked into the environment.

**When to use:** On-premise infrastructure, enterprise environments with
Vault already in use, dynamic secret rotation requirements.

**Prerequisites:**

```bash
pip install "api2mcp[vault]"
```

**`.api2mcp.yaml`:**

```yaml
secrets:
  backend: vault
  addr: https://vault.example.com
  path: secret/data/github-token   # KV v2 path
  token_env: VAULT_TOKEN           # or use VAULT_ROLE_ID + VAULT_SECRET_ID for AppRole
```

**AppRole authentication (recommended for production):**

```yaml
secrets:
  backend: vault
  addr: https://vault.example.com
  path: secret/data/github-token
  role_id_env: VAULT_ROLE_ID
  secret_id_env: VAULT_SECRET_ID
```

---

### 3.4 OS Keychain

**Problem:** On a developer workstation you want to store secrets in the
operating system's secure credential store (macOS Keychain, Windows Credential
Manager, Linux Secret Service) instead of plain environment variables.

**When to use:** Developer laptops, single-user workstations, tools invoked
interactively.

**`.api2mcp.yaml`:**

```yaml
secrets:
  backend: keychain
  service: api2mcp
  username: github-token
```

**Store the secret once:**

```bash
# macOS / Linux / Windows — interactive prompt
api2mcp wizard --spec github.yaml
# The wizard detects the keychain backend and prompts you to store the secret.
```

**Or store programmatically:**

```python
import keyring
keyring.set_password("api2mcp", "github-token", "ghp_xxxxxxxxxxxx")
```

---

### 3.5 Encrypted File

**Problem:** You want to commit an encrypted secrets file to the repository so
secrets travel with the code but remain protected at rest.

**When to use:** Offline development environments, air-gapped networks, teams
that version-control secrets with symmetric encryption.

**`.api2mcp.yaml`:**

```yaml
secrets:
  backend: encrypted_file
  file: .secrets.enc        # path to the AES-256-GCM encrypted file
  key_env: SECRETS_KEY      # base64-encoded 32-byte AES key from the environment
```

**Encrypt secrets:**

```python
from api2mcp.secrets.encrypted_file import EncryptedFileBackend

backend = EncryptedFileBackend(file=".secrets.enc", key_env="SECRETS_KEY")
backend.write({"GITHUB_TOKEN": "ghp_xxxx", "STRIPE_KEY": "sk_live_xxxx"})
```

**Decrypt and read (happens automatically at startup):**

```bash
export SECRETS_KEY="base64-encoded-32-byte-key"
api2mcp serve ./github-server
```

---

## 4. Reliability & Performance

### 4.1 Rate Limiting

**Problem:** The target API imposes rate limits (e.g. GitHub allows 60
unauthenticated or 5 000 authenticated requests/hour). Exceeding the limit
returns `429 Too Many Requests`, breaking the AI workflow mid-execution.

**When to use:** Any API with documented rate limits — GitHub (5 000 req/hr),
Stripe (100 req/s), OpenAI (tier-dependent), all public APIs.

**`.api2mcp.yaml` — sliding window (recommended for most APIs):**

```yaml
rate_limit:
  strategy: sliding_window
  requests_per_minute: 60
  retry_after: true          # respect Retry-After header from the API
```

**Fixed window (matches APIs that reset on the clock minute):**

```yaml
rate_limit:
  strategy: fixed_window
  requests_per_hour: 5000
  retry_after: true
```

**Token bucket (smooth rate with burst allowance):**

```yaml
rate_limit:
  strategy: token_bucket
  requests_per_second: 10
  burst_size: 50             # allow short bursts up to 50 requests
  retry_after: true
```

**Behaviour:** When the limit is reached, API2MCP queues the request and
automatically retries it after the appropriate cooldown period. The AI agent
never sees a `429` — it just waits transparently.

---

### 4.2 Response Caching

**Problem:** The AI workflow calls the same read-only endpoint repeatedly (e.g.
`get_user` or `list_repositories`) causing redundant network round-trips and
burning through rate-limit quota.

**When to use:** Read-heavy workflows, endpoints whose data changes slowly
(user profiles, repository metadata, product catalogues).

**In-memory cache (single process, ephemeral):**

```yaml
cache:
  backend: memory
  ttl_seconds: 300     # cache for 5 minutes
  max_size: 1000       # max number of cached responses
```

**Redis cache (shared across processes / containers):**

```yaml
cache:
  backend: redis
  redis_url: redis://localhost:6379/0
  ttl_seconds: 600
```

**Disk cache (survives process restarts):**

```yaml
cache:
  backend: disk
  ttl_seconds: 3600
  max_size: 500
```

**Note:** Only `GET`-equivalent tool calls are cached. Mutation tools (POST,
PUT, DELETE) always bypass the cache.

---

### 4.3 Circuit Breaker

**Problem:** A downstream API is intermittently failing. Without a circuit
breaker, every tool call during an outage blocks and times out, causing the
entire AI workflow to hang.

**When to use:** Any production integration, especially with third-party APIs
that may have outages (Stripe, Twilio, external data providers).

**`.api2mcp.yaml`:**

```yaml
circuit_breaker:
  failure_threshold: 5       # open after 5 consecutive failures
  recovery_timeout: 30       # seconds before attempting half-open
  success_threshold: 2       # successes needed to close again
  timeout: 10                # per-request timeout in seconds
```

**States:**

| State | Behaviour |
|-------|-----------|
| **Closed** | Normal operation — requests pass through |
| **Open** | All calls fail immediately with `CircuitBreakerOpen` error |
| **Half-open** | One probe request allowed; success → closed, failure → open |

**Handling the open state in an orchestration workflow:**

```python
from api2mcp.circuitbreaker import CircuitBreakerOpen

try:
    result = await graph.run("Fetch Stripe customer details")
except CircuitBreakerOpen as exc:
    print(f"Stripe is currently unavailable: {exc}")
    # Fall back to cached data or notify the user
```

---

### 4.4 Connection Pooling

**Problem:** Under high load, creating a new HTTP connection for every tool
call is expensive. Connection setup latency adds up, and file-descriptor limits
can be exhausted.

**When to use:** Production deployments with more than ~10 concurrent AI agents,
batch-processing workflows, high-frequency tool call patterns.

**`.api2mcp.yaml`:**

```yaml
pool:
  max_connections: 100       # total connections across all hosts
  keepalive_expiry: 30       # seconds to keep an idle connection alive
  connect_timeout: 10        # seconds to wait for connection establishment
  read_timeout: 30           # seconds to wait for response data
```

**For very high throughput (e.g. internal data mesh):**

```yaml
pool:
  max_connections: 500
  keepalive_expiry: 60
  connect_timeout: 5
  read_timeout: 60
```

---

### 4.5 Input Validation & Sanitization

**Problem:** An AI model may produce tool inputs that are too long, deeply
nested, or contain injection payloads. Without validation, these reach the
upstream API and can cause unexpected behaviour or security issues.

**When to use:** Any production MCP server accessible to LLM-generated input
— which is effectively every deployment.

**`.api2mcp.yaml`:**

```yaml
validation:
  max_string_length: 10000      # reject strings longer than 10 000 chars
  max_array_items: 500          # reject arrays with more than 500 items
  max_object_depth: 10          # reject deeply nested objects
  sanitize_strings: true        # strip HTML/script tags, null bytes
```

**Strict mode (returns a validation error instead of sanitizing):**

```yaml
validation:
  max_string_length: 5000
  sanitize_strings: false       # reject rather than strip
  strict: true
```

**Custom validation in a plugin:**

```python
from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.hooks import PRE_GENERATE

class SQLInjectionGuard(BasePlugin):
    id = "sql-injection-guard"
    name = "SQL Injection Guard"
    version = "1.0.0"

    def setup(self, hook_manager):
        hook_manager.register_hook(PRE_GENERATE, self._check_inputs, plugin_id=self.id)

    def _check_inputs(self, *, api_spec, **kwargs):
        # Inspect and reject specs containing SQL patterns
        pass
```

---

## 5. Development Workflow

### 5.1 Hot Reload Dev Server

**Problem:** While iterating on an OpenAPI spec, you want the MCP server to
automatically regenerate and restart whenever the spec file changes — without
manually stopping, re-running `generate`, and restarting `serve`.

**When to use:** Active API development, rapid prototyping, API-first design
cycles where the spec changes frequently.

**Start the hot-reload dev server:**

```bash
api2mcp dev openapi.yaml --output ./dev-server --port 9000
```

**What happens:**

1. `api2mcp dev` generates the server and starts it immediately.
2. It watches `openapi.yaml` (and `./dev-server/`) for changes.
3. When a change is detected, it re-generates and hot-restarts within ~1 second.
4. The terminal shows a rebuild notification with a diff summary.

**Watch an additional directory (e.g. shared schema fragments):**

```bash
api2mcp dev openapi.yaml --watch-dir ./schemas --output ./dev-server
```

---

### 5.2 Interactive Wizard Setup

**Problem:** A new team member needs to set up an MCP server but is unfamiliar
with the CLI flags, config file syntax, and auth options. They need a guided
experience.

**When to use:** First-time setup, on-boarding new developers, generating
production-ready configs with all options correctly set.

**Launch the wizard:**

```bash
api2mcp wizard
```

The wizard walks through:

1. **Spec file** — browse or paste a path / URL
2. **Output directory** — where to write the generated server
3. **Base URL** — detected from the spec or overridden
4. **Authentication** — select type and enter credentials interactively
5. **Secret backend** — env vars, AWS, Vault, keychain, or encrypted file
6. **Rate limiting** — guided configuration based on the target API
7. **Transport** — `http` or `stdio`
8. **Port** — with conflict detection
9. **Config file** — writes `.api2mcp.yaml` to disk
10. **Generate & serve** — optionally runs immediately

**Pre-fill answers for partially automated setups:**

```bash
api2mcp wizard --spec ./openapi.yaml --output ./server --no-confirm
```

---

### 5.3 VS Code Integration

**Problem:** Writing `.api2mcp.yaml` by hand is error-prone — wrong key names,
invalid enum values, out-of-range ports are only caught at runtime.

**When to use:** Any developer editing `.api2mcp.yaml` in VS Code.

**Setup (one-time):**

```bash
# Install recommended extensions (prompted automatically when the workspace opens)
# or install manually:
code --install-extension redhat.vscode-yaml
code --install-extension ms-python.python
code --install-extension charliermarsh.ruff
```

The file `.vscode/settings.json` ships with the project and wires the JSON
Schema automatically:

```json
{
  "yaml.schemas": {
    "./schemas/api2mcp-config.schema.json": [".api2mcp.yaml", ".api2mcp.yml"]
  }
}
```

**What you get:**

- Autocomplete for all keys (`output`, `host`, `port`, `transport`, `log_level`,
  `auth.type`, `cache.backend`, etc.)
- Inline error for `transport: ftp` — only `http` and `stdio` are valid
- Inline error for `port: 99999` — must be ≤ 65535
- Hover documentation for every key
- Seven debug launch configurations (F5 to start the server or run tests)

---

### 5.4 Validating a Spec Without Generating

**Problem:** You want to check whether an API spec is well-formed and
API2MCP-compatible before committing it to a CI pipeline, without producing
any output files.

**When to use:** Pre-commit hooks, CI gating, automated spec reviews.

**Validate and print warnings:**

```bash
api2mcp validate openapi.yaml
# Exit code 0 = valid (warnings allowed)
```

**Treat warnings as errors (strict mode):**

```bash
api2mcp validate openapi.yaml --strict
# Exit code 1 if any warning is found
```

**Pre-commit hook (`.pre-commit-config.yaml`):**

```yaml
repos:
  - repo: local
    hooks:
      - id: api2mcp-validate
        name: Validate OpenAPI spec
        entry: api2mcp validate openapi.yaml --strict
        language: system
        files: openapi\.ya?ml$
        pass_filenames: false
```

**GitHub Actions gate:**

```yaml
- name: Validate API spec
  run: api2mcp validate openapi.yaml --strict
```

---

### 5.5 Testing MCP Servers with MCPTestClient

**Problem:** You want to write automated tests that call MCP tools directly —
verifying tool inputs, outputs, error handling, and auth integration — without
spinning up a live server.

**When to use:** Unit and integration tests for generated MCP servers, CI
pipelines, TDD of API integrations.

**Install the test extra:**

```bash
pip install "api2mcp[dev]"
```

**Example test:**

```python
import pytest
from api2mcp.testing import MCPTestClient

@pytest.fixture
async def client():
    async with MCPTestClient("./github-server") as c:
        yield c

async def test_list_issues_returns_list(client):
    result = await client.call("list_issues", {
        "owner": "api2mcp",
        "repo": "api2mcp",
        "state": "open",
    })
    assert isinstance(result, list)
    assert all("number" in issue for issue in result)

async def test_list_issues_validates_owner(client):
    with pytest.raises(ValueError, match="owner"):
        await client.call("list_issues", {"owner": "", "repo": "api2mcp"})
```

**Mock the underlying HTTP call (no real network needed):**

```python
from api2mcp.testing import MCPTestClient, mock_http

async def test_create_issue_sends_correct_payload(client):
    with mock_http("POST", "https://api.github.com/repos/owner/repo/issues") as mock:
        mock.return_value = {"number": 42, "title": "Test"}
        result = await client.call("create_issue", {
            "owner": "owner",
            "repo": "repo",
            "title": "Test",
        })
    assert result["number"] == 42
    assert mock.called_with(json={"title": "Test"})
```

---

### 5.6 Snapshot Testing for Regression Detection

**Problem:** After updating an OpenAPI spec or upgrading API2MCP, you want to
confirm that the set of generated tools and their schemas have not changed
unexpectedly.

**When to use:** After API spec updates, after upgrading API2MCP, as a
regression guard in CI.

**Capture a baseline snapshot:**

```python
from api2mcp.testing import MCPTestClient, ToolSnapshot

async def test_tool_schema_snapshot():
    async with MCPTestClient("./github-server") as client:
        snapshot = ToolSnapshot(client)
        await snapshot.assert_matches("tests/snapshots/github-tools.json")
        # First run: creates the snapshot file
        # Subsequent runs: fails if the tool list or schemas change
```

**Update the snapshot intentionally (after a deliberate spec change):**

```bash
UPDATE_SNAPSHOTS=1 pytest tests/test_snapshots.py
```

---

## 6. Deployment Scenarios

### 6.1 Local Development (stdio Transport)

**Problem:** You are developing an AI application that embeds the MCP server
as a subprocess. Using `stdio` avoids port conflicts and simplifies the local
development setup.

**When to use:** Local Claude Desktop integration, embedding in VS Code
extensions, tools that launch MCP servers as subprocesses.

**`.api2mcp.yaml`:**

```yaml
transport: stdio
log_level: debug
```

**Start via stdio:**

```bash
api2mcp serve ./my-server --transport stdio
```

**Claude Desktop configuration (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "github": {
      "command": "api2mcp",
      "args": ["serve", "./github-server", "--transport", "stdio"],
      "env": {
        "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx"
      }
    }
  }
}
```

---

### 6.2 Network Server (HTTP Transport)

**Problem:** The MCP server needs to be accessible over the network — by a
remote AI agent, a containerised workflow, or multiple concurrent clients.

**When to use:** Production deployments, multi-agent systems, cloud-hosted
MCP servers, shared team infrastructure.

**`.api2mcp.yaml`:**

```yaml
host: 0.0.0.0       # listen on all interfaces
port: 8000
transport: http
log_level: info
```

**Start:**

```bash
api2mcp serve ./my-server --host 0.0.0.0 --port 8000
```

**Connect from a remote agent:**

```python
from mcp import ClientSession
from mcp.client.http import http_client

async with http_client("http://mcp-server.internal:8000") as (r, w):
    async with ClientSession(r, w) as session:
        tools = await session.list_tools()
```

**TLS termination:** Use a reverse proxy (nginx, Caddy, AWS ALB) in front of
the server and forward to `127.0.0.1:8000` internally.

---

### 6.3 Docker Container Deployment

**Problem:** You need a portable, reproducible deployment of an MCP server
inside a container.

**When to use:** Kubernetes, ECS, any container-based production environment.

**`Dockerfile`:**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install "api2mcp[docs]"

COPY openapi.yaml .
COPY .api2mcp.yaml .

RUN api2mcp generate openapi.yaml --output ./server

EXPOSE 8000
CMD ["api2mcp", "serve", "./server", "--host", "0.0.0.0", "--port", "8000"]
```

**Build and run:**

```bash
docker build -t my-mcp-server .
docker run -p 8000:8000 \
  -e GITHUB_TOKEN=ghp_xxxx \
  my-mcp-server
```

**Docker Compose (server + Redis cache):**

```yaml
version: "3.9"
services:
  mcp-server:
    build: .
    ports:
      - "8000:8000"
    environment:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

**`.api2mcp.yaml` inside the container:**

```yaml
host: 0.0.0.0
port: 8000
transport: http
cache:
  backend: redis
  redis_url: redis://redis:6379/0
  ttl_seconds: 300
```

---

### 6.4 CI/CD Pipeline Integration

**Problem:** You want to validate specs, regenerate servers, and run tests
automatically on every pull request.

**When to use:** Any team using GitHub Actions, GitLab CI, CircleCI, etc.

**`.github/workflows/mcp.yml`:**

```yaml
name: MCP Server CI

on:
  push:
    branches: [main]
  pull_request:
    paths:
      - "openapi.yaml"
      - ".api2mcp.yaml"

jobs:
  validate-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install API2MCP
        run: pip install "api2mcp[dev]"

      - name: Validate spec
        run: api2mcp validate openapi.yaml --strict

      - name: Generate server
        run: api2mcp generate openapi.yaml --output ./server

      - name: Run MCP server tests
        run: pytest tests/ --no-cov -v
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN_TEST }}
```

---

### 6.5 Multi-Environment Config (dev / staging / prod)

**Problem:** You need different configurations for development, staging, and
production (different base URLs, log levels, rate limits).

**When to use:** Any team with multiple deployment environments.

**Directory layout:**

```
project/
├── openapi.yaml
├── .api2mcp.yaml          # base config (committed)
├── .api2mcp.dev.yaml      # dev overrides (committed)
├── .api2mcp.staging.yaml  # staging overrides (committed)
└── .api2mcp.prod.yaml     # prod overrides (committed, no secrets)
```

**`.api2mcp.yaml` (base):**

```yaml
transport: http
log_level: warning
validation:
  sanitize_strings: true
```

**`.api2mcp.prod.yaml` (production overrides):**

```yaml
host: 0.0.0.0
port: 8000
log_level: error
cache:
  backend: redis
  redis_url: ${REDIS_URL}
  ttl_seconds: 600
pool:
  max_connections: 200
circuit_breaker:
  failure_threshold: 3
  recovery_timeout: 60
```

**Serve with a specific config:**

```bash
# Development
api2mcp serve ./server --config .api2mcp.dev.yaml

# Production
api2mcp serve ./server --config .api2mcp.prod.yaml
```

---

## 7. LangGraph Orchestration

### 7.1 Reactive Agent — Single API

**Problem:** You want an AI agent that can freely use any tool from a single
MCP server to answer a natural-language request — without pre-defined steps.

**When to use:** Open-ended queries, exploratory tool use, chat assistants
with API access, any task where the agent decides which tools to call.

**Full example:**

```python
import asyncio
import os
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.reactive import ReactiveGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    model = ChatAnthropic(model="claude-sonnet-4-6", api_key=os.environ["ANTHROPIC_API_KEY"])
    registry = MCPToolRegistry()

    async with stdio_client(StdioServerParameters(command="python", args=["github-server/server.py"])) as (r, w):
        async with ClientSession(r, w) as session:
            await registry.register_server("github", session)

            graph = ReactiveGraph(
                model=model,
                registry=registry,
                api_names=["github"],
                checkpointer=MemorySaver(),
            )

            result = await graph.run(
                "List all open issues in the anthropics/anthropic-sdk-python repo "
                "that were created in the last 7 days."
            )
            print(result["output"])

asyncio.run(main())
```

---

### 7.2 Planner Graph — Sequential Workflow

**Problem:** You have a multi-step task where each step depends on the result
of the previous one. You want the LLM to plan the steps upfront and then
execute them in order.

**When to use:** ETL pipelines, data enrichment workflows, ordered operations
where the output of step N is input to step N+1.

**Example — create a GitHub issue, then immediately label it:**

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from api2mcp.orchestration.graphs.planner import PlannerGraph

async def sequential_workflow(registry):
    model = ChatAnthropic(model="claude-sonnet-4-6")
    checkpointer = SqliteSaver.from_conn_string("workflows.db")

    graph = PlannerGraph(
        model=model,
        registry=registry,
        api_names=["github"],
        checkpointer=checkpointer,
        execution_mode="sequential",
    )

    result = await graph.run(
        "In the repo api2mcp/api2mcp: "
        "1. Create an issue titled 'Add PostgreSQL support' with a description. "
        "2. Add the label 'enhancement' to the newly created issue."
    )
    print(result["output"])
    print("Steps executed:", result["steps"])
```

---

### 7.3 Planner Graph — Parallel Execution

**Problem:** You have a multi-step workflow where many steps are independent
and can be executed concurrently to reduce total execution time.

**When to use:** Data aggregation from multiple endpoints, fan-out read
operations, bulk processing where each item is independent.

**Example — fetch details for 10 GitHub issues simultaneously:**

```python
graph = PlannerGraph(
    model=model,
    registry=registry,
    api_names=["github"],
    checkpointer=checkpointer,
    execution_mode="parallel",   # all independent steps run concurrently
)

result = await graph.run(
    "For each of the following GitHub issue numbers — 1, 2, 3, 4, 5 — "
    "fetch the full issue details and return a summary table."
)
# All 5 `get_issue` calls execute in parallel
```

**Mixed mode — automatically parallelises where safe:**

```python
graph = PlannerGraph(
    model=model,
    registry=registry,
    api_names=["github", "jira"],
    checkpointer=checkpointer,
    execution_mode="mixed",   # LLM identifies dependencies; parallelises the rest
)
```

---

### 7.4 Multi-API Orchestration

**Problem:** A workflow spans two or more separate APIs. For example, reading
from GitHub and writing to Jira, or reading from Stripe and writing to a CRM.

**When to use:** Cross-platform automation, bi-directional sync, any task that
requires data from API A to be acted upon in API B.

**Example — GitHub → Jira bug sync:**

```python
from api2mcp.orchestration.adapters.registry import MCPToolRegistry
from api2mcp.orchestration.graphs.planner import PlannerGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def sync_bugs(model, checkpointer):
    registry = MCPToolRegistry()

    async with stdio_client(StdioServerParameters(command="python", args=["github-server/server.py"])) as (r1, w1):
        async with ClientSession(r1, w1) as github_session:
            await registry.register_server("github", github_session)

            async with stdio_client(StdioServerParameters(command="python", args=["jira-server/server.py"])) as (r2, w2):
                async with ClientSession(r2, w2) as jira_session:
                    await registry.register_server("jira", jira_session)

                    graph = PlannerGraph(
                        model=model,
                        registry=registry,
                        api_names=["github", "jira"],
                        checkpointer=checkpointer,
                        execution_mode="mixed",
                    )

                    result = await graph.run(
                        "Find all open GitHub issues in org/repo labelled 'bug' "
                        "that have no corresponding Jira ticket. Create a Jira "
                        "ticket in project BUG for each one, linking back to the "
                        "GitHub issue URL."
                    )
                    print(result["output"])
```

**Filtering tools by server:**

```python
# Use only GitHub tools in this call
github_tools = registry.get_tools(server_name="github")

# Use only read tools (no mutations)
read_tools = registry.get_tools(category="read")
```

---

### 7.5 Conversational Agent with Memory

**Problem:** You want a multi-turn conversation where the agent remembers
previous messages and can reference earlier results — like a chatbot with
full API access.

**When to use:** Interactive AI assistants, support bots with API access,
developer tools that accept natural language commands over multiple turns.

**Example:**

```python
from api2mcp.orchestration.graphs.conversational import ConversationalGraph
from langgraph.checkpoint.sqlite import SqliteSaver

async def chat_session(registry):
    model = ChatAnthropic(model="claude-sonnet-4-6")
    checkpointer = SqliteSaver.from_conn_string("chat.db")

    graph = ConversationalGraph(
        model=model,
        registry=registry,
        api_names=["github"],
        checkpointer=checkpointer,
        thread_id="user-alice-session-001",   # unique per conversation
    )

    # Turn 1
    r1 = await graph.chat("Show me the 5 most recent open issues")
    print("Agent:", r1["output"])

    # Turn 2 — agent remembers the issues from turn 1
    r2 = await graph.chat("Close the oldest one and add a comment explaining it was resolved")
    print("Agent:", r2["output"])

    # Turn 3
    r3 = await graph.chat("Now create a new issue summarising the ones we closed today")
    print("Agent:", r3["output"])
```

**Resume a previous conversation (across restarts):**

```python
# SQLite checkpointer persists to disk — the thread_id retrieves prior state
graph = ConversationalGraph(..., thread_id="user-alice-session-001")
r = await graph.chat("What did we do last time?")
# Agent recalls the previous turns
```

---

### 7.6 Human-in-the-Loop Approval

**Problem:** Some tool calls have irreversible consequences (deleting data,
sending emails, processing payments). You want the agent to pause and request
human approval before executing these actions.

**When to use:** Any workflow involving mutations, deletions, or financial
transactions.

**Example with approval callback:**

```python
from api2mcp.orchestration.graphs.conversational import ConversationalGraph

async def approve(tool_name: str, tool_input: dict) -> bool:
    """Called before any write operation. Return True to allow, False to deny."""
    print(f"\n[APPROVAL REQUIRED]")
    print(f"Tool: {tool_name}")
    print(f"Input: {tool_input}")
    answer = input("Allow? (y/n): ").strip().lower()
    return answer == "y"

graph = ConversationalGraph(
    model=model,
    registry=registry,
    api_names=["github"],
    checkpointer=checkpointer,
    thread_id="session-002",
    approval_callback=approve,         # invoked for write tools
    auto_approve_reads=True,           # GET-equivalent tools bypass approval
)

result = await graph.chat("Close all issues labelled 'wontfix'")
# Agent will pause and call approve() before each close_issue call
```

---

### 7.7 Streaming Real-Time Output

**Problem:** A long-running workflow generates output progressively. You want
to display tokens and tool events to the user in real-time instead of waiting
for the full result.

**When to use:** Interactive terminals, web UIs with server-sent events,
long-running workflows where progress feedback matters.

**Token and event streaming:**

```python
from api2mcp.orchestration.graphs.reactive import ReactiveGraph

async def stream_workflow(registry):
    graph = ReactiveGraph(model=model, registry=registry, api_names=["github"])

    print("Agent: ", end="", flush=True)
    async for event in graph.astream("Summarise all open pull requests with their review status"):
        if "token" in event:
            print(event["token"], end="", flush=True)
        elif "tool_call" in event:
            tc = event["tool_call"]
            print(f"\n  [→ calling {tc['name']} ...]", flush=True)
        elif "tool_result" in event:
            print(f"  [← {event['tool_result']['name']} completed]", flush=True)
    print()  # newline after final token
```

**FastAPI server-sent events (SSE) endpoint:**

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json

app = FastAPI()

@app.post("/run")
async def run_workflow(prompt: str):
    async def event_generator():
        async for event in graph.astream(prompt):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

### 7.8 Checkpointed & Resumable Workflows

**Problem:** A workflow fails partway through (network error, API outage,
process crash). Without checkpointing you must restart from the beginning,
re-doing expensive steps.

**When to use:** Long-running workflows, workflows with expensive API calls,
multi-day scheduled automations, any workflow that must survive failures.

**PostgreSQL checkpointer (recommended for production):**

```bash
pip install "api2mcp[postgres]"
```

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:pass@db.example.com:5432/workflows"
)

graph = PlannerGraph(
    model=model,
    registry=registry,
    api_names=["github", "jira"],
    checkpointer=checkpointer,
    execution_mode="mixed",
    thread_id="sync-2026-03-06",
)
```

**Resume after a failure:**

```python
# The thread_id is the key — rerunning with the same ID resumes from the last checkpoint
result = await graph.run(
    "Sync all GitHub issues to Jira",
    thread_id="sync-2026-03-06",   # resumes mid-workflow
)
```

**List available checkpoints:**

```python
checkpoints = await checkpointer.list({"configurable": {"thread_id": "sync-2026-03-06"}})
for cp in checkpoints:
    print(cp.config, cp.metadata)
```

---

## 8. Real-World Integration Scenarios

### 8.1 GitHub DevOps Automation

**Use case:** Automate daily DevOps workflows — triaging issues, labelling PRs,
closing stale issues, generating release notes — using natural language.

**Setup:**

```bash
api2mcp template install github-issues
api2mcp generate github-openapi.yaml --output ./github-server
```

**`.api2mcp.yaml`:**

```yaml
auth:
  type: bearer
  token_env: GITHUB_TOKEN
rate_limit:
  strategy: sliding_window
  requests_per_minute: 60
  retry_after: true
cache:
  backend: memory
  ttl_seconds: 60
```

**Workflow — auto-triage new issues:**

```python
result = await graph.run(
    """
    Look at all GitHub issues opened in the last 24 hours in org/repo.
    For each issue:
    - If it mentions a crash or traceback, add label 'bug' and assign to @on-call
    - If it is a feature request, add label 'enhancement'
    - If it is a question, add label 'question' and post a comment asking for more detail
    - If it has no description, add label 'needs-info' and comment asking for details
    """
)
```

**Scheduled release notes (cron):**

```python
result = await graph.run(
    "Generate release notes for all PRs merged into main since the last git tag. "
    "Group them by label: Breaking Changes, New Features, Bug Fixes, Documentation."
)
with open("RELEASE_NOTES.md", "w") as f:
    f.write(result["output"])
```

---

### 8.2 Stripe Payment Processing

**Use case:** Build an AI billing assistant that can look up customers,
subscriptions, invoices, and trigger refunds — all via natural language.

**Setup:**

```bash
api2mcp template install stripe-billing
api2mcp generate stripe-openapi.yaml --output ./stripe-server
```

**`.api2mcp.yaml`:**

```yaml
auth:
  type: bearer
  token_env: STRIPE_SECRET_KEY
rate_limit:
  strategy: token_bucket
  requests_per_second: 25    # Stripe's default limit
  burst_size: 100
  retry_after: true
validation:
  sanitize_strings: true
  max_string_length: 5000
```

**Set your key:**

```bash
export STRIPE_SECRET_KEY="sk_live_xxxxxxxxxxxx"
api2mcp serve ./stripe-server --port 8002
```

**Billing assistant workflow:**

```python
result = await graph.run(
    "Find all customers whose subscription will expire in the next 7 days. "
    "For each customer, check if they have auto-renew enabled. "
    "If not, send them a renewal reminder via the billing email."
)
```

**Refund processing with human-in-the-loop:**

```python
graph = ConversationalGraph(
    model=model,
    registry=registry,
    api_names=["stripe"],
    checkpointer=checkpointer,
    thread_id="support-ticket-12345",
    approval_callback=approve,   # approval required before refund
)

result = await graph.chat(
    "Customer cus_xxx says they were double-charged on 2026-02-15. "
    "Verify the duplicate charge and process a full refund if confirmed."
)
```

---

### 8.3 GitHub + Stripe Billing Reconciliation

**Use case:** Match GitHub organisation members against Stripe customers to
ensure every developer seat is billed correctly, flag discrepancies, and create
refund or invoice adjustments automatically.

**Setup:**

```bash
api2mcp generate github-openapi.yaml --output ./github-server
api2mcp generate stripe-openapi.yaml --output ./stripe-server
```

**Both servers must be running or reachable:**

```bash
api2mcp serve ./github-server --port 8001 &
api2mcp serve ./stripe-server --port 8002 &
```

**Reconciliation workflow:**

```python
async def reconcile(registry, model, checkpointer):
    graph = PlannerGraph(
        model=model,
        registry=registry,
        api_names=["github", "stripe"],
        checkpointer=checkpointer,
        execution_mode="mixed",
    )

    result = await graph.run(
        """
        1. List all members of the GitHub org 'mycompany'.
        2. For each member, find their corresponding Stripe customer by email.
        3. Check that each member has an active 'developer-seat' subscription.
        4. Report:
           a. Members with no Stripe customer record (need to be invoiced)
           b. Stripe customers with no GitHub membership (subscriptions to cancel)
           c. Members whose subscription is past due
        5. For past-due subscriptions, send a dunning email via Stripe.
        """
    )
    print(result["output"])
```

---

### 8.4 GitHub + Slack Notifications

**Use case:** Post GitHub event summaries to Slack channels — daily standup
reports, PR review reminders, release announcements.

**Setup:**

```bash
api2mcp generate github-openapi.yaml --output ./github-server
api2mcp generate slack-openapi.yaml  --output ./slack-server
```

**`.api2mcp.yaml` for Slack:**

```yaml
auth:
  type: bearer
  token_env: SLACK_BOT_TOKEN
```

**Daily standup bot:**

```python
result = await graph.run(
    """
    1. Fetch all PRs opened in the last 24 hours in org/repo.
    2. Fetch all PRs that have been awaiting review for more than 48 hours.
    3. Fetch all issues closed in the last 24 hours.
    4. Compose a standup summary in Slack Block Kit format.
    5. Post it to the #engineering channel.
    """
)
```

**PR review reminders (scheduled daily):**

```python
result = await graph.run(
    "Find all open PRs in org/repo that have been waiting for review for "
    "more than 3 days. For each, DM the assigned reviewer on Slack with "
    "a reminder that includes the PR title, author, and number of days waiting."
)
```

---

### 8.5 Internal Enterprise API Gateway

**Use case:** Your organisation has dozens of internal microservices, each with
its own OpenAPI spec. You want to expose all of them as a unified MCP tool
registry so AI agents can access any internal service via natural language.

**Setup (one server per microservice):**

```bash
for spec in services/*/openapi.yaml; do
  name=$(basename $(dirname $spec))
  api2mcp generate "$spec" --output "./mcp-servers/$name"
done
```

**Start all servers:**

```bash
for dir in mcp-servers/*/; do
  name=$(basename "$dir")
  api2mcp serve "$dir" --port $((8000 + i)) &
  ((i++))
done
```

**Register all in a single registry:**

```python
registry = MCPToolRegistry()

services = [
    ("users",    "mcp-servers/users/server.py"),
    ("orders",   "mcp-servers/orders/server.py"),
    ("inventory","mcp-servers/inventory/server.py"),
    ("billing",  "mcp-servers/billing/server.py"),
    ("shipping", "mcp-servers/shipping/server.py"),
]

for name, script in services:
    params = StdioServerParameters(command="python", args=[script])
    # ... connect and register each
    await registry.register_server(name, session)

# All tools are now available as users:get_user, orders:list_orders, etc.
graph = ReactiveGraph(model=model, registry=registry, api_names=[s[0] for s in services])
result = await graph.run("What is the current status of order #12345 for customer john@example.com?")
```

---

### 8.6 AWS Cloud Infrastructure Management

**Use case:** Convert the AWS API (via OpenAPI spec or Postman collection) into
MCP tools so an AI agent can describe, create, and manage cloud resources using
natural language.

**Setup:**

```bash
# Use the community AWS template
api2mcp template install aws-ec2
api2mcp template install aws-s3
```

**`.api2mcp.yaml`:**

```yaml
auth:
  type: api_key
  location: header
  name: Authorization       # AWS Signature V4 — handled by the template
  key_env: AWS_ACCESS_KEY_ID

secrets:
  backend: aws              # pull from Secrets Manager
  region: us-east-1
  secret_id: prod/aws-mcp-credentials

rate_limit:
  strategy: token_bucket
  requests_per_second: 50
```

**Infrastructure management workflow:**

```python
result = await graph.run(
    """
    1. List all EC2 instances tagged 'Environment=staging' that have been stopped
       for more than 30 days.
    2. List all S3 buckets that have not been accessed in the last 90 days.
    3. Generate a cost-saving report estimating monthly savings if these resources
       were terminated/deleted.
    4. Tag the eligible EC2 instances with 'Action=PendingTermination'.
    """
)
```

---

### 8.7 CRM Automation (Salesforce + Email)

**Use case:** An AI assistant that can query Salesforce for leads and contacts,
draft personalised outreach emails, and send them — or escalate high-value
opportunities to the sales team via Slack.

**Setup:**

```bash
api2mcp generate salesforce-openapi.yaml --output ./salesforce-server
api2mcp generate sendgrid-openapi.yaml   --output ./email-server
```

**`.api2mcp.yaml` for Salesforce:**

```yaml
auth:
  type: oauth2
  flow: client_credentials
  token_url: https://login.salesforce.com/services/oauth2/token
  client_id_env: SF_CLIENT_ID
  client_secret_env: SF_CLIENT_SECRET
  scopes: [api, refresh_token]
```

**Lead nurturing workflow:**

```python
graph = PlannerGraph(
    model=model,
    registry=registry,
    api_names=["salesforce", "sendgrid"],
    checkpointer=checkpointer,
    execution_mode="mixed",
    approval_callback=approve,   # approve before sending emails
)

result = await graph.run(
    """
    Find all Salesforce leads in stage 'MQL' (Marketing Qualified Lead) that
    have not been contacted in the last 14 days. For each lead:
    1. Look up their industry, company size, and last activity.
    2. Draft a personalised follow-up email referencing their specific pain points.
    3. Send the email via SendGrid from outreach@company.com.
    4. Update the Salesforce lead's 'Last Contact Date' and add an activity log.
    """
)
```

---

### 8.8 Database API Proxy

**Use case:** Your organisation exposes its database through a REST API (e.g.
PostgREST, Hasura, Directus). You want an AI agent to query and update records
using natural language without writing SQL.

**Setup:**

```bash
# PostgREST auto-generates an OpenAPI spec at /
curl http://localhost:3000/ -o postgrest-openapi.json
api2mcp generate postgrest-openapi.json --output ./db-server
```

**`.api2mcp.yaml`:**

```yaml
auth:
  type: bearer
  token_env: PGRST_JWT_SECRET
validation:
  max_string_length: 50000
  max_array_items: 10000
  sanitize_strings: true
cache:
  backend: memory
  ttl_seconds: 30           # short TTL — data changes frequently
rate_limit:
  strategy: sliding_window
  requests_per_second: 100
```

**Natural language database query:**

```python
result = await graph.run(
    "Find all orders from the last month where the total exceeds $1,000, "
    "group them by customer, and return the top 10 customers by total spend."
)
```

**Data pipeline workflow:**

```python
result = await graph.run(
    """
    1. Query the 'raw_events' table for all records from yesterday.
    2. Aggregate by event_type and user_id.
    3. Insert the aggregated results into the 'daily_metrics' table.
    4. Delete the processed raw_events records to free space.
    """
)
```

---

## 9. Extending API2MCP

### 9.1 Install a Community Template

**Problem:** You want a pre-built, production-ready MCP server for a popular
API without configuring everything from scratch.

**Browse available templates:**

```bash
api2mcp template search
api2mcp template search stripe
api2mcp template search --verbose   # show full descriptions and versions
```

**Install a template:**

```bash
api2mcp template install github-issues --dest ./github-server
api2mcp template install stripe-billing --dest ./stripe-server
```

**Pin to a specific version:**

```bash
api2mcp template install github-issues --version v1.2.0 --dest ./github-server
```

**Update a template:**

```bash
api2mcp template update github-issues --dest ./github-server
```

---

### 9.2 Build and Publish a Template

**Problem:** You have built an MCP server for an API that others on your team
(or the community) will also need. You want to package and share it.

**Template directory structure:**

```
my-template/
├── template.yaml          # Manifest (required)
├── openapi.yaml           # The API spec
├── .api2mcp.yaml          # Default configuration
├── README.md              # Usage instructions
└── examples/
    └── basic.py           # Example workflow
```

**`template.yaml`:**

```yaml
id: myorg/my-api
name: My API MCP Server
description: MCP server for My API — converts all endpoints to MCP tools
author: Your Name
license: MIT
tags: [rest, enterprise, myapi]
versions:
  - tag: v1.0.0
    description: Initial release
    api_version: "2024-01"
    min_api2mcp: "0.1.0"
```

**Publish (push to GitHub with a version tag):**

```bash
git tag v1.0.0
git push origin v1.0.0
```

Submit to the community registry by opening a PR to the
`api2mcp/template-registry` repository adding your template to `registry.yaml`.

---

### 9.3 Write a Custom Plugin

**Problem:** You need to extend API2MCP with custom behaviour at specific
points in the pipeline — for example, to add custom logging, transform API
responses, or enforce company-specific security policies.

**Available hook points:**

| Hook | When it fires | Typical use |
|------|---------------|-------------|
| `PRE_PARSE` | Before a spec is parsed | Spec pre-processing, injection detection |
| `POST_PARSE` | After a spec is parsed to IR | IR enrichment, tag addition |
| `PRE_GENERATE` | Before MCP tools are generated | Code generation customisation |
| `POST_GENERATE` | After MCP server code is written | File post-processing |
| `PRE_SERVE` | Before the server starts | Config validation, warm-up |
| `ON_TOOL_CALL` | On every incoming tool call | Logging, auditing, custom validation |

**Example — audit log plugin:**

```python
import logging
from api2mcp.plugins.base import BasePlugin
from api2mcp.plugins.hooks import ON_TOOL_CALL

logger = logging.getLogger("audit")

class AuditLogPlugin(BasePlugin):
    id = "audit-log"
    name = "Audit Log"
    version = "1.0.0"
    description = "Logs every MCP tool call to the audit logger"

    def setup(self, hook_manager):
        hook_manager.register_hook(ON_TOOL_CALL, self._log_call, plugin_id=self.id, priority=10)

    def _log_call(self, *, tool_name, tool_input, **kwargs):
        logger.info(
            "tool_call",
            extra={"tool": tool_name, "input_keys": list(tool_input.keys())}
        )
```

**Register via `pyproject.toml` entry point:**

```toml
[project.entry-points."api2mcp.plugins"]
audit-log = "my_package.plugins.audit:AuditLogPlugin"
```

**Or load from a local directory:**

```python
from api2mcp.plugins.manager import PluginManager

manager = PluginManager()
manager.load_all(directory="./plugins/")
```

---

### 9.4 Write a Custom Parser

**Problem:** Your organisation uses an internal API format that is not OpenAPI,
GraphQL, Swagger, or Postman — for example, a custom YAML schema or a
protobuf-based descriptor.

**Step 1 — Create the parser module:**

```python
# src/api2mcp/parsers/myformat.py
from pathlib import Path
from api2mcp.core.ir_schema import APISpec
from api2mcp.core.parser import BaseParser, ParseError

class MyFormatParser(BaseParser):
    """Parser for MyOrg's internal API descriptor format."""

    def detect(self, content: dict) -> bool:
        """Return True if this parser should handle the content."""
        return "myorg_api_version" in content

    async def validate(self, source: str | Path, **kwargs) -> list[ParseError]:
        content = self._load(source)
        errors = []
        if "endpoints" not in content:
            errors.append(ParseError("Missing 'endpoints' key", severity="error"))
        return errors

    async def parse(self, source: str | Path, **kwargs) -> APISpec:
        content = self._load(source)
        # Convert content to the standard IR (APISpec)
        return APISpec(
            title=content.get("title", "My API"),
            version=content.get("api_version", "1.0"),
            base_url=content["base_url"],
            endpoints=self._convert_endpoints(content["endpoints"]),
        )

    def _convert_endpoints(self, raw):
        # ... map raw endpoint dicts to IR Endpoint objects
        pass
```

**Step 2 — Register in `parsers/__init__.py`:**

```python
from api2mcp.parsers.myformat import MyFormatParser

PARSERS = [
    OpenAPIParser,
    GraphQLParser,
    SwaggerParser,
    PostmanParser,
    MyFormatParser,   # add here — detection order matters
]
```

**Step 3 — Test:**

```bash
api2mcp validate my-api-descriptor.myformat --format myformat
api2mcp generate my-api-descriptor.myformat --format myformat --output ./server
```

---

## 10. Observability & Troubleshooting

### 10.1 Structured Logging

**Enable verbose logging for a single run:**

```bash
api2mcp --log-level debug serve ./my-server
```

**Log levels and their meaning:**

| Level | Use |
|-------|-----|
| `debug` | Every request/response, tool registration, config loading |
| `info` | Server startup, tool calls, cache hits/misses |
| `warning` | Rate limit approaches, validation warnings, deprecated config |
| `error` | Failed requests, auth errors, parse failures |
| `critical` | Server crashes, unrecoverable errors |

**Production `.api2mcp.yaml`:**

```yaml
log_level: warning    # quiet in production; errors go to your log aggregator
```

**Forward logs to a log aggregator (e.g. Datadog):**

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record),
        })

logging.getLogger("api2mcp").setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger("api2mcp").addHandler(handler)
```

---

### 10.2 Workflow Streaming Observability

**Track every step of a LangGraph workflow in real-time:**

```python
async for event in graph.astream("Run the daily sync"):
    event_type = list(event.keys())[0]

    if event_type == "plan":
        print(f"[PLAN] {len(event['plan'])} steps identified")
        for i, step in enumerate(event["plan"], 1):
            print(f"  Step {i}: {step['description']}")

    elif event_type == "tool_call":
        tc = event["tool_call"]
        print(f"[CALL] {tc['name']} ← {list(tc['input'].keys())}")

    elif event_type == "tool_result":
        tr = event["tool_result"]
        status = "✓" if tr.get("success") else "✗"
        print(f"[DONE] {tr['name']} {status}")

    elif event_type == "token":
        print(event["token"], end="", flush=True)

    elif event_type == "error":
        print(f"[ERROR] {event['error']}")
```

---

### 10.3 Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `ParseError: Missing 'paths' key` | Input file is not a valid OpenAPI spec | Run `api2mcp validate` to see all errors; check file format |
| `AuthError: 401 Unauthorized` | Wrong or expired API token | Check `key_env` / `token_env` variable name and value |
| `RateLimitError: 429 Too Many Requests` | API rate limit exceeded | Set `retry_after: true`; reduce `requests_per_minute` |
| `CircuitBreakerOpen` | Downstream API has too many failures | Check the upstream API status; circuit will auto-recover after `recovery_timeout` |
| `ValidationError: string too long` | LLM produced an oversized input | Increase `max_string_length` or add a system prompt limiting output size |
| `SyntaxError` in generated server | API spec has malformed operation IDs | Run `api2mcp validate --strict` and fix the reported issues |
| `ConnectionRefused` on serve | Port already in use | Change the port: `api2mcp serve ./server --port 9001` |
| `ImportError: graphql-core` | GraphQL extra not installed | `pip install "api2mcp[graphql]"` |
| `ImportError: hvac` | Vault extra not installed | `pip install "api2mcp[vault]"` |
| `PluginDependencyError` | Plugin `requires` a plugin that is not loaded | Ensure all required plugins are installed and in the load path |
| `SnapshotMismatch` | Tool schema changed after spec update | Review changes intentionally; update snapshot with `UPDATE_SNAPSHOTS=1 pytest` |

---

*Generated by API2MCP project — `docs/runbook.md`*
