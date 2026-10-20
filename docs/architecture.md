# Phase 2 controller foundation

## Boundaries

The editable Python package is `backend/src/voice_assistant`, managed by the root
uv project. Importing it never loads models, downloads assets or opens devices.

| Module | Responsibility |
| --- | --- |
| `contracts.py` | Immutable Pydantic data and typed capture, VAD, STT, LLM, TTS, playback and storage protocols |
| `state.py` | Explicit legal assistant state transitions |
| `events.py` | Version 1 events, structured failures and a bounded in-memory event journal |
| `storage.py` | Bounded, clearable in-memory conversation history |
| `controller.py` | Single-turn ownership, deadlines, cancellation, cleanup and safe errors |
| `readiness.py` | Bounded, concurrent dependency checks |
| `api.py` | Read-only FastAPI liveness/readiness routes and lifecycle wiring |
| `__main__.py` | Supported loopback-only Uvicorn launcher |

Fake adapters live in `backend/tests/fakes.py`. They provide synthetic PCM and
controlled delays/failures; they are not a default application mode or substitutes
for the selected engines. The Phase 3 adapters described below extend this
foundation using the selected engine configuration.

## Turn lifecycle

Microphone permission begins **off** and is independent of assistant state.
The internal controller API is intended for a future authenticated transport:

1. `await controller.set_microphone(True)` permits capture.
2. `turn_id = controller.begin_turn()` synchronously reserves the only turn slot
   and schedules work. Overlapping turns and microphone-off capture are rejected.
3. Capture starts asynchronously. `listening` is emitted after the adapter confirms
   it started, not merely when a button was pressed.
4. `controller.release(turn_id)` ends recording. Duplicate releases are harmless;
   controls carrying an older turn ID cannot affect the current turn.
5. VAD rejects silence, then STT produces text. A nonempty user message is retained
   and passed to the language-model adapter with the bounded session history.
6. A valid finalized answer is retained before synthesis. This lets the UI keep
   the answer visible if Piper or playback fails. Empty answers and reasoning
   markup are rejected, not spoken.
7. Synthesis remains `thinking`. The playback adapter calls `on_started` when audio
   starts; only then does the controller emit `speaking`.
8. Cleanup stops capture and playback, then the controller emits a terminal outcome
   and normally returns to `idle`. The microphone permission stays as the user set it.

Normal state sequence:

```text
idle → listening → transcribing → thinking → speaking → idle
```

`acting` is reserved in the state model for future permission-controlled tools.
No tool registry, shell capability or model-proposed action executes in Phase 2.
`error` requires an explicit `reset()` once resources are stopped; a successful
reset returns to `idle` without deleting the displayed conversation.

## Cancellation, deadlines and device ownership

`cancel(turn_id)` signals a turn and waits for bounded cleanup. Microphone-off,
transport disconnect handling and shutdown must route through this method.
`close()` disables the microphone, cancels any turn and prevents new turns. A
caller cancelling its own `wait()` does not abandon or silently cancel the owned
turn; an explicit cancellation signal is required.

| Operation | Default limit |
| --- | --- |
| Capture start / finish | 5 seconds each |
| Waiting for button release | 30 seconds |
| VAD / transcription | 30 seconds each |
| Response generation | 60 seconds |
| Synthesis | 30 seconds |
| Playback | 120 seconds |
| Capture abort / playback stop | 2 seconds each |

Limits are validated by the immutable `Deadlines` schema. Audio is bounded to
mono signed 16-bit PCM, supported sample rates and a maximum duration; capture
adapters must additionally enforce the recording limit while buffering.

An adapter must never block the asyncio event loop. Future native inference and
audio implementations must use adapter-owned workers/processes and implement
resource-safe cancellation. Cancelling a Python coroutine alone cannot stop a
native inference call or forcibly release a device in another thread.

The controller stops waiting at a deadline, ignores late results, and tracks any
operation still running after cancellation. New turns/reset are rejected while
such work remains. A device operation that ignores cancellation, or a failed
cleanup, requires backend restart. This is containment of a broken adapter, not a
claim that Python can kill arbitrary native work. Capture's cancelled `start`
must never reopen a microphone later, and playback's cancelled `play` must never
resume sound. Both cleanup methods must be idempotent.

