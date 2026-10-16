# Phase 3 desktop transcription preview

The interface connects hold-to-talk → microphone capture → Silero → CPU/int8
Whisper → visible transcript. Qwen responses, Piper playback and tools are not
wired into this preview. The existing terminal diagnostic remains available.

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
choose your current physical microphone input, then enable the microphone switch.
Hold the talk button, wait for **Listening to you**, speak, and release.
The transcript appears after **Turning speech into text**. Keyboard users can
hold Space or Enter while the button has focus. Escape disables the microphone.

The microphone is off by default and only records during a turn. Turning the
switch off, switching away from the window, hiding the page, losing pointer capture,
or closing/disconnecting the client cancels recording. Normal pointer/key release
transcribes the captured audio. A quick release during startup is retained until
the server acknowledges that turn. Recording is capped at 30 seconds.

After cancellation during inference, the speech worker may need reloading. Disable
the microphone and choose **Load speech model**; if an error is shown, use **Reset
assistant** once cleanup has completed. A cleanup failure requires restarting the
backend. Devices can be refreshed while the microphone is disabled. Device indices
can change between sessions; settings are not persisted.

## Native Tauri development window

The target laptop's development libraries are installed and the locked native
Cargo check and debug executable build pass. Window launch and microphone interaction still need manual
acceptance. On a fresh Ubuntu setup, install the prerequisites separately:

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

### VS Code Snap: missing `antialiasing` schema key

If startup aborts with `org.gnome.settings-daemon.plugins.xsettings` missing the
`antialiasing` key, check whether the terminal inherited `GSETTINGS_SCHEMA_DIR`
from the VS Code Snap. This was reproduced locally with Snap revision 268.
From `desktop/`, select the system schemas for this launch:

```bash
GSETTINGS_SCHEMA_DIR=/usr/share/glib-2.0/schemas npm run tauri -- dev
```

This environment override applies only to the command and its child processes.
It does not modify GNOME settings or schema files. A native GTK initialization
probe failed with the inherited environment and passed with this single override;
the complete Tauri window and microphone interaction still need verification.
See the [matching upstream VS Code report](https://github.com/microsoft/vscode/issues/340859).

## Local checks and acceptance

```bash
# Repository root
uv run --offline --locked pytest -W error
uv run --offline --locked ruff check backend
uv run --offline --locked ruff format --check backend
uv run --offline --locked mypy

# desktop/
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

Only the opt-in desktop launcher mounts `/session`. HTTP health remains read-only;
`/ready` still reports the full pipeline as `not_configured` (503). Authenticated
snapshots expose separate transcription-model readiness to this preview.

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
