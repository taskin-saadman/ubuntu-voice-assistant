# Desktop push-to-talk conversation

The interface connects hold-to-talk → microphone capture → Silero → CPU/int8
Whisper → visible transcript → streamed Qwen answer → CPU Piper → speaker playback.
Tools are not wired into this preview. The existing terminal diagnostic remains transcription-only.

## Start Qwen

Use the previously verified llama.cpp build and Qwen3-4B Q4_K_M model. In a separate
terminal, keep this server running while using the assistant:

```bash
~/.local/share/ubuntu-voice-assistant/tools/llama.cpp/build/bin/llama-server \
  --model ~/.local/share/ubuntu-voice-assistant/models/qwen3-4b/Qwen3-4B-Q4_K_M.gguf \
  --alias qwen3-4b --host 127.0.0.1 --port 8080 \
  --ctx-size 4096 --parallel 1 --gpu-layers auto \
  --fit on --fit-target 512 --batch-size 256 --ubatch-size 128 \
  --jinja --reasoning off \
  --offline --no-webui --log-disable
```

This is the same pinned model/runtime and GPU configuration verified earlier.
The pinned runtime deprecates the old CLI `enable_thinking` template override;
`--reasoning off` selects its supported equivalent. Each HTTP request also disables
thinking through its template options.
`--log-disable` prevents runtime logs from retaining prompt/output details.
Check startup in another terminal with `curl --fail http://127.0.0.1:8080/health`.
If port 8080 already hosts the correctly configured server, reuse that process.
The Python backend does not start, stop, download or replace llama.cpp or its model.

## Start the backend

From the repository root, after the existing uv/model/audio setup:

```bash
uv sync --locked --dev
uv run --offline --locked python -m voice_assistant.desktop_server
```

Stop the health-only server first if it occupies port 8765. This launcher binds
`127.0.0.1:8765` before printing a random connection key. Keep the terminal open.
The key permits access to this process's in-memory conversation and controls;
do not save it in the repository or share terminal screenshots containing it.
It changes on every backend restart. No virtual-environment activation is needed.

## Browser development preview

With Node 22.22.1, in another terminal:

```bash
cd desktop
npm ci --ignore-scripts
npm run dev
```

Open **http://127.0.0.1:1420**. The exact host/port matters for origin validation;
`localhost:1420` is not an accepted browser origin. Paste the backend key and choose
**Connect locally**, then **Load speech model**. While the microphone is disabled,
choose your current physical microphone input and speaker output, then enable the
microphone switch.
Hold the talk button, wait for **Listening to you**, speak, and release.
The transcript appears after **Turning speech into text**. The assistant then shows
**Thinking about your question** and an in-progress reply. A valid completed answer
replaces the draft. The interface then shows **Preparing speech**, followed by
**Speaking to you** during playback. Keyboard users can hold Space or Enter while the button has focus. Escape disables the microphone.

The microphone is off by default and only records during a turn. Turning the
switch off, switching away from the window, hiding the page, losing pointer capture,
or closing/disconnecting the client cancels recording. Normal pointer/key release
transcribes the captured audio. A quick release during startup is retained until
the server acknowledges that turn. Recording is capped at 30 seconds. **Stop response**,
Escape, focus loss or microphone-off also cancel generation, synthesis and playback.
During playback, **Stop speaking** stops the output and disables the microphone. Incomplete drafts are removed; completed messages remain.

After cancellation during inference, the speech worker may need reloading. Disable
the microphone and choose **Load speech model**; if an error is shown, use **Reset
assistant** once cleanup has completed. A cleanup failure requires restarting the
backend. Devices can be refreshed while the microphone is disabled. Device indices
can change between sessions; settings are not persisted.

## Native Tauri development window

The target laptop's development libraries are installed and the locked native
Cargo check and debug executable build pass. A user-supplied screenshot confirms
the native interface renders and displays transcripts. Remaining manual acceptance
checks are listed below. On a fresh Ubuntu setup, install the prerequisites separately:

```bash
sudo apt update
sudo apt install libwebkit2gtk-4.1-dev libxdo-dev \
  libayatana-appindicator3-dev librsvg2-dev libdbus-1-dev
```

