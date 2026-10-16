# Ubuntu Voice Assistant

A planned private, local voice assistant for Ubuntu using Qwen3-4B through
llama.cpp, faster-whisper, Piper, FastAPI and React/Tauri 2.

The repository contains a tested controller foundation and a local health API.
The recorded-audio Whisper → Qwen → Piper pipeline has also been tested separately
on the target laptop, including a restart with Wi-Fi disabled. Capture, VAD and
Whisper now connect through a local transcription diagnostic and an authenticated
React push-to-talk preview. Qwen and Piper are not yet connected to the new controller.
The Tauri shell builds and renders on the laptop, with transcripts visible in the UI;
the remaining hardware acceptance checks are pending. See the
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
uv run --locked ruff check backend
uv run --locked ruff format --check backend
uv run --locked mypy
uv run --locked pytest -W error
```

`.python-version` selects Python 3.12; `pyproject.toml` pins uv and declares
dependencies; `uv.lock` records exact resolutions. uv creates `.venv` automatically.
Use `uv add <package>` or `uv add --dev <package>` for reviewed dependency changes,
and include both the manifest and lockfile in the change. Use `uv run` for
backend commands. Node/npm and Cargo manage the frontend and Tauri dependencies;
see the [desktop development guide](docs/desktop-development.md).

## Run the Phase 2 health server

```bash
uv run --locked python -m voice_assistant
```

The supported launcher binds to `127.0.0.1:8765`. It does not load models or open
audio devices. In another terminal:

```bash
curl --include http://127.0.0.1:8765/health
curl --include http://127.0.0.1:8765/ready
```

`/health` returns 200 while the process is serving. `/ready` deliberately returns
503 with `not_configured` component statuses until real adapters are wired. Stop
the server with Ctrl+C. No microphone controls, transcripts or tool execution are
exposed through HTTP at this stage.

The [architecture and lifecycle guide](docs/architecture.md) describes the
controller's typed interfaces, event schemas, cancellation and error recovery.
Tests exercise complete simulated turns with fake adapters and synthetic audio;
they require no GPU, model downloads or microphone access.

## Phase 3 audio development

Phase 3 adds isolated microphone capture, input-device selection, recording limits,
16 kHz normalization, Silero silence filtering and local CPU/int8 Whisper. Run an
explicit five-second microphone-to-transcript check with your current input index:

```bash
uv run --offline --locked python -m voice_assistant.transcribe --device 23 --seconds 5
```

The model loads before capture opens. Speak when `State: listening` appears.
Ctrl+C cancels and releases resources. This diagnostic displays the transcript in
your terminal and writes no recordings or history files. See
[Ubuntu audio setup](docs/setup-ubuntu.md) for device enumeration, local model
requirements, silence/recovery checks and limitations. The health server remains
read-only. To try the authenticated hold-to-talk preview, follow the
[desktop development guide](docs/desktop-development.md). It includes connection
setup, native prerequisites and the remaining manual acceptance checks.

## GitHub Actions

The `CI` workflow runs on pull requests, pushes to `main`, and manual dispatch.
It installs locked dependencies, validates YAML and workflow security, and runs
backend linting, formatting, strict type checks and tests. Actions
are pinned to commit hashes; the token has read-only repository access and
checkout credentials are not persisted. No secrets are required.

The workflow becomes available after these files are committed and pushed to
GitHub with Actions enabled. Manual dispatch requires the workflow on the default
branch. After its first successful run, `Repository checks` can be selected as a
required check in a branch ruleset. These repository settings have not been changed.

The `Desktop checks` job installs locked npm dependencies, tests controls, builds
the frontend and checks the native Tauri shell with Rust 1.98.1 and Ubuntu development
libraries. Its first hosted run is pending. Hosted CI uses fake adapters and synthetic fixtures; real GPU, microphone, playback and
offline acceptance checks remain target-laptop verification. Delivery automation is deferred until
the first working milestone; this workflow does not publish releases.

See [development tooling notes](docs/development-tooling.md) for licenses,
network access and the CI/CD roadmap.
