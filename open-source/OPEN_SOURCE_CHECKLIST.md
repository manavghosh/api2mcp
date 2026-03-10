# API2MCP — Open Source Launch Checklist

A complete reference for publishing API2MCP as a community open source project.
Work through each section in order. Check off items as you complete them.

---

## 1. Legal & Licensing

- [ ] Copy `LICENSE` (MIT) into the root of the repository
- [ ] Confirm `pyproject.toml` has `license = "MIT"` and the OSI classifier (already set)
- [ ] Add a copyright header to every source file, or confirm MIT allows omitting per-file headers (it does — one root LICENSE file is sufficient)
- [ ] Confirm you own or have rights to all code, assets, and dependencies
- [ ] Audit all third-party dependencies: verify each is MIT-compatible (Apache 2.0, BSD, ISC are all fine; GPL is not compatible with MIT distribution)
- [ ] Remove or replace any internal/proprietary code, credentials, or company-specific references from the codebase

---

## 2. Repository Setup (GitHub)

- [ ] Create a new public GitHub repository: `github.com/manavghosh/api2mcp`
- [ ] Set the repository description: *"Universal REST/GraphQL to MCP Server Converter with LangGraph orchestration"*
- [ ] Add repository topics/tags: `mcp`, `openapi`, `graphql`, `langgraph`, `ai`, `python`, `llm`, `model-context-protocol`, `api`, `converter`
- [ ] Set the default branch to `main`
- [ ] Enable GitHub Discussions for community Q&A
- [ ] Enable GitHub Issues with the provided issue templates
- [ ] Add a social preview image (1280×640px) — shows in link previews on Twitter/LinkedIn
- [ ] Pin the repository to your GitHub profile if applicable
- [ ] Set up branch protection on `main`:
  - [ ] Require pull request reviews (at least 1 reviewer)
  - [ ] Require status checks to pass (CI)
  - [ ] Disallow force pushes

---

## 3. Core Open Source Files

Copy these from `open-source/` into the repository root:

- [ ] `LICENSE` — MIT license (generated)
- [ ] `CONTRIBUTING.md` — contribution guide (generated)
- [ ] `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1 (generated)
- [ ] `SECURITY.md` — vulnerability reporting policy (generated)
- [ ] `CHANGELOG.md` — version history (generated, keep updated)
- [ ] `GOVERNANCE.md` — decision-making and maintainer model (generated)
- [ ] `SUPPORT.md` — where to ask questions (generated)

---

## 4. GitHub Templates

Copy these from `open-source/.github/` into `.github/` in your repository:

- [ ] `.github/ISSUE_TEMPLATE/bug_report.md`
- [ ] `.github/ISSUE_TEMPLATE/feature_request.md`
- [ ] `.github/ISSUE_TEMPLATE/question.md`
- [ ] `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] `.github/CODEOWNERS` — designate code owners per directory

---

## 5. README

- [ ] README.md exists at the repository root (already in `docs/`)
- [ ] README includes:
  - [ ] Project name and one-line description
  - [ ] Badges: PyPI version, Python versions, license, CI status, coverage
  - [ ] Quick install: `pip install api2mcp`
  - [ ] 60-second quickstart (copy from existing README)
  - [ ] Links to full docs site
  - [ ] Links to CONTRIBUTING.md and CODE_OF_CONDUCT.md
  - [ ] Screenshot or architecture diagram
  - [ ] "Built with" / acknowledgements section

---

## 6. PyPI Publication

