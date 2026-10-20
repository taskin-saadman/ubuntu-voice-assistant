# Backend dependency decisions

Phase 2 uses Python 3.12 and uv. Exact resolutions are in `uv.lock`.

| Dependency | Purpose | Upstream license |
| --- | --- | --- |
| Pydantic | Validate immutable component data and UI/API schemas | MIT |
| FastAPI | Thin health/readiness HTTP routes | MIT |
| Uvicorn | Local ASGI server | BSD-3-Clause |
| HTTPX (development) | In-process ASGI endpoint tests | BSD-3-Clause |
| pytest | Backend tests | MIT |
| pytest-asyncio | Async cancellation and responsiveness tests | Apache-2.0 |
| Ruff | Python linting and formatting | MIT |
| mypy | Strict static type checks | MIT |
| uv_build | Editable installation of `backend/src/voice_assistant` | MIT OR Apache-2.0 |

The licenses were checked against upstream PyPI project metadata before adding
these dependencies. Pydantic is already transitive through existing tooling;
declaring it directly records the backend's own requirement. No additional
inference, audio, logging or workflow framework is introduced.

Package installation uses PyPI. Phase 2 tests use synthetic data and fake engines,
require no models or microphone, and make no external API calls. The local health
server performs no downloads or engine initialization. Inference dependencies
remain those verified in [verification.md](verification.md); distribution of Piper
and voices still requires the review recorded there.

FastAPI's resolved dependencies include the OpenTelemetry API interface. No
OpenTelemetry SDK, exporter, instrumentation or remote telemetry is configured
by this application; the `standard`/`opentelemetry` extras are not installed.

