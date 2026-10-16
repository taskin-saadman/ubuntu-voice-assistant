# Ubuntu Voice Assistant

A planned private, local voice assistant for Ubuntu using Qwen3-4B through
llama.cpp, faster-whisper, Piper, FastAPI and React/Tauri 2.

The repository currently contains development tooling, locked engine dependencies
and verification documentation. The recorded-audio Whisper → Qwen → Piper pipeline
has been tested on the target laptop, including a restart with Wi-Fi disabled.
There is no runnable push-to-talk application yet. See the
[verification results and limitations](docs/verification.md).

## Development with uv

Use **uv 0.12.18** for Python environments, dependencies and commands. Follow the
[official uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/)
if it is not installed. Run these commands from the repository root:

```bash
uv python install
uv sync --locked --dev
uv run --locked yamllint --strict .github .yamllint.yaml
uv run --locked zizmor --offline --no-progress .github/workflows
```

`.python-version` selects Python 3.12; `pyproject.toml` pins uv and declares
dependencies; `uv.lock` records exact resolutions. uv creates `.venv` automatically.
Use `uv add <package>` or `uv add --dev <package>` for reviewed dependency changes,
and include both the manifest and lockfile in the change. Use `uv run` for future
backend commands. Node/npm and Cargo will continue to manage the frontend and
Tauri dependencies when those components exist.

## GitHub Actions

The `CI` workflow runs on pull requests, pushes to `main`, and manual dispatch.
It installs locked tooling, validates YAML and checks workflow security. Actions
are pinned to commit hashes; the token has read-only repository access and
checkout credentials are not persisted. No secrets are required.

The workflow becomes available after these files are committed and pushed to
GitHub with Actions enabled. Manual dispatch requires the workflow on the default
branch. After its first successful run, `Repository checks` can be selected as a
required check in a branch ruleset. These repository settings have not been changed.

Application linting, type checks, tests and build jobs will be added alongside the
backend and desktop implementations. Hosted CI will use fake adapters and
synthetic/licensed fixtures; real GPU, microphone, playback and offline acceptance
checks remain target-laptop verification. Delivery automation is deferred until
the first working milestone; this workflow does not publish releases.

See [development tooling notes](docs/development-tooling.md) for licenses,
network access and the CI/CD roadmap.