## Events and privacy

Events are immutable and validated: schema version, monotonically increasing
sequence, turn ID, kind and exactly one matching payload. Event kinds are `state`,
`message`, `error`, `finished` and `microphone`. Finished outcomes are `completed`,
`cancelled`, `no_speech` and `failed`.

The event journal holds at most 256 events; consumers can read after a sequence.
If history has been evicted, the future UI transport must detect the sequence gap
and reconstruct its view from current controller state and conversation history.
There is no WebSocket/event endpoint yet. Do not publish this journal without the
planned authentication and origin checks; message events intentionally contain
the transcript needed by the local UI.

Session history holds at most 20 messages of at most 8192 characters each and can
be explicitly cleared. This is a memory bound, not a token budget. The real LLM
adapter must enforce the 4096-token context and reserve answer tokens in Phase 4.
Raw PCM is excluded from Pydantic serialization and repr. Logs contain a stable
event name and error code, not engine exception text, audio, prompts or answers.

## Health API

Run `uv run --locked python -m voice_assistant`. The supported launcher binds only
to `127.0.0.1:8765`, disables access logging and does not trust proxy headers.
Allowed Host headers are localhost/127.0.0.1; no CORS permissions are granted.

- `GET /health`: 200 with `{"status":"ok"}`; process liveness only.
- `GET /ready`: 200 only when every configured component probe reports ready;
  otherwise 503. Per-component statuses distinguish `not_configured`, `unavailable`
  and `timeout`. Probe exceptions do not disclose paths or engine diagnostics.
- The default factory has no engine probes: readiness is therefore 503. A manually
  running llama-server does not make the unwired backend ready.
- Probes run concurrently with a one-second default deadline. Concurrent polling
  shares in-flight probes and cannot spawn more copies of a stubborn probe.
- Readiness describes dependency availability, not microphone permission or whether
  a turn slot is free; the controller enforces those separately.

The application exposes no state-changing routes, conversation data or tools.
Authentication, origin validation and disconnect-to-cancellation wiring are required
before adding microphone controls or the UI WebSocket transport in Phase 3.
Host validation and loopback binding alone are not authorization.

## Validation and remaining work

The suite covers state/data validation, ordered simulated turns, silence, duplicate
and stale controls, cancellation at every stage, timeout/cleanup behavior,
unavailable engines, retained answers after TTS failure, invalid LLM answers,
late callbacks/results, bounded history, safe logs and backend liveness/readiness.
An in-process health request remains responsive while a fake model and a readiness
probe are blocked. A real local server smoke check separately verifies HTTP status
codes and process shutdown.

These tests establish the Phase 2 simulated-turn exit criterion on the local Python
environment. They do not establish real-device cancellation, live voice latency,
streamed llama.cpp response parsing, tool permissions, UI behavior or desktop
packaging. Phase 1 engine measurements remain separate evidence in
[verification.md](verification.md).

## Phase 3 capture increment

`audio/capture.py` implements the capture protocol with a short-lived subprocess
per recording. The child imports sounddevice after a typed request; importing the
backend or listing devices never starts recording. `audio/worker.py` owns the
PortAudio stream, reads mono signed 16-bit samples at the selected device's default
rate, closes it, and uses existing PyAV resampling to return 16 kHz PCM. No WAV files
are created. Native diagnostics are discarded; the parent receives allowlisted
error codes through private pipes.

Recording is bounded by both a frame count and wall-clock duration, with a maximum
of 30 seconds. A separate parent watchdog terminates a worker blocked in a native
read when the release signal is lost. Start/finish waits are bounded to four
seconds. Abort sends termination, waits up to 250 ms, then uses a forced kill and
waits up to 500 ms to reap the child. The adapter cannot be reused until cleanup
finishes; cancellation of a caller does not abandon that cleanup. Normal backend
shutdown must still await controller cleanup. Abrupt parent-process termination
during a hung native call has not been verified by this increment.

The controller now gives cancelled device operations the bounded cleanup window
to finish. Operations still active after abort/stop require a backend restart;
operations successfully reaped during cleanup permit another turn. Tests cover
both outcomes, including a synthetic process that ignores normal termination.