`build-essential`, `pkg-config` and `libssl-dev` are already installed on the target
laptop; other systems also need them. This follows the
[official Linux prerequisites](https://v2.tauri.app/start/prerequisites/), with
D-Bus headers explicitly included based on the observed build error. Rust 1.98.1
is available locally. After prerequisites are installed:

```bash
cd desktop
npm ci --ignore-scripts
npm run build
cargo +1.98.1 check --locked --manifest-path src-tauri/Cargo.toml
npm run tauri -- dev
```

Stop a separately running Vite server first: Tauri launches it on the same fixed
loopback port. Keep the Python backend running separately and enter its key in
the native window. No automatic backend spawning, release packaging or publishing
is implemented. The native window enables no Tauri command capabilities. Its CSP
restricts connections to local services; development alone allows inline scripts
for Vite's React refresh preamble.

### VS Code Snap: GTK schema and WebKit startup errors

If startup aborts with `org.gnome.settings-daemon.plugins.xsettings` missing the
`antialiasing` key, check whether the terminal inherited `GSETTINGS_SCHEMA_DIR`
from the VS Code Snap. This was reproduced locally with Snap revision 268.
Selecting the system schemas alone fixed GTK initialization, but the user then
observed a WebKit internal-error page. Other GTK/GIO paths still referenced Snap
modules. The user supplied a screenshot of the functioning interface after the
following expanded launch command. From `desktop/`:

```bash
env -u GTK_PATH -u GTK_EXE_PREFIX \
    -u GTK_IM_MODULE_FILE -u GIO_MODULE_DIR \
    GSETTINGS_SCHEMA_DIR=/usr/share/glib-2.0/schemas \
    XDG_DATA_DIRS=/usr/local/share:/usr/share \
    npm run tauri -- dev
```

These environment overrides apply only to the command and its child processes.
They do not modify GNOME settings or schema files. The successful screenshot
does not isolate which additional override resolved WebKit's failure.
See the [GTK schema report](https://github.com/microsoft/vscode/issues/340859) and
[Snap GTK/GIO WebKit report](https://github.com/canonical/authd/issues/1829).

## Local checks and acceptance

```bash
# Repository root
uv run --offline --locked pytest -W error
uv run --offline --locked ruff check backend
uv run --offline --locked ruff format --check backend
uv run --offline --locked mypy

cd desktop
npm test
npm run build
cargo +1.98.1 fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo +1.98.1 check --locked --manifest-path src-tauri/Cargo.toml
```

Before accepting Phase 3 on the laptop:

1. Verify startup/reconnect show microphone off; a wrong key or second window
   cannot control the microphone or read the conversation.
2. Hold/release with pointer and keyboard. Confirm listening starts only when the
   device opens, transcribing follows release, and the expected words appear.
3. Stay quiet: expect a no-speech notice and no transcript. Try an immediate tap.
4. During recording, test Escape, focus loss, microphone off, window close and
   backend disconnect. Check Ubuntu's actual microphone indicator clears.
5. Reconnect/re-enable and repeat successfully. Cancel during transcription;
   reload the model if needed and confirm recovery.
6. Exercise missing model, invalid/unplugged input and recording timeout. Errors
   should be visible, controls should recover or clearly request a backend restart.
7. Repeat after disabling Wi-Fi, with dependencies/models already cached. Check
   readable contrast, keyboard focus and reduced-motion settings in the real window.

Record observations without committing personal audio, transcripts or connection
keys. DOM/fake-engine tests do not prove physical device cleanup, visual quality,
recognition accuracy or native/offline operation.

## Transport and privacy boundaries

Restart both the Python backend and frontend after updating: snapshots now include
bounded draft and speech-preparation fields plus output-device selection. Only the opt-in desktop launcher mounts `/session`. HTTP health remains read-only;
`/ready` reports the full pipeline as `not_ready` (503) while other probes remain
`not_configured`; its `llm` entry now checks llama.cpp health. Authenticated snapshots
expose separate transcription-model readiness. A ready speech model does not imply
llama.cpp is available: a failed generation preserves the transcript and shows an error.

The server requires an exact allowed Origin and a first authentication frame within
three seconds. Tokens are not URL parameters, cookies, files or browser storage.
Only one authenticated window owns controls. Commands have UUIDs and typed bounded
arguments; release/cancel include a turn ID, and unknown or repeated commands close
the connection. Queues, frame sizes, writes and command rate are bounded. Heartbeats
run independently of model loading. Missing control traffic for six seconds closes
the session; the client also detects absent responses. Disconnect cleanup disables
the microphone before ownership can transfer. The existing controller bounds
capture and native cleanup independently.

Events carry monotonic sequences; authoritative snapshots recover current state and
a bounded 20-message in-memory conversation. Reconnecting to the same backend can
recover that conversation, but never re-enables the microphone automatically.
Restarting the backend clears it. Credentials and transcripts are excluded from
application logs; the connection key is intentionally printed once in the developer
terminal. Origin checks protect the browser boundary, not a hostile local process
with access to the key. The manual key is a development pairing mechanism; packaged
launch/credential delivery remains future work.


## Phase 4 conversation acceptance

These checks were accepted before Phase 5. With Phase 5 enabled, completed answers
also play aloud; use the additional playback checks below.

After starting Qwen, restart the Python backend, reconnect with its new key, and
load the speech model. Keep the same local launch workaround if using VS Code Snap.

1. Ask a short question. Confirm `listening → transcribing → thinking → idle`, a
   visible transcript, streaming draft text and one completed assistant answer.
2. Ask a follow-up referring to the previous answer. Confirm recent completed turns
   provide context. No speech playback is expected in Phase 4.
3. During a longer answer, use **Stop response** or Escape. The draft should vanish,
   the microphone should be disabled, and re-enabling it should permit a fresh turn.
4. Stop llama.cpp and ask a question. The transcript should remain, an error should
   appear, and no assistant answer should be committed. Restart llama.cpp, choose
   **Reset assistant**, and retry. No backend restart should be necessary.
5. Repeat silence, client-disconnect and focus-loss checks with generation enabled.
   Later repeat after a Wi-Fi-disabled restart with all assets already downloaded.

The latest request is never silently cut to fit. The client asks llama.cpp to apply
its chat template and tokenize the result, keeping at most 3680 prompt tokens with
384 output tokens and a 32-token margin in the 4096-token context. Oldest complete
user/assistant pairs are removed from the request as needed; the visible history
still holds up to 20 messages. Failed/cancelled user-only turns are excluded from
future prompt context. Very large histories are also bounded before tokenization.
A latest request that cannot fit produces an explicit shorter-question error.

Generation has a 55-second overall client deadline, a 15-second HTTP read deadline,
and a separate 60-second controller deadline. Answers are capped at 384 tokens and
8192 characters. A token-limit finish, missing completion marker, malformed event,
reasoning field or recognized control markup causes failure and discards the draft.
Use a shorter question/request if output is repeatedly truncated. The client does
not automatically retry or continue partial answers. Text is rendered as plain text.

Thinking is disabled in both the server command and each request. The client rejects
structured reasoning/tool calls and known reasoning/control markers, including
markers split across chunks. This is format validation, not a guarantee of factual
accuracy or a general semantic classifier for model output. No tools are exposed.


## Phase 5 speech and playback acceptance

Restart the Python backend and desktop after updating, using the existing Qwen
server command and native GTK/WebKit workaround above. No new dependencies or
system packages are required. Keep these already-downloaded files together:

```text
~/.local/share/ubuntu-voice-assistant/models/piper/en_US-ljspeech-medium.onnx
~/.local/share/ubuntu-voice-assistant/models/piper/en_US-ljspeech-medium.onnx.json
```

Piper loads lazily on the first completed answer and stays resident on CPU. **Load
speech model** still loads Whisper; it does not test the Piper files or speaker.
Missing/invalid Piper files produce a synthesis error after the answer is displayed,
without a download attempt. Restarting the backend reloads a changed voice file.

With the microphone disabled, use **Refresh devices** and choose **Speaker output**.
The default follows the system output at playback time. Device lists are session
snapshots: refresh after connecting/disconnecting hardware. Outputs must support
mono or stereo int16 audio at a default rate between 8 and 48 kHz. Piper's mono audio
is resampled to that rate; stereo outputs receive it in both channels. Device choices
are held in memory, so reselect them after restarting. The app does not change system
volume or mute settings.

1. **Complete answer:** Ask “In two short sentences, explain what a local voice
   assistant does.” Confirm the transcript and complete answer appear, then hear
   the entire answer once. Expect listening → transcribing → thinking (including
   Preparing speech) → speaking → idle. The talk button stays unavailable until
   the turn completes. Check that the final word is not cut off.
2. **Repeated turns:** Ask three short follow-ups. Each should play once, with no
   overlap, delayed replay or missing last word.
3. **Stop:** Ask for five short benefits of local processing. During playback,
   select **Stop speaking**. Audio should stop promptly, the completed answer should
   remain visible, and the microphone should be disabled. Re-enable it and ask a
   short question to verify recovery. If possible, also stop during Preparing speech;
   the next answer should reload Piper automatically.
4. **Other cancellation paths:** Repeat during playback using Escape, switching
   windows, microphone-off and Disconnect. No old answer should resume after
   reconnecting. Confirm Ubuntu's microphone indicator is off during speech output.
5. **Output selection/failure:** With the microphone off, select a connected headset
   or another known output and confirm speech routes there. If available, unplug a
   selected removable output before a turn. Expect a visible playback error with
   the completed answer retained. Reset, refresh/reselect an available output, and
   retry. System sound servers may reroute a removed device rather than report an
   error; record the observed behavior.
6. **Offline restart:** With models/dependencies already cached, disable Wi-Fi,
   restart Qwen/backend/desktop and repeat a full spoken turn. Do not claim this
   check based solely on package offline flags.

Automated tests cover missing/corrupt voice responses and native-worker failure;
there is no need to move or delete your model files for manual testing. Record
results without saving private audio or conversation text in Git.

Only finalized, validated answers are synthesized. A synthesis/playback error keeps
the answer visible and provides Reset assistant. A cancelled Piper request kills its
worker; the next request loads it again. Speech is bounded to 90 seconds, with a
25-second synthesis deadline. Playback startup is limited to 5 seconds, with bounded
completion and cleanup waits. Native underflow is reported as an error rather than
silently accepting dropped audio. Speaking follows PortAudio's scheduled first-buffer
DAC time and finishes after its drain callback; exact acoustic timing still needs
human verification. No sentence streaming, barge-in or automatic audio replay is added.
