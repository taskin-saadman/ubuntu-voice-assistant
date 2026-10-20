# Initial local engine verification

Verification date: 2026-10-17 (Australia/Sydney).

## Scope and evidence

The user ran the checks on the target Ubuntu laptop and supplied terminal output.
The results below summarize that output and the user's listening and Wi-Fi status
reports. They establish a working recorded-audio pipeline, not a completed
push-to-talk application or a sustained-performance benchmark.

No recordings, transcripts, generated answers, raw terminal logs, model binaries
or personal filesystem paths are included in this report.

## Hardware and toolchain

| Component | Observed configuration |
| --- | --- |
| Operating system | Ubuntu 26.04.1 LTS |
| CPU | Intel Core i7-11800H (project target; CPU identification was not captured in these logs) |
| System RAM | `free -h` reports 14 GiB usable total; project target is 16 GB installed |
| GPU | NVIDIA GeForce RTX 3050 Ti Laptop GPU, 4096 MiB VRAM |
| NVIDIA driver | 595.91.07 |
| CUDA toolkit | 12.4, NVCC 12.4.131 |
| Build compilers | GCC/G++ 13.4.0, explicitly selected for llama.cpp |
| System default compilers | GCC/G++ 15.2.0; not used for the CUDA build |
| CMake | 4.2.3 |
| Git | 2.53.0 |
| Python project management | uv 0.12.18, Python 3.12 project constraint |

`nvidia-smi` reported CUDA 13.2 as the driver's supported CUDA version; the
installed compiler reported toolkit 12.4. These are different measurements.
A small CUDA program compiled with G++ 13.4 and returned the expected GPU result
of 42. This observed success does not imply that Ubuntu 26.04 is a validated
platform for every CUDA 12.4 workload.

## Models and runtime settings

### Qwen through llama.cpp

