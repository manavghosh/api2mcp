# Security Policy

For a comprehensive security analysis, see [THREAT_MODEL.md](THREAT_MODEL.md).

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

Older versions do not receive security fixes. Please upgrade to the latest release.

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub Issues.**

If you discover a security vulnerability, use one of the following private channels:

### Option 1 — GitHub Private Vulnerability Reporting (preferred)

1. Go to the repository on GitHub
2. Click **Security** → **Report a vulnerability**
3. Fill in the form with as much detail as possible

This is end-to-end private and notifies the maintainers directly.

### Option 2 — Email

Send details to **manavghosh@gmail.com**.
Encrypt your message with the maintainer's public PGP key if available.

---

## What to Include in a Report

Please provide:

- A description of the vulnerability and its potential impact
- The affected version(s)
- Steps to reproduce the issue
- Any proof-of-concept code (if applicable)
- Suggested remediation (if you have one)

---

## Response Timeline

| Milestone | Target |
|-----------|--------|
| Acknowledgement of report | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix released (critical) | Within 14 days |
| Fix released (moderate) | Within 30 days |
| Public disclosure | After fix is released |

---

## Scope

The following are **in scope** for security reports:

- Input validation bypasses in the OpenAPI/GraphQL parsers
- Authentication credential exposure or leakage
- Secret management flaws (keyring, env var handling)
- Dependency vulnerabilities with a direct exploit path
- CLI command injection via crafted spec files
- MCP server transport security issues

The following are **out of scope**:

- Vulnerabilities in third-party APIs that API2MCP connects to
- Issues requiring physical access to the machine
- Social engineering
- Denial of service via extremely large spec files (known limitation, tracked separately)

---

## Disclosure Policy

We follow responsible disclosure. Once a fix is available, we will:

1. Release the patched version to PyPI
2. Publish a GitHub Security Advisory
3. Credit the reporter in the advisory (unless they prefer to remain anonymous)
4. Update `CHANGELOG.md` with a security notice

---

## Security Best Practices for Users

- Always pin `api2mcp` to a specific version in production
- Store API keys in environment variables, never in spec files or config files
- Use the `keyring` backend for secret storage in production deployments
- Run `pip audit` periodically to check for known vulnerabilities in dependencies
- Enable Dependabot alerts on any fork of this repository

---

## Disclaimer

API2MCP is an independent personal project created and maintained solely by
[Manav Ghosh](https://github.com/manavghosh) in a personal capacity. It is not
affiliated with, sponsored by, endorsed by, or in any way associated with any
current or former employer, client, or organisation. All design decisions,
source code, documentation, and expressed opinions are those of the author
alone and do not represent the views or intellectual property of any third
party.