Sources: [Pydantic](https://pypi.org/project/pydantic/),
[FastAPI](https://pypi.org/project/fastapi/), [Uvicorn](https://pypi.org/project/uvicorn/),
[HTTPX](https://pypi.org/project/httpx/), [pytest](https://pypi.org/project/pytest/),
[pytest-asyncio](https://pypi.org/project/pytest-asyncio/),
[Ruff](https://pypi.org/project/ruff/), [mypy](https://pypi.org/project/mypy/),
[uv_build](https://pypi.org/project/uv-build/).

## Phase 3 microphone capture

`sounddevice >=0.5.6,<0.6` (MIT) provides Python access to PortAudio input devices.
It is the audio library selected in the implementation plan; the existing engines
do not provide device capture. Its locked transitive dependencies are CFFI 2.1.1
(MIT-0) and pycparser 3.11 (BSD-3-Clause), checked against upstream package metadata.
Linux also needs the system `libportaudio2` library (PortAudio's permissive license).
No OS package is installed by uv or application startup.

Resampling reuses PyAV 18.1.0, already locked for faster-whisper, rather than adding
another audio conversion dependency. The adapter imports sounddevice only in its
private worker after an explicit capture or enumeration request. It makes no
network requests or recording-file writes. Package downloads still use PyPI, and
OS package installation uses the configured Ubuntu repositories.

Sources: [sounddevice metadata](https://pypi.org/project/sounddevice/0.5.6/),
[CFFI metadata](https://pypi.org/project/cffi/2.1.1/),
[pycparser metadata](https://pypi.org/project/pycparser/3.11/),
[sounddevice installation](https://python-sounddevice.readthedocs.io/en/latest/installation.html),
[PortAudio license](https://www.portaudio.com/license.html).

## Phase 3 VAD and transcription

The existing faster-whisper 1.2.1 dependency provides Whisper and its bundled
Silero VAD model; no new VAD package or model download was introduced. NumPy is
now declared directly because the adapter converts PCM to the float32 arrays
expected by these engines. Its existing locked resolution remains 2.5.4. Upstream
metadata declares `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`, including
bundled components; distribution must retain applicable notices.

The private speech worker sets Hugging Face offline/telemetry-disable flags before
inference imports and disables ONNX Runtime telemetry. It requires a local model
directory with `model.bin`, `config.json`, `tokenizer.json`, and vocabulary files.
In particular, the tokenizer check prevents faster-whisper's missing-tokenizer
fallback to `Tokenizer.from_pretrained`. There is no automatic download path in
application startup. These configuration measures are not a network-traffic audit.

Sources: [NumPy 2.5.4 metadata](https://pypi.org/project/numpy/2.5.4/),
[faster-whisper usage and VAD](https://github.com/SYSTRAN/faster-whisper#usage),
[pinned tokenizer loading](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py),
[pinned bundled VAD](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/vad.py).

## Phase 3 authenticated desktop session

| Dependency | Purpose | Reviewed upstream license |
| --- | --- | --- |
| websockets 17.2 | Uvicorn's explicit Sans-I/O WebSocket implementation | BSD-3-Clause |
| AnyIO 4.15.1 | Protect microphone cleanup against ASGI cancellation; already transitive through FastAPI | MIT |
| React / React DOM 19.3.1 | Desktop view and accessible controls | MIT |
| TypeScript 7.0.2 | Strict frontend type checking | Apache-2.0 |
| Vite 8.3.4 / React plugin 6.1.2 | Local development server and frontend assets | MIT |
| Vitest 5.0.5 / jsdom 29.1.1 / Testing Library React 16.3.3 | DOM, gesture and connection tests without hardware | MIT |
| React/DOM/Node type definitions | Type checking | MIT |
| Tauri CLI 2.12.3, tauri 2.12.4, tauri-build 2.7.3 | Native Linux window around the local interface | MIT OR Apache-2.0 |

Direct npm dependencies are exact-pinned; `desktop/package-lock.json` and
`desktop/src-tauri/Cargo.lock` lock the full graphs. Python remains managed by uv.
Node 22.22.1 and Rust 1.98.1 are the local/CI baselines. jsdom 29 is selected for
this Node version. No frontend WebSocket or schema framework was added: browser
WebSocket and a bounded protocol parser cover this small transport.

npm installation contacts the npm registry; Cargo contacts crates.io; Rust
installation contacts Rust's distribution servers; apt contacts Ubuntu repositories.
GitHub Actions installs these on its disposable runner. The application does not
install OS dependencies or download models. Vite's development server and HMR use
loopback only; production assets bundle local code, styles and system fonts.
The browser client only opens `ws://127.0.0.1:8765/session`. Native Tauri capabilities
are empty, with no shell, filesystem, updater or telemetry plugins enabled.
Distribution still requires a complete transitive/system-library license review;
no release packaging or publishing is enabled here.

Sources: [websockets](https://pypi.org/project/websockets/17.2/),
[AnyIO](https://pypi.org/project/anyio/4.15.1/),
[React license](https://github.com/facebook/react/blob/main/LICENSE),
[TypeScript license](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt),
[Vite license](https://github.com/vitejs/vite/blob/main/LICENSE),
[Vitest license](https://github.com/vitest-dev/vitest/blob/main/LICENSE),
[jsdom license](https://github.com/jsdom/jsdom/blob/main/LICENSE.txt),
[Testing Library license](https://github.com/testing-library/react-testing-library/blob/main/LICENSE),
[Tauri licenses](https://github.com/tauri-apps/tauri),
[Tauri Linux prerequisites](https://v2.tauri.app/start/prerequisites/).

## Phase 4 local Qwen client

HTTPX is promoted from the development group to runtime dependencies for asynchronous
loopback HTTP and streamed responses. The constraint remains `>=0.28.1,<0.29`, the
locked version remains 0.28.1, and its reviewed license remains BSD-3-Clause. This
reuses the installed package; no OpenAI SDK, SSE package or tokenizer package is
added. The existing llama.cpp server supplies its own model-specific chat template
and tokenizer. Its pinned source commit is recorded in `verification.md`.

The client only constructs `http://127.0.0.1:<port>` URLs, ignores proxy environment
variables and never follows redirects. Its requests target health, template,
tokenization and chat-completion endpoints. Models are still loaded from local
files by the separately launched server; the application has no cloud fallback
or download path. For normal use, launch llama.cpp with the documented offline and
logging-disable flags. The client stores no audio or conversation files.

Protocol decisions were checked against the installed pinned llama.cpp source and
[server documentation at that revision](https://github.com/ggml-org/llama.cpp/blob/620d2225cc436ab0b001e3200e590e3b286ef9ab/tools/server/README.md).
HTTPX behavior and licensing are described in the [upstream repository](https://github.com/encode/httpx/tree/0.28.1).


## Phase 5 Piper and playback

No dependency or lockfile change is needed. The adapters reuse locked Piper 1.8.0,
ONNX Runtime, sounddevice/PortAudio, NumPy and PyAV. Piper provides local synthesis;
sounddevice provides selected-device output; PyAV supplies resampling. The installed
Piper metadata declares `GPL-3.0-or-later`. Its engine and bundled components require
appropriate distribution review before packaging; this phase does not publish builds.

The selected `en_US-ljspeech-medium` model and local MODEL_CARD were inspected.
The [upstream voice card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD)
identifies the LJ Speech dataset as public domain. This dataset statement alone is
not a complete distribution-license audit of the trained artifact and application.
Keep the voice-specific review open before distribution, as required by AGENTS.md.

Implementation was checked against the installed pinned Piper source and
[Piper's Python API](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md),
and against the [sounddevice stream contract](https://python-sounddevice.readthedocs.io/en/latest/api/streams.html).
Piper loads explicit local assets and disables the optional Arabic resource loader;
unsupported phonemizer configurations fail instead of fetching assets. ONNX Runtime
telemetry is disabled before session creation. Playback uses local PortAudio devices.
Neither adapter adds a network request, cloud fallback or file-output path. Existing
package/model download sources remain setup-time operations, separate from runtime.