- [ ] Create an account on [pypi.org](https://pypi.org) if you don't have one
- [ ] Register the package name `api2mcp` on PyPI (check availability first)
- [ ] Add PyPI trusted publisher in GitHub Actions (OIDC — no stored secrets needed):
  - Go to PyPI → Your projects → api2mcp → Publishing → Add publisher
  - Set: owner=`<your-github-org>`, repo=`api2mcp`, workflow=`release.yml`
- [ ] Verify `pyproject.toml` metadata is complete:
  - [ ] `name`, `version`, `description`, `readme`, `license`
  - [ ] `authors` with name and email
  - [ ] `homepage`, `repository`, `documentation` URLs
  - [ ] All classifiers accurate
- [ ] Do a test publish to [test.pypi.org](https://test.pypi.org) first
- [ ] Publish `v0.1.0` to production PyPI
- [ ] Confirm `pip install api2mcp` works from a clean environment

---

## 7. CI/CD (GitHub Actions)

The `.github/workflows/` directory already has a CI workflow. Verify and extend:

- [ ] `ci.yml` runs on every PR: tests, lint, type-check, security scan (already exists)
- [ ] Add `release.yml` — triggered on version tags (`v*`), publishes to PyPI via OIDC
- [ ] Add `docs.yml` — builds and deploys MkDocs to GitHub Pages on push to `main` (already exists)
- [ ] Add `dependency-review.yml` — scans new dependencies on PRs for license/vulnerability issues
- [ ] Confirm all workflows pass on the initial public commit

---

## 8. Documentation Site

- [ ] `mkdocs.yml` is configured and `mkdocs build --strict` passes (already done)
- [ ] Deploy docs to GitHub Pages:
  - Go to repo Settings → Pages → Source: GitHub Actions
  - Confirm `docs.yml` workflow deploys on merge to `main`
- [ ] Verify the live docs URL: `https://manavghosh.github.io/api2mcp/`
- [ ] Add the docs URL to the GitHub repository "Website" field
- [ ] Add the docs URL to `pyproject.toml` under `[project.urls]`

---

## 9. Code Quality Gates

- [ ] All existing tests pass: `pytest` (currently 1954 passed, 81.65% coverage)
- [ ] Coverage is above 80% (already met)
- [ ] `ruff check src/` passes with zero errors
- [ ] `mypy src/` passes (or known ignores are documented)
- [ ] `bandit -r src/` security scan passes
- [ ] No hardcoded secrets, API keys, or internal URLs in the codebase
- [ ] Run `git log --all --oneline` and confirm no sensitive data in commit history

---

## 10. Security Hygiene

- [ ] `SECURITY.md` is present with a private reporting path (GitHub private vulnerability reporting or a security email)
- [ ] Enable GitHub's "Private vulnerability reporting" in repo Settings → Security
- [ ] Enable Dependabot alerts (Settings → Security → Dependabot)
- [ ] Enable Dependabot auto-updates for dependencies
- [ ] Enable GitHub secret scanning (Settings → Security → Secret scanning)
- [ ] Remove any `.env` files or secrets from git history (use `git-filter-repo` if needed)
- [ ] Add `.env*` and `*.pem` to `.gitignore`

---

## 11. Community Building

- [ ] Write and publish an announcement blog post (dev.to, Hashnode, or personal blog)
- [ ] Post on Reddit: r/Python, r/MachineLearning, r/LocalLLaMA, r/programming
- [ ] Post on Hacker News: "Show HN: API2MCP — convert any REST API to an MCP server"
- [ ] Post on X/Twitter with demo GIF or screenshot
- [ ] Submit to awesome-mcp or similar curated lists
- [ ] Create a Discord server or point to GitHub Discussions as the community hub
- [ ] Write a "good first issue" label and tag 5–10 beginner-friendly issues
- [ ] Respond to all initial issues/PRs within 48 hours to build momentum

---

## 12. Versioning & Release Process

- [ ] Adopt Semantic Versioning: `MAJOR.MINOR.PATCH` (e.g., `0.1.0`)
- [ ] Tag releases in git: `git tag v0.1.0`
- [ ] Write release notes for each version in `CHANGELOG.md`
- [ ] Create a GitHub Release for each tag (release notes auto-populate from CHANGELOG)
- [ ] Decide on a release cadence (e.g., monthly minor releases, patch releases as needed)

---

## 13. Long-Term Maintenance

- [ ] Add at least one co-maintainer with write access
- [ ] Document the release process in `GOVERNANCE.md`
- [ ] Set up a project roadmap (GitHub Projects board or `ROADMAP.md` at repo root)
- [ ] Define what "done" means for a contribution (tests + docs required)
- [ ] Establish a policy for breaking changes (deprecation notices, major version bumps)
- [ ] Schedule a periodic dependency audit (quarterly)

---

## Quick Reference — File Locations

| File | Destination in repo |
|------|---------------------|
| `open-source/LICENSE` | `LICENSE` |
| `open-source/CONTRIBUTING.md` | `CONTRIBUTING.md` |
| `open-source/CODE_OF_CONDUCT.md` | `CODE_OF_CONDUCT.md` |
| `open-source/SECURITY.md` | `SECURITY.md` |
| `open-source/CHANGELOG.md` | `CHANGELOG.md` |
| `open-source/GOVERNANCE.md` | `GOVERNANCE.md` |
| `open-source/SUPPORT.md` | `SUPPORT.md` |
| `open-source/.github/*` | `.github/*` |

---

## Copyright Claims

### Can you claim this as open source if it was built with AI assistance?

Yes — but understand what you are and are not claiming.

**What you can legitimately claim:**
- The product vision — you defined what API2MCP should do
- The architecture decisions — you directed the structure, patterns, and design choices
- The requirements and specifications — you wrote or approved the PRD, specs, and task breakdowns
- The project direction — every feature, every constraint, every design trade-off was your decision
- The integration and curation — you assembled and validated a coherent working system

This is no different from a software architect who directs a team of engineers. The architect is considered the author of the system.

### The key legal distinction

- "AI wrote this entirely without my direction" → weak copyright claim
- "I directed every aspect of the design and the AI was my tool" → strong copyright claim

This project falls clearly into the second category — it has a PRD, specs, task breakdowns, architectural decisions, and months of directed development. That constitutes substantial human authorship.

The US Copyright Office (as of 2024) requires human authorship for copyright registration. Purely AI-generated content without human creative input cannot be registered. However, AI-assisted work with significant human direction can be.

### Checklist for copyright and attribution

- [ ] Add `LICENSE` (MIT) to the repository root — this is the primary legal instrument
- [ ] Use SPDX license identifiers in source files instead of verbose copyright headers:
  ```
  # SPDX-License-Identifier: MIT
  # Copyright (c) 2026 Manav and contributors
  ```
- [ ] Add an AI assistance acknowledgement to the README:
  ```
  This project was developed with the assistance of Claude (Anthropic).
  ```
- [ ] Do not claim you personally wrote every line of code — this is unnecessary and untrue
- [ ] If you intend to monetise this project or build a company around it, consult an IP attorney in your jurisdiction before publishing
- [ ] Be transparent if asked — AI-assisted development is increasingly normal and respected in the open source community; honesty strengthens rather than weakens your credibility

### What to avoid

- Do not assert in any public statement that every line was hand-written
- Do not remove or obscure the AI assistance if directly asked about the project's origins
- Do not reproduce large verbatim blocks from other copyrighted works (the AI may have trained on them, but direct reproduction is a separate issue)

### Bottom line

You can publish API2MCP as open source under MIT. You directed the entire project — the vision, architecture, specifications, and every design decision. Claude was your implementation tool, the same way a code editor or a framework is a tool. The project is legitimately yours to open source.