- Source release: `v0.7.0`.
- Source commit: `620d2225cc436ab0b001e3200e590e3b286ef9ab`.
- Binary reports: `0.7.0-dev (build 1, commit 620d222)`, GNU 13.4.0, Linux x86_64.
- CUDA build enabled, with native GPU architecture and G++ 13 as CUDA host compiler.
- Both `llama-cli` and `llama-server` built successfully; device listing found CUDA0.
- Model: `Qwen/Qwen3-4B-GGUF`, `Qwen3-4B-Q4_K_M.gguf`.
- Model revision: `bc640142c66e1fdd12af0bd68f40445458f3869b`.
- Model SHA-256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`.
- The user confirmed that the downloaded model checksum matched.

Server settings used for the combined tests:

```text
--alias qwen3-4b
--host 127.0.0.1
--port 8080
--ctx-size 4096
--parallel 1
--gpu-layers auto
--fit on
--fit-target 512
--batch-size 256
--ubatch-size 128
--jinja
--chat-template-kwargs '{"enable_thinking":false}'
--offline
--no-webui
```

Requests used the local `/v1/chat/completions` endpoint, temperature 0.7,
non-streaming responses and a 160-token output limit for combined tests. A short
system instruction established on-device operation and requested brief answers.
The diagnostic rejected empty answers, reasoning markup and unfinished responses.

### Speech recognition

- Engine: faster-whisper 1.2.1.
- Model: `Systran/faster-whisper-small.en`.
- Model revision: `d1d751a5f8271d482d14ca55d9e2deeebbae577f`.
- Device/compute type: CPU/int8; eight CPU threads, one worker.
- Transcription: English, beam size 5, VAD enabled, previous-text conditioning disabled.
- Input: a ten-second user-recorded WAV; transcription was fully consumed before timing ended.
- PyAV 19.0.1 initially failed on the removed `metadata_errors` argument.
  Constraining PyAV to `>=18,<19` resolved the environment to 18.1.0.
  Synthetic mono/stereo decoding and the real recording then passed. See
  [dependency compatibility](dependency-compatibility.md).

### Speech synthesis and playback

- Engine: Piper (`piper-tts` 1.8.0).
- Voice: `en_US-ljspeech-medium`, loaded explicitly on CPU (`use_cuda=False`).
- Voice repository: `rhasspy/piper-voices`.
- Voice revision: `c10ece1aade47bb51c153c893d14e5bf8e5b7117`.
- Expected ONNX SHA-256: `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`.
- Output: mono, signed 16-bit PCM WAV at 22050 Hz; playback through `aplay`.
- The user confirmed clear, complete playback during the independent Piper test.
- Independent Piper timing output and a separate voice checksum result were not
  supplied; combined synthesis timings are recorded below.

At report preparation, the local environment reported Python 3.12.14,
CTranslate2 4.8.3 and ONNX Runtime 1.31.0 in addition to the engine versions above.
Exact Python package resolutions are recorded in the repository's `uv.lock`.

## Independent results

| Check | Result |
| --- | --- |
| CUDA compilation/execution | Expected GPU result returned |
| llama.cpp build/device discovery | Both executables built; NVIDIA GPU detected |
| Qwen inference | Completed a short response; about 57.1 generated tokens/s, 0.998 s generation and 0.046 s prompt processing in one request |
| Whisper loading | 0.57 s in the successful transcription run |
| Whisper transcription | 10.00 s recording transcribed in 1.25 s, then 1.14 s |
| Piper generation/listening | User reported hearing the full sentence clearly |

The first Qwen prompt used the ambiguous phrase "local voice assistant" and
received a geographically focused explanation. The combined test clarified
on-device operation in the system instruction. No broader response-quality
evaluation has been performed.

## Combined recorded-audio pipeline

The diagnostic loaded Whisper and Piper once per process, then performed two
sequential turns against a running llama-server:

```text
Recorded WAV → Whisper → local Qwen HTTP request → Piper → aplay
```

Temporary synthesized WAV files were removed on exit. The diagnostic did not
capture live microphone input, execute model-proposed tools or retain conversation
history between turns. All three models remained loaded for the final memory
snapshot in each run.

| Run | Whisper + Piper load | Turn | Whisper | Qwen request | Piper | Processing before playback |
| --- | --- | --- | --- | --- | --- | --- |
| Initial combined run | 1.60 s | 1 | 1.19 s | 0.59 s | 0.27 s | 2.06 s |
| Initial combined run | 1.60 s | 2 | 1.12 s | 0.53 s | 0.27 s | 1.92 s |
| Wi-Fi off; llama-server retained | 1.58 s | 1 | 1.14 s | 0.62 s | 0.24 s | 2.00 s |
| Wi-Fi off; llama-server retained | 1.58 s | 2 | 1.13 s | 0.47 s | 0.21 s | 1.81 s |
| Wi-Fi off; llama-server restarted | 1.63 s | 1 | 1.15 s | 0.61 s | 0.25 s | 2.02 s |
| Wi-Fi off; llama-server restarted | 1.63 s | 2 | 1.13 s | 0.47 s | 0.23 s | 1.84 s |

All six turns completed without a reported pipeline error. The playback command
returned successfully in each turn. Times are printed to two decimal places, so
rounded stage values may not sum exactly to the printed total.

Timing excludes recording duration, model loading and speaker playback. It measures
complete response generation and synthesis, not streaming time to first token or
first audible sample. The repeated input can benefit from Qwen's prompt cache,
and answer lengths vary. These six samples do not establish median/p95 latency
over representative workloads.

### Memory snapshots with all three models loaded

| Run | Total GPU memory used | llama-server GPU memory | Available system RAM | Swap used |
| --- | --- | --- | --- | --- |
| Initial combined run | 3100 / 4096 MiB | 3072 MiB | 7.8 GiB | 48 MiB |
| Wi-Fi off; server retained | 3100 / 4096 MiB | 3072 MiB | 7.9 GiB | 48 MiB |
| Wi-Fi off; server restarted | 3100 / 4096 MiB | 3072 MiB | 8.0 GiB | 48 MiB |

These are end-of-run snapshots, not peak memory measurements. GPU use is observed;
the exact offloaded layer count was not supplied, so full GPU offload is not claimed.

## Offline evidence and limits

The user reported disabling Wi-Fi, then repeated the test successfully. They then
reported restarting llama-server while Wi-Fi remained off and supplied another
successful two-turn run. A changed server process ID is visible in the supplied
output. Whisper and Piper were also reloaded in a fresh Python process.

The Python runs set `UV_OFFLINE=true`, `HF_HUB_OFFLINE=1` and
`HF_HUB_DISABLE_TELEMETRY=1`, loaded explicit local model paths and used only the
fixed loopback Qwen endpoint. This supports restart and operation with Wi-Fi
disabled and existing assets present. Other network interfaces were not audited,
and no packet capture or outbound-connection audit was performed. This is not
proof that no component attempted an external request.

## Remaining milestone verification

- Live push-to-talk capture, microphone-off behavior and device failures.
- Real-adapter state transitions, cancellation, deadlines and recovery from unavailable engines.
- Tool schema validation, allowlist rejection and confirmation policy tests.
- Integrated engine readiness, authenticated transport and origin restrictions.
- Frontend/Tauri integration and visible errors.
- Twenty consecutive turns, longer/context-heavy prompts, silence and noisy input.
- Representative latency distribution and peak RAM/VRAM monitoring.
- Network observation and loopback-only listener verification for the integrated application.
- Exact GPU offload configuration and reproducible startup documentation.
- Piper engine/voice distribution licensing review before packaging or release.

The engine checks do not mark the complete push-to-talk milestone done.

## Phase 2 controller and API verification

Verified locally on 2026-10-17 with Python 3.12 and the locked uv environment:

| Check | Result |
| --- | --- |
| `uv sync --locked --dev` | Passed |
| Ruff lint and format checks | Passed |
| Strict mypy checks | Passed, 14 source files |
| `PYTHONASYNCIODEBUG=1 uv run --offline --locked pytest -W error` | 49 tests passed |
| Strict YAML lint and offline zizmor workflow checks | Passed |
| `git diff --check` | Passed |
| Live loopback server `/health` | HTTP 200, status `ok` |
| Live loopback server `/ready` | HTTP 503, expected with no configured adapters |
| Live server termination | Exited successfully |

Tests used synthetic audio and fake adapters with controlled failures and delays.
They covered complete turns, silence, cancellation at each stage, deadlines,
cleanup failures, stale controls, microphone-off rejection, event ordering,
bounded memory, safe errors and responsive health requests during pending work.
Hugging Face offline and telemetry-disable flags were also set for the test run.

This satisfies the Phase 2 simulated-turn exit criterion. It does not verify
native worker cancellation, live microphone capture or a real engine turn through
the new controller. No model, microphone or speaker was needed by these tests.
The GitHub Actions workflow now includes these backend checks; a hosted run has
not been observed for this branch. The next implementation phase is push-to-talk
capture and transcription with authenticated UI transport.

## Phase 3, first increment: microphone adapter

Verified locally on 2026-10-17 with Python 3.12.14 and the locked uv environment:

| Check | Result |
| --- | --- |
| Locked development dependency synchronization | Passed |
| Ruff lint and formatting | Passed, 22 Python files |
| Strict mypy | Passed, 22 Python files |
| Full suite with warnings treated as errors and asyncio debug enabled | 86 tests passed |
| Focused audio suite | 35 tests passed |
| YAML lint and offline workflow security checks | Passed |
| Whitespace/diff validation | Passed |
| Actual input-enumeration worker with missing PortAudio | Returned the expected safe prerequisite error |

The capture tests use generated tones, zero-valued PCM and controlled subprocesses.
They verify 8/16/44.1/48 kHz normalization, finite recording limits, overflow and
short-read failures, device closure, single ownership, stale startup cancellation,
malformed/oversized IPC, worker termination and forced kill, lost-release cleanup,
and cancellation of a cleanup waiter. Controller integration tests cover
microphone-off, cancellation during startup/finish, silence through a fake VAD,
recording timeout and reuse after successful cleanup.

These tests exposed and fixed a Phase 2 controller issue: cooperative device
cancellation was being treated as a permanent cleanup failure before its cleanup
window had elapsed. Regression tests verify successful cleanup allows reuse and
a resource operation outliving cleanup still requires restart.

The initial enumeration check did not record audio. At that point, `apt-cache policy`
reported `libportaudio2` was not installed, and no OS packages had been changed.
Subsequent user-run hardware checks are recorded below.
There is no new claim of end-to-end offline voice operation. VAD/Whisper wiring,
authenticated transport and the React/Tauri window remain for later Phase 3
increments; the Phase 3 exit criterion is not yet satisfied.

### User-run capture and cancellation checks

The user supplied terminal output showing installation of `libportaudio2`
19.7.0+git20260206.e1b70d33-0ubuntu1, successful device enumeration, and the
[manual capture check](setup-ubuntu.md) with the built-in analog input selected
as device index 23. Enumeration reported its default sample rate as 48000 Hz.
Indices are session-dependent; enumerate again before selecting an input.

| Check | Observed result |
| --- | --- |
| Three normal captures before interruption | Each returned 2.98 s, 16000 Hz, mono int16 |
| Ctrl+C during a subsequent recording | `CancelledError` followed by `KeyboardInterrupt`; terminal prompt returned |
| Normal capture after interruption | Returned 2.98 s, 16000 Hz, mono int16 |

The traceback is expected from the diagnostic's uncaught keyboard interrupt. Its
`finally` block awaits capture abort, and no cleanup exception was reported. The
successful subsequent capture demonstrates the selected input could reopen.
These observations support real capture, resampling and recovery after interruption;
they do not independently prove that the device indicator cleared or that no worker
remained after cancellation. Microphone-indicator behavior was not reported.

The diagnostic kept audio in memory and printed metadata only. No recordings or
device inventory containing personal identifiers were added to the repository.
Speech quality, live VAD/transcription, startup latency, physical device disconnects
and real-device lost-release behavior remain unverified. `UV_OFFLINE=true` was set,
but this capture check was not a network-traffic audit or a complete voice turn.

## Phase 3, second increment: local VAD and transcription

Verified locally on 2026-10-17 with the locked Python 3.12 environment:

| Check | Result |
| --- | --- |
| Ruff lint/format and strict mypy | Passed, 31 Python files |
| Full suite, warnings as errors, offline flags and asyncio debug enabled | 109 tests passed |
| Speech adapter tests | 17 passed |
| Transcription controller/diagnostic tests | 6 passed |
| Diagnostic `--help` | Passed; no model/device initialization |
| Diagnostic with a nonexistent model directory | Safe initialization error and exit 1; capture never enabled |

Tests cover incomplete model directories (including missing tokenizer files),
bounded settings/IPC, float32 PCM conversion, real bundled-Silero rejection of
generated silence, lazy segment consumption, transcript limits, resident worker
reuse, overlapping requests, malformed replies, forced termination, deadlines and
reload after cancellation. Transcription-only controller tests verify state and
message behavior, silence skipping STT, no LLM/TTS calls, inference cancellation
cleanup and diagnostic shutdown. CI needs no microphone or downloaded Whisper
weights; the Silero model is bundled in the existing faster-whisper dependency.

### Native worker smoke check with synthetic speech

A short nonpersonal sentence was synthesized with the existing local Piper voice
into memory, normalized to 16 kHz PCM, and passed to the new speech adapters. This
check used the downloaded small.en model with CPU/int8, eight threads and one
worker. It did not open the microphone, read personal recordings or write audio files.

| Observation | Result |
| --- | --- |
| Worker startup, Whisper loading and VAD warmup | 0.76 s |
| One second of generated zero-valued PCM | VAD false; standalone transcript empty |
| Piper-generated sentence | VAD true |
| First transcription through the resident worker | Correct sentence, 0.98 s |
| Second transcription through the same worker | Correct sentence, 0.93 s |
| Worker shutdown | Completed successfully |

Transcription timings include IPC and filtering but exclude Piper synthesis and
microphone capture. These are two observations of one synthetic utterance, not a
representative latency distribution or live recognition accuracy measurement.
Offline/telemetry-disable flags were set; no packet capture was performed.

### User-reported microphone-to-transcript acceptance

After receiving the diagnostic instructions, the user confirmed that the microphone
tests passed and worked as expected. This confirms the requested manual checks:

- Spoken input produced a transcript and a completed turn.
- Staying quiet produced `no_speech` without a transcript.
- Ctrl+C during recording, followed by a normal retry, worked as expected.

This is user-reported acceptance of the microphone → VAD → Whisper diagnostic;
no additional terminal output, recordings or transcripts were supplied or committed.
No latency or quantitative recognition-accuracy measurement is inferred from it.
Noisy-room behavior, physical device disconnects, cancellation during inference
and explicit microphone-indicator observations remain separate verification items.

The desktop hold control and authenticated transport are not implemented yet,
so Phase 3's complete exit criterion remains pending. See
[setup-ubuntu.md](setup-ubuntu.md) for the reproducible diagnostic procedure.

## Phase 3, third increment: authenticated desktop transcription preview

Implemented on 2026-10-17. This supersedes the earlier note that transport and the
hold control were not yet implemented; hardware acceptance of the new UI is pending.

Local verification: 127 backend tests and 19 frontend tests passed. Ruff lint/format
and strict mypy passed across 36 Python files; strict TypeScript/build and Rust
format checks passed. The full Python run enabled offline flags, warnings as errors
and asyncio debug. Native compilation remains blocked as described below.

- Backend origin/authentication/ownership tests cover missing or untrusted origins,
  wrong keys, query credentials, a second client, stale release IDs, replayed
  commands, malformed/binary frames, disconnect and missing heartbeat cleanup.
- A stalled model-preparation test verifies that ping acknowledgements continue
  independently. Runtime tests enforce loaded-model and inactive-device rules.
- Frontend tests cover authenticated frames, no token in URL/view/browser storage,
  quick release before acknowledgement, duplicate presses, microphone-off guards,
  disconnect/timeouts, stale snapshots, invalid responses, keyboard repeat,
  pointer release/lost capture, Escape, focus loss and hidden-page cancellation.
- A separate real loopback Uvicorn `websockets-sansio` smoke check authenticated,
  ran a synthetic turn, received its transcript and observed microphone permission
  disabled after disconnect. It used fake engines, no microphone and no model.
- Strict TypeScript and Vite production build passed. Rust formatting passed.
  YAML lint and offline zizmor workflow checks passed.
- `cargo check --locked` was attempted and failed because `dbus-1` development
  metadata was missing. GTK3 and WebKitGTK4.1 development metadata are also absent.
  No OS packages were installed. Native compilation/launch remains unverified.
- Visual browser review was unavailable: the computer-use tool reported no connected
  browser. DOM tests are not a substitute for reviewing the rendered window.

The GitHub desktop job now includes locked frontend tests/build and native Cargo
checking on Ubuntu with system prerequisites. It has not yet run on GitHub.
No release bundle or publication was performed. Full UI-to-microphone acceptance,
visible microphone-indicator cleanup, native focus behavior, reduced-motion visual
review and a Wi-Fi-disabled run remain the checks in
[desktop-development.md](desktop-development.md). The existing terminal microphone
acceptance does not prove these new UI behaviors on the laptop.


### Native build after system prerequisite installation

On 2026-10-17, the user reported installing the requested system development
libraries. Subsequent local checks confirmed WebKitGTK 2.52.6, GTK 3.24.52 and
D-Bus 1.16.2 through pkg-config, resolving the earlier native-build blocker.

| Check | Result |
| --- | --- |
| `npm run build` | Strict TypeScript and Vite build passed |
| `cargo +1.98.1 check --locked --manifest-path desktop/src-tauri/Cargo.toml` | Passed |
| `cargo +1.98.1 build --offline --locked -j 2 --manifest-path desktop/src-tauri/Cargo.toml` | Debug executable compiled and linked successfully |
| `cargo +1.98.1 fmt --manifest-path desktop/src-tauri/Cargo.toml -- --check` | Passed |
| Shared-library resolution for the debug executable | No missing libraries reported by `ldd` |

The exact Rust 1.98.1 toolchain was provisioned by rustup before the checks;
that setup used network access. The subsequent Cargo build used cached crates
with `--offline`, which does not establish offline operation of the running app.
Generated Tauri schema output is now ignored by Git. No application logic changed,
so backend and DOM suites were not repeated after the prior passing runs.

The executable was not launched and no microphone was opened in this verification.
Window appearance, native focus/cancellation behavior, microphone capture and a
Wi-Fi-disabled UI turn still require the manual acceptance procedure in
[desktop-development.md](desktop-development.md). No release was packaged or pushed.

### GTK startup failure from the VS Code Snap environment

The user's subsequent `npm run tauri -- dev` compiled and launched the executable,
then aborted in GLib/GIO because the xsettings schema lacked `antialiasing`.
Inspection found that the executable resolved the system GTK/GDK libraries while
the terminal inherited `GSETTINGS_SCHEMA_DIR` pointing into VS Code Snap revision
268. Other GTK/data search variables also referenced the Snap.

A separate Python ctypes probe called the system `gtk_init_check` without creating
an application window or opening audio devices. Core dumps were disabled for the
probe. Results observed on 2026-10-17:

- Inherited environment: reproduced the exact schema-key error; process exit -6.
- Only `GSETTINGS_SCHEMA_DIR=/usr/share/glib-2.0/schemas`: GTK initialization returned
  true and process exit 0.
- System schema plus system XDG data directories: also passed; the extra override
  was unnecessary for this failure and is not part of the recommended command.

The documented workaround sets the single variable for the Tauri launch. No OS
configuration or application code changed. GTK initialization passing does not
establish that WebKit rendering or the complete native microphone flow works;
those remain the next user acceptance checks.

### Native UI rendering and transcript display

On 2026-10-17, after the schema-only workaround, the user supplied a screenshot
showing WebKit's internal-error page. Inspection still found Snap GTK/GIO module
paths in the inherited terminal environment. The next launch instructions cleared
`GTK_PATH`, `GTK_EXE_PREFIX`, `GTK_IM_MODULE_FILE` and `GIO_MODULE_DIR`, selected
system schemas, and restricted XDG data directories to the system locations.

The user's subsequent screenshot visibly confirms:

- The native Local Voice window renders the React interface instead of the error page.
- The UI reports a local connection and exposes the loaded-model device controls.
- Multiple user transcript entries are displayed in the conversation panel.
- Microphone permission is shown as disabled and the hold button is disabled.

This is screenshot evidence from the target laptop, not an independently observed
recording session. No screenshot or transcript text was copied into the repository.
The combined environment workaround succeeded at rendering; the exact offending
GTK/GIO override was not isolated. The screenshot also shows vertical overflow,
so compact-window layout remains a visual refinement item.

Native pointer/keyboard state timing, silence behavior, Escape/focus-loss cleanup,
physical microphone-indicator observations, retry and Wi-Fi-disabled UI operation
still need explicit acceptance. Qwen replies and Piper playback remain unwired in
this preview. These documentation-only updates were checked with `git diff --check`;
no application logic changed and automated suites were not repeated.

### User acceptance of native silence, cancellation and recovery

On 2026-10-17, the user confirmed that all three requested follow-up checks passed:

- Silence produced a no-speech notice.
- Escape or switching windows stopped recording and cleared Ubuntu's microphone
  indicator.
- Re-enabling the microphone allowed another successful turn.

Together with the preceding native UI screenshot and displayed transcripts, this
records user acceptance of the core Phase 3 push-to-talk transcription flow and
its tested cancellation/recovery behavior. This supersedes the pending status of
these specific checks above. It is user-reported verification, not independently
captured timing or device telemetry.

The confirmation is scoped to the three checks requested immediately beforehand.
Physical-device disconnection, the full keyboard/pointer edge-case matrix, native
reconnect/second-window rejection, repeated-turn measurements and Wi-Fi-disabled
UI operation remain separate acceptance items. Phase 4 connects Qwen conversation;
Phase 5 adds Piper and playback. The complete microphone-to-speaker milestone is
not yet implemented.

No application code changed in this acceptance update. `git diff --check` passed;
automated tests were not repeated for documentation-only changes.

## Phase 4: local Qwen conversation implementation

Implemented on 2026-10-18 on `feat/phase-4-qwen-conversation`. Desktop turns now
continue from transcription into a streamed Qwen answer. Piper playback remains
Phase 5 work. The transcription-only CLI remains available.

Local validation: **176 backend tests and 23 frontend tests passed**. Ruff lint/format,
strict mypy across 42 Python files, TypeScript/frontend build, offline native Cargo
check, Rust formatting, YAML lint and offline zizmor checks passed. The full backend
suite ran with offline flags, asyncio debug and warnings treated as errors. Hosted
CI and native UI acceptance have not run for this branch.

Automated coverage adds fragmented Unicode/SSE parsing, comments and multiline
frames, completion markers, output limits, malformed/unfinished responses, split
reasoning/control markers, tool-call rejection, context fitting and pruning,
malformed tokenizer/template replies, redirects, server failures, timeouts,
cancellation/stream cleanup and retry. Controller/transport tests verify draft
snapshots, finalized-only history, stale callback rejection, silence skipping Qwen,
disconnect cleanup, error recovery and conversation-runtime cleanup. UI tests cover
escaped in-progress text, completed replacement, Stop response, same-sequence draft
updates and draft-size rejection.

### Native checks with the downloaded engines

A temporary server was launched using the existing pinned llama.cpp binary and
Qwen3-4B Q4_K_M model, with 4096 context, one slot, the previously verified GPU-fit
settings, non-thinking template configuration, offline mode and logs disabled.
Only generated prompts/audio were used; no microphone, personal recording or
speaker playback was accessed. Audio and conversation data stayed in memory.
The documented `--reasoning off` startup flag was also tested with a successful
native streaming request. Temporary verification servers were stopped afterward.

| Observation | Result |
| --- | --- |
| Direct native streaming request | Completed; 28 text chunks, 159 answer characters |
| First text callback / complete request in that one sample | 0.07 s / 0.56 s |
| Native HTTP stream cancellation after first text | Cancelled; a subsequent request completed successfully |
| Oversized latest input using the native tokenizer | Rejected before generation with context-limit error |
| Generated 4.93-second utterance → real Silero/Whisper → Qwen → controller history | Correct transcript and relevant completed answer; 1.66 s warm processing |
| Controller state sequence | listening → transcribing → thinking → idle |

An earlier 2.90-second synthetic arithmetic utterance was misrecognized by Whisper.
Qwen answered the incorrect transcript, so the semantic assertion failed even though
the pipeline completed. This is a recognition-quality limitation, not a passing
accuracy test. The longer utterance passed without changing the selected models or
recognition settings. These isolated samples do not establish a latency distribution
or recognition-accuracy rate. Processing timing excludes synthesis, model warmup,
physical capture, UI rendering and playback. Offline flags and cached assets were
used; Wi-Fi was not disabled and no network-traffic audit was performed.

Native Phase 4 UI acceptance is pending: hold-to-answer rendering, follow-up context,
Stop/Escape during generation, server-down/reset/retry and offline restart still need
user checks in `desktop-development.md`. Prior Phase 3 UI acceptance does not verify
these new behaviors. No release bundle or publication is included.

### User acceptance of Phase 4 conversation

On 2026-10-20, the user reported that all checks in the supplied six-part spoken
test script passed:

- A short question produced the expected state sequence, transcript, streamed
  draft and completed answer.
- A follow-up recalled information from an earlier completed turn.
- Stop response and Escape discarded unfinished drafts and disabled the
  microphone; re-enabling it allowed successful new turns.
- Stopping llama.cpp produced a visible error while preserving the transcript.
  Restarting llama.cpp and resetting the assistant allowed a successful retry
  without restarting the Python backend.
- Silence produced a no-speech notice without adding a transcript or answer.

The supplied screenshot independently shows the server-unavailable error,
retained user transcript, microphone-disabled state and Reset assistant control.
It does not independently demonstrate the other reported checks. No screenshot
or conversation content was copied into the repository.

The user also supplied passing local output for all 176 backend tests, 23 frontend
tests, Ruff lint/format, mypy, the TypeScript/Vite build, Rust formatting and Cargo
check. Initial frontend/native commands failed because they were run from the
repository root; rerunning from `desktop/` passed without code changes.

This supersedes the pending status above for the tested Phase 4 conversation,
cancellation and recovery behavior. Wi-Fi-disabled desktop restart, additional
disconnect/focus-loss checks during generation and hosted CI remain unverified
for this phase. Piper playback remains Phase 5 work.

This acceptance update changes documentation only. `git diff --check` passed;
application test suites were not repeated.

## Phase 5: Piper synthesis and selected-device playback

Implemented on 2026-10-20 on `feat/phase-5-piper-playback`. The desktop now wires
complete-answer CPU Piper synthesis and selected-device PortAudio playback after
Qwen. The UI distinguishes Preparing speech from Speaking, offers Stop speaking,
and preserves completed answers on synthesis/playback failure or cancellation.
No dependencies, system configuration, downloaded assets or release workflow were
changed. Phase 4's merge and passing CI were reported by the user before this work.

Local checks passed: **224 backend tests and 29 frontend tests**, Ruff lint/format,
strict mypy across 54 Python files, TypeScript/Vite production build, offline locked
Cargo check and Rust formatting. The full Python suite ran with warnings treated
as errors, asyncio debug and Hugging Face offline flags. Hosted Phase 5 CI has not
run. Documentation-only edits were checked with `git diff --check`.

New tests cover bounded synthesis/PCM schemas, CPU-only/thread-limited engine setup,
missing voice/config, unsupported phonemizers, literal handling of Piper phoneme
markup, resident worker reuse, timeouts, malformed/truncated worker output, delayed
spawn cancellation, forced termination, cancellation-safe cleanup and retry. Playback
tests cover complete-frame rendering, final silence padding, error-buffer silence,
DAC-time start notification, drain completion, device failures and cancellation.
Controller/runtime/transport/UI coverage verifies output selection guards, preserved
answers, preparation/speaking feedback, Stop, disconnect cleanup and retry.

### Native checks

Only synthetic input/text was used; the microphone was not opened. Generated PCM
and conversations stayed in memory. Existing downloaded models and the default
system output were used; no output recordings or screenshots were saved.

| Check | Observed result |
| --- | --- |
| Piper cold synthesis of a two-sentence test | 4.73 s mono audio at 22050 Hz; 1.68 s synthesis including worker/model startup |
| Same request with resident Piper | 4.79 s audio; 0.19 s synthesis |
| Output-device enumeration | 15 compatible outputs returned without opening playback |
| Short native default-device playback | 2.11 s audio; start notification after 1.19 s, completion after 3.06 s from adapter call |
| Cancel during native playback | Worker terminated/reaped; measured cancellation rounded to 0.00 s in this sample |
| Playback after cancellation | Completed successfully |
| Generated 5.24 s input → Silero/Whisper → Qwen → Piper → native output | Completed in 9.16 s, including output playback |
| Full-controller states | listening → transcribing → thinking → speaking → idle |
| Full-controller history and cleanup | User and completed assistant messages retained; output worker reaped |

The full-controller measurement excludes synthetic input generation and engine
warmup; it substitutes generated audio for physical capture and bypasses the UI.
A temporary Qwen server used the existing pinned model/runtime, GPU-fit settings,
4096 context and documented non-thinking/offline flags, then was stopped. All test
workers were closed. These are individual samples, not latency percentiles, acoustic
measurements or a recognition/answer-quality benchmark. PortAudio completion does
not independently establish that the user heard clear speech. Wi-Fi was not disabled
and no network-traffic audit was performed.

The first native synthesis attempt exposed the local LJSpeech config's `en` eSpeak
identifier. The initial implementation only allowed `en-us`; the adapter now accepts
both English identifiers, with a regression test for each. The existing model and
configuration were unchanged. Two new WebSocket tests initially used the test
client's default host and were rejected by the existing host restriction; their
URLs were corrected to loopback. Neither issue remains in the passing checks.

### Remaining acceptance

Follow the [Phase 5 checklist](desktop-development.md#phase-5-speech-and-playback-acceptance)
for audible end-to-end desktop turns, last-word completion, repeated turns,
Stop/Escape/focus-loss/disconnect behavior, microphone indicator observations,
selected-device routing/removal and recovery, and a Wi-Fi-disabled restart. The
first complete microphone-to-speaker milestone is awaiting that user acceptance.
No native UI visual inspection, distribution approval, package or release is claimed.

### Bluetooth completion-timeout fix

On 2026-10-20, the user reported that an AirPods reply played but was followed by
an audio-playback error. They also reported less accurate recognition with the
headset microphone than with the laptop microphone. These are distinct findings;
headset-microphone quality is not established as fixed by this playback change.

A playback-only synthetic test reproduced the error without opening any microphone:
a 2.55-second clip began output, then failed after 5.84 seconds waiting for completion.
Read-only PipeWire inspection showed AAC/A2DP output and automatic headset-profile
switching enabled; no system or Bluetooth settings were changed.

Additional callback instrumentation of a 2.66-second synthetic clip showed that
all frames were queued and CallbackStop was requested, with no underflow flags,
but no finished callback arrived. The final buffer's scheduled DAC time was 2.70 s,
while the stream clock stopped at about 2.49 s. A first attempt to wait for that
stream clock to reach the final end time therefore still timed out. The final fix
maps the last buffer's remaining scheduled duration to a monotonic clock and adds
a 100 ms margin. It only permits fallback completion after all audio has been queued
with valid timestamps; incomplete buffers, invalid timing, underflow and disconnect
remain failures, and the existing deadline still bounds a stalled device.

After the AirPods were reconnected, the updated adapter completed two native
playbacks of a 2.57-second synthetic clip in 3.28 s and 3.29 s from adapter entry.
Cancellation during output and a subsequent playback retry also passed. All workers
were reaped. The tests used the selected Bluetooth output and never opened its
microphone. No audio files, private transcripts or device identifiers were added
to the repository. These observations verify adapter completion and cleanup, not
independent acoustic measurements or full desktop acceptance with headset input.

Validation: **227 backend tests passed**, including new missing-finished-callback,
frozen-stream-clock, partial-output and invalid-timing cases. Existing playback
error and cancellation tests still pass. The isolated playback test suite passes
19 tests; its sounddevice mocks now restore only that module, avoiding unintended
NumPy module unloading when run alone. Ruff lint/format, strict mypy and
`git diff --check` passed. Frontend/Rust code was unchanged, so those suites were
not repeated. Restart the Python backend and retest several full desktop turns;
headset-microphone recognition/profile switching and audible last-word completion
remain user acceptance checks.

### User acceptance of AirPods playback and microphone use

On 2026-10-20, following the Bluetooth fix and the request to retest repeated short
desktop turns, the user confirmed that all checks passed. This records acceptance
of the requested playback-completion/return-to-idle checks without the trailing
error. The user also explicitly confirmed testing the AirPods microphone, while
noting that some words were still missed.

The user suggested nearby conversation/background noise as a possible explanation.
That cause has not been isolated with controlled comparisons. Recognition accuracy
remains a limitation; the playback fix does not claim to improve transcription.
No personal recordings, transcripts or screenshots were saved in the repository.

This supersedes the pending AirPods desktop retest above. It is user-reported
acceptance, distinct from the earlier instrumented playback-only tests. The latest
confirmation follows the Bluetooth retest request and does not separately establish
Wi-Fi-disabled desktop restart, device-removal recovery or every cancellation path
in the broader Phase 5 checklist.

Documentation only: `git diff --check` passed; application tests were not repeated.

### Completion of Phase 5 manual acceptance

On 2026-10-20, after being asked to complete the remaining playback cancellation,
output-device recovery and Wi-Fi-disabled restart checks, the user confirmed that
all tests passed and requested a branch push and PR description.

This records user acceptance of Stop speaking, Escape, focus loss and Disconnect
during playback with successful retry; the applicable output-device removal/recovery
checks; and a complete spoken turn after restarting Qwen, the backend and desktop
with Wi-Fi disabled. It supersedes the corresponding pending statuses above.
These are user-reported results, not independently captured acoustic measurements
or a network-traffic audit. Occasional AirPods microphone recognition errors remain
a documented limitation with no confirmed cause.

The first push-to-talk microphone-to-speaker flow is now accepted on the target
laptop. Phase 6 hardening, broader hardware coverage and latency measurement remain
future work. Hosted CI for this branch must still be checked on the PR; release
packaging and publication are not included.

This update changes documentation only. `git diff --check` passed; the previously
passing application checks were not repeated.