Python adapters run on the same event loop; only the private child handles blocking
audio operations. This process-per-turn design prioritizes reliable device release.
Its real startup cost and microphone behavior are still to be measured. No runtime
controls have been exposed yet: authentication/origin checks and UI disconnect
cancellation remain prerequisites for connecting the future desktop interface.

## Phase 3 VAD and transcription increment

`speech/adapters.py` provides separate `SileroVAD` and `WhisperTranscriber`
boundaries sharing a `SpeechWorker`. The worker starts lazily, loads the local
small.en model on CPU/int8, and retains it between successful requests. It accepts
one request at a time and rejects overlap. PCM is limited to mono 16 kHz and 30
seconds; responses are validated and transcripts bounded to 8192 characters.
Heavy imports, bundled Silero inference and Whisper's lazy segment iteration all
run in the child process, outside the API event loop.

Whisper's standalone adapter repeats the speech check and enables the decoder's
integrated VAD filter. This intentionally guards callers that bypass the controller;
empty/silent input returns an empty transcript without invoking the decoder.
There is no transcript prompt carried between calls. The controller retains only
its bounded in-memory conversation. Neither the adapters nor the worker log content.

Cancelling or timing out a request terminates/reaps the child, using forced kill
if normal termination takes longer than 250 ms. The next request reloads the local
model. `close()` permanently shuts down the worker. The controller now allows an
additional bounded cleanup interval for cancelled inference tasks to settle before
declaring a turn finished; lingering work still quarantines subsequent turns.
An application runtime must close both the controller and its owned speech worker.

`TranscriptionComponents` explicitly configures a capture/VAD/STT-only controller.
Its successful state path is `idle → listening → transcribing → idle`, publishing
one user message. Silence ends with `no_speech` and no conversation message. The
existing full `Components` configuration retains Qwen/TTS/playback orchestration.
There are no fake assistant responses or dummy speech outputs in transcription mode.

`python -m voice_assistant.transcribe` wires these adapters into a timed terminal
diagnostic. Model warmup happens before microphone permission is enabled; errors
and state changes are displayed. Its transcript output is an explicit user-facing
view, not application logging. This command adds no HTTP routes or network listeners.
The FastAPI factory remains health-only, with default readiness still 503 until an
application runtime wires its probes. Authentication, origin validation, disconnect
cancellation and the React/Tauri hold control remain subsequent work.

## Authenticated transcription desktop

`desktop_server` creates `TranscriptionRuntime` and opts into `DesktopTransport`;
the original health launcher does not expose controls. The runtime owns capture,
a resident speech worker and a transcription-only controller. Preparation loads
local weights and enumerates devices with microphone permission off. Device changes
require an inactive controller; enabling the microphone requires a loaded model.

The WebSocket transport authenticates before emitting any state, permits one owner,
and uses independent receive, serialized control and send loops. Heartbeat traffic
therefore remains responsive while model preparation waits. Bounded queues prevent
unlimited control backlog. Ownership ends only after disconnect cleanup disables
the microphone; AnyIO shielding protects this cleanup during ASGI cancellation.

The React client owns connection deadlines, command acknowledgements and the held
turn ID. Presentation components translate pointer/keyboard/focus gestures into
client calls and render validated authoritative snapshots. The Rust shell provides
a window only: no native command capabilities, engine logic or backend spawning.
See [desktop-development.md](desktop-development.md) for protocol limits, pairing,
privacy boundaries and manual acceptance.

## Phase 4 conversation and streaming

`ConversationComponents` adds a language-model adapter to the transcription
components. The existing full `Components` adds TTS/playback afterward, preserving
Phase 2's full-turn tests and the Phase 3 transcription-only diagnostic.
`ConversationRuntime` now wires the desktop to `LlamaClient`; its HTTP pool closes
with the runtime. llama.cpp remains a separately launched local process.

The LLM contract accepts a synchronous, non-blocking delta callback. The controller
keeps draft text separate from conversation history, ties callbacks to the active
turn and ignores late callbacks after cancellation or turn replacement. Only a
validated, complete answer enters history. Cancellation, error and completion all
clear the draft. Native model work remains in llama.cpp; HTTP and stream processing
are asynchronous in Python.

