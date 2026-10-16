# Development tooling and CI/CD

## Dependency decisions

| Tool | Purpose | License/source |
| --- | --- | --- |
| uv | Manage Python, environments, dependencies and locked execution | [MIT or Apache-2.0](https://github.com/astral-sh/uv) |
| yamllint | Validate YAML syntax, duplicate keys and formatting | [GPL-3.0-or-later](https://github.com/adrienverge/yamllint/blob/master/LICENSE) |
| zizmor | Analyze GitHub Actions for workflow security issues | [MIT](https://github.com/zizmorcore/zizmor) |
| actions/checkout | Retrieve repository source in CI | [MIT](https://github.com/actions/checkout/blob/main/LICENSE) |
| astral-sh/setup-uv | Install the project's pinned uv version in CI | [MIT](https://github.com/astral-sh/setup-uv/blob/main/LICENSE) |

These are development tools, not assistant runtime dependencies. yamllint checks
general YAML correctness; zizmor checks workflow security. Neither replaces a
successful GitHub Actions run or application tests. Resolved Python dependencies
and hashes are recorded in `uv.lock`; review transitive licenses before distributing
any tooling. No assistant engine or voice distribution is introduced here.

Python 3.12 is the initial compatibility baseline for the planned native inference
dependencies. Verify their actual wheel/runtime compatibility in the prerequisite
phase. The Python minor version is constrained; patch releases can advance.
uv is pinned exactly in `pyproject.toml`, which setup-uv reads automatically.

## Network and privacy

Setup downloads uv and managed Python from upstream release infrastructure and
Python packages from PyPI and its file hosts. GitHub Actions checks out repository
source and retains workflow logs on GitHub. The project follows the official
[uv GitHub Actions integration](https://docs.astral.sh/uv/guides/integration/github/).

zizmor runs with `--offline` to avoid GitHub API queries. Dependency setup still
requires networking on a fresh machine; it is separate from the assistant's future
offline runtime requirement. CI downloads no voice or LLM models and handles no
user audio, transcripts, credentials or conversation histories. Dependency caching
is disabled for the small initial tool set.

## CI/CD progression

1. **Now:** locked uv tooling, strict YAML validation and workflow security checks
   on pull requests and main, with bounded runtime and read-only permissions.
2. **Backend implementation:** add Ruff, mypy and pytest to the uv development
   group, then require lint, type and unit/integration checks. Use fake engine
   adapters so PR jobs do not require downloaded models or GPU access.
3. **Desktop implementation:** add `npm ci`, TypeScript checks, UI tests and a
   production frontend build. Add Cargo formatting, linting and checks with the
   required Ubuntu Tauri libraries. Keep lockfiles under version control.
4. **First working milestone:** record real hardware and offline acceptance results.
   Revisit downloadable artifacts and GitHub Releases then. Delivery is deferred
   by user preference; no release workflow or publishing credentials are configured.

Add checks in the same changes that introduce their components; do not hide missing
tests behind successful placeholder jobs. Keep untrusted PR code on hosted runners,
not on the user's laptop. Refresh action SHA pins and uv/tool dependencies through
reviewed changes. Select required branch checks after observing their first hosted
run; configuring branch rules and publishing are separate actions.

`AGENTS.md` and `PLAN.md` currently remain local because the existing `.gitignore`
excludes them. CI does not depend on either file.
