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
for the selected engines. Real adapters will arrive in the subsequent planned
phases, using the already validated llama.cpp/Whisper/Piper configuration.

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
