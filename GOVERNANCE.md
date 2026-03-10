# Governance

This document describes how API2MCP is governed and how decisions are made.

---

## Project Structure

API2MCP is an open source project maintained by its author and a growing group of
community contributors. It currently operates under a **Benevolent Dictator For Now
(BDFN)** model — common for early-stage open source projects — with the intent to
transition to a broader maintainer committee as the community grows.

---

## Roles

### Author / Lead Maintainer

- Sets the project vision and roadmap
- Has final say on all technical and policy decisions
- Merges pull requests
- Publishes releases to PyPI
- Manages GitHub repository settings and access

### Maintainers

Maintainers are trusted community contributors who are granted write access to the
repository. They can:

- Review and approve pull requests
- Triage and label issues
- Close stale issues
- Participate in roadmap discussions

To become a maintainer, a contributor should have:

- Merged at least 5 meaningful pull requests
- Demonstrated familiarity with the codebase
- Been active in the community for at least 3 months

Nomination is made by the Lead Maintainer or an existing Maintainer.

### Contributors

Anyone who opens an issue, submits a pull request, improves documentation, or
participates in Discussions is a contributor. Contributors are listed in
`CHANGELOG.md` and GitHub's contributor graph.

---

## Decision Making

### Day-to-day decisions

Routine decisions (bug fix approach, minor API design, documentation structure) are
made by whoever is reviewing the pull request. Any maintainer may merge a PR once it
has one approving review and all CI checks pass.

### Significant decisions

Changes that affect public API contracts, the IR schema, transport protocols, or the
orchestration graph interfaces require discussion before implementation:

1. Open a GitHub Discussion or a design issue labelled `design`
2. Allow at least 5 business days for community input
3. The Lead Maintainer makes the final call

### Breaking changes

Breaking changes (requiring a `MAJOR` version bump) must:

1. Be discussed in a public issue or Discussion
2. Have a deprecation notice in the prior minor release where possible
3. Be documented clearly in `CHANGELOG.md`
4. Be approved by the Lead Maintainer

---

## Pull Request Policy

- All PRs require at least **1 approving review** from a Maintainer
- All CI checks must pass before merge
- PRs from first-time contributors require review by a Maintainer before CI is allowed to run
- The author of a PR should not merge their own PR (except the Lead Maintainer for minor fixes)
- PRs that have been open for 30 days without activity will be marked `stale` and closed after a further 14 days

---

## Release Process

1. Maintainer creates a release branch `release/vX.Y.Z`
2. `CHANGELOG.md` is updated with the release date and notes
3. Version is bumped in `pyproject.toml`
4. PR is merged to `main`
5. Git tag `vX.Y.Z` is pushed — this triggers the `release.yml` GitHub Actions workflow
6. Workflow publishes to PyPI via OIDC trusted publisher
7. GitHub Release is created with the CHANGELOG entry as release notes

---

## Code of Conduct Enforcement

The Lead Maintainer is responsible for enforcing the [Code of Conduct](CODE_OF_CONDUCT.md).
Reports are handled privately and confidentially. The process follows the Contributor
Covenant enforcement guidelines.

Possible outcomes range from a private warning to a permanent ban from the project,
depending on the severity of the incident.

---

## Amendments

This governance document may be updated by the Lead Maintainer at any time. Significant
changes will be announced via a GitHub Discussion before taking effect.

---

## Evolving Governance

As API2MCP grows, the goal is to transition to a more distributed governance model:

- **Phase 1 (now):** BDFN — Lead Maintainer makes decisions, community contributes
- **Phase 2 (3–5 active maintainers):** Maintainer Committee with majority vote for significant decisions
- **Phase 3 (mature project):** Foundation or CNCF-style governance with elected steering committee
