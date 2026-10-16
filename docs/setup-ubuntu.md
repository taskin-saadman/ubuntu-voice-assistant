# Ubuntu audio development setup

## Current implementation

Phase 3 has started with a microphone adapter and synthetic tests. The health
server still exposes only `/health` and `/ready`; it does not open the microphone.
Whisper/VAD integration, authenticated controls and the React/Tauri push-to-talk
window remain subsequent increments. This is not yet a runnable voice assistant.

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
the future VAD adapter must classify it as no speech. No real silence detection is
claimed yet.

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
