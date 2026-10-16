# Ubuntu audio development setup

## Current implementation

Phase 3 provides capture and local VAD/Whisper through a transcription diagnostic.
The health server still exposes only `/health` and `/ready`; it does not open the
microphone. Authenticated controls and the React/Tauri push-to-talk window remain
subsequent increments. This is not yet the complete voice assistant.

## PortAudio prerequisite

The `sounddevice` Python dependency is managed by uv. On Linux it also needs the
system PortAudio library. The initial inspection found `libportaudio2` missing on
the target laptop; the user has since installed it and supplied successful capture
results. On a fresh machine, installation is a separate OS change for the user to
authorize or perform:

```bash
sudo apt install libportaudio2
```

No ALSA development headers are needed for this runtime-library path. Tauri's
WebKitGTK development package is also absent, but is not needed for this audio
increment. Desktop prerequisites will be handled when implementing the window.

After PortAudio is available, run from the repository root in your desktop session:

```bash
uv sync --locked --dev
uv run --offline --locked python -m voice_assistant.audio
```

This lists input device indices and their default sample rates without opening a
recording stream. It filters out output-only devices and rates outside 8–48 kHz.
Device indices can change after reconnects; enumerate again after hardware changes.
An absent or unsupported input produces a visible error; the adapter never silently
switches a specifically selected index to another device.

## Manual capture check

Only run this when ready to enable your microphone for three seconds. It keeps
audio in memory and prints metadata, without saving, transcribing or playing it.
Use `CaptureSettings(device=INDEX)` to select an index from the listing, or leave
`device=None` for the system default input. This script verifies capture mechanics,
not audible quality or speech recognition.

```bash
UV_OFFLINE=true uv run --locked python - <<'PY'
import asyncio

from voice_assistant.audio.capture import MicrophoneCapture
from voice_assistant.audio.models import CaptureSettings

async def main():
    capture = MicrophoneCapture(CaptureSettings(device=None))
    try:
        await capture.start()
        print("Microphone recording for three seconds…", flush=True)
        await asyncio.sleep(3)
        audio = await capture.finish()
        print(f"Microphone closed; {audio.duration:.2f}s, {audio.sample_rate} Hz, mono int16")
    finally:
        await capture.abort()

asyncio.run(main())
PY
```

Press Ctrl+C during the check to exercise cancellation. Repeat a normal check
afterward to verify the device can reopen. Confirm that the desktop microphone
indicator clears after completion and cancellation. Device-disconnection and
lost-release checks will also need validation in the eventual push-to-talk UI.

The worker rejects overflow and incomplete reads instead of transcribing damaged
audio. Empty, immediately released capture becomes one zero-valued PCM frame;
the Silero adapter classifies generated one-frame silence as no speech in tests.

## Automated checks

```bash
uv run --offline --locked pytest backend/tests/test_audio.py -W error
uv run --offline --locked ruff check backend
uv run --offline --locked ruff format --check backend
uv run --offline --locked mypy
uv run --offline --locked pytest -W error
```

Synthetic streams and subprocesses exercise capture boundaries without PortAudio,
an audio device, models, user recordings or network access. Real microphone quality,
device release and capture startup latency must be observed separately on the laptop.

## Microphone-to-transcript check

The diagnostic uses the same controller, capture adapter, Silero VAD and Whisper
adapter intended for the desktop. It ends after transcription and does not invoke
Qwen, Piper or any tools. Local settings default to:

- Model directory: `~/.local/share/ubuntu-voice-assistant/models/whisper-small.en`.
- Whisper: CPU, int8, eight threads, one worker, English, beam size 5.
- VAD: bundled Silero, probability threshold 0.5, minimum speech 100 ms,
  minimum separating silence 500 ms. Very short utterances can be discarded.
- Maximum recorded audio: 30 seconds; the diagnostic accepts 0.1–25 seconds to
  leave room before the controller's independent recording deadline.

The local model directory must contain `model.bin`, `config.json`, `tokenizer.json`
and either `vocabulary.txt` or `vocabulary.json`. Missing files cause an error;
the diagnostic never downloads a replacement. Use `--model-path /absolute/path`
to point at your existing small.en model directory if it is elsewhere.

First enumerate devices; indices can change. Then choose your microphone input
(index 23 was the built-in analog input in the supplied verification output):

```bash
uv run --offline --locked python -m voice_assistant.audio
uv run --offline --locked python -m voice_assistant.transcribe --device 23 --seconds 5
```

The command loads the local model while the microphone is off. Wait for
`State: listening` and the “Speak now” message before speaking a short sentence.
Expected states are `listening → transcribing → idle`, with a transcript and
`Result: completed`. The transcript is displayed intentionally in the terminal;
audio and history are kept in memory, with no recording/history files written.
The worker enforces offline/telemetry-disable settings internally; `--offline`
also prevents uv from fetching dependencies.

Repeat the command while staying quiet: expect `Result: no_speech` and no transcript.
Then press Ctrl+C during recording, confirm the microphone indicator clears, and
run a normal turn again. The diagnostic prints `Cancelled.` without a traceback.
Repeat cancellation during `transcribing` if the inference interval is long enough.
Record whether cancellation and subsequent turns succeed, and whether the visible
transcript matches what you said. Avoid sharing private utterances in logs or Git.

The final “Microphone disabled” line describes the controller's permission flag.
Any cleanup error is also displayed; confirm the desktop microphone indicator
clears instead of relying on that line alone. Speech quality, noisy-room behavior
and physical-device failures still require these real-device checks. This command
uses a timed recording; the hold-to-talk desktop control is a later increment.