Authenticated snapshots include the bounded draft alongside state, turn ID and
history. Draft changes do not allocate journal events or advance the journal
sequence; the existing snapshot sender observes changes and the frontend accepts
ordered snapshots at the same sequence. New state/history events still advance
that sequence. This avoids replaying hundreds of partial answers and lets snapshots
remain authoritative after journal gaps. The UI escapes text, marks drafts as
in-progress, follows new text while scrolled near the bottom, and keeps a Stop
response control available during transcription/generation.

`LlamaClient` uses a fixed IPv4-loopback host, no environment proxy settings, no
redirect following, bounded responses and one active generation per client. It
closes the streaming HTTP response on completion/error/cancellation. SSE framing
handles fragmented UTF-8 and CRLF, rejects oversized events/bodies, and requires
both a successful stop finish and `[DONE]`. Non-thinking template options are sent
on every request. Structured tool/reasoning output and known special markers are
rejected; possible marker prefixes are held until subsequent chunks disambiguate
them, so split markers are not emitted to the UI.

Context is measured with the server's `/apply-template` and `/tokenize`, using the
same request options as generation. The adapter retains the system instruction and
latest user request, drops oldest complete pairs to reserve output space, and
rejects a latest request that still cannot fit. Orphan assistant messages and
failed/cancelled user-only turns are not sent back to the model. Display history
is unaffected by prompt pruning and remains bounded in memory.

The speech-ready flag remains independent of LLM health. The desktop's `/ready`
service now probes llama.cpp, but overall readiness remains false until the other
full-pipeline probes are configured. Generation failure preserves the user's
transcript, reports a safe error and supports reset/retry. No tool registry or
model-generated action is connected in Phase 4.


## Phase 5 synthesis and playback

`VoiceRuntime` extends the conversation runtime with `PiperSynthesizer` and
`AudioPlayback`, wiring the existing full `Components` contract into the desktop.
The transcription diagnostic and conversation-only runtime remain available. The
controller stores a finalized answer before synthesis; failures or cancellation
in either audio stage preserve it. A `preparing_speech` snapshot flag distinguishes
synthesis/output startup from generation without adding another state. It clears
on the playback-start callback and on every terminal path.

Piper runs lazily in a resident private process with two ONNX CPU inference threads,
one inter-op thread, telemetry disabled and no CUDA provider. The configured local
ONNX and JSON files must exist. The supported English eSpeak configuration avoids
alternative phonemizers with resource-download paths, and optional Arabic resource
loading is disabled. Text is bounded and Piper's explicit phoneme delimiters are
removed before synthesis. PCM returns through bounded binary pipes and is limited
to 90 seconds; no audio or conversation files are written.

Playback uses a separate short-lived process for each turn. PyAV resamples to the
selected output's default rate and mono samples are duplicated for stereo. The
PortAudio callback fills every buffer, pads the final block with silence, and
requests a drain after the last samples. The worker reports start at the first
buffer's scheduled DAC time, then reports completion after the finished callback.
For Bluetooth backends that omit that callback, completion can instead follow the
final fully queued buffer's remaining scheduled duration, mapped from its callback
timestamps to a monotonic clock with a 100 ms margin. This also handles a frozen
stream clock after CallbackStop. Partial output,
invalid timing and underflow do not qualify for this fallback; the existing deadline
still bounds stalled devices. This prevents successful output becoming a false
completion-timeout error.
Errors abort/close output; parent disconnection is checked during playback. The
async adapter also bounds startup and completion, and kills/reaps blocked workers.
This reflects the audio driver's timing, not a measurement of sound at the listener.

`LocalWorker` shares process ownership/cleanup between the new adapters. Startup
is shielded so cancellation cannot abandon a just-created process. Generation
checks prevent a delayed spawn from receiving work after stop. Cleanup is shared,
shielded from caller cancellation and escalates termination to kill; ownership is
not released until the process is reaped. The existing controller quarantines
unfinished cleanup. Piper cancellation resets its worker for lazy retry; runtime
shutdown closes all resident engines.

Authenticated snapshots include output choices and selected output index. A typed
`output` command accepts only a listed index or system default, and runtime guards
require microphone-off and no active turn. The UI exposes Preparing speech,
Speaking to you and Stop speaking. Escape, blur, microphone-off and disconnect use
the same cancellation path; completed messages remain visible. Device selection
is session-only. No output stream opens during startup or device enumeration.
