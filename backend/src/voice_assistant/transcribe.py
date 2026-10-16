"""Explicit microphone-to-transcript diagnostic; no HTTP controls or LLM calls."""

import argparse
import asyncio
from pathlib import Path

from pydantic import ValidationError

from voice_assistant.audio.capture import MicrophoneCapture
from voice_assistant.audio.models import CaptureSettings
from voice_assistant.controller import Controller, TranscriptionComponents
from voice_assistant.events import Event
from voice_assistant.speech.adapters import SileroVAD, SpeechWorker, WhisperTranscriber
from voice_assistant.speech.models import SpeechError, SpeechSettings
from voice_assistant.storage import MemoryConversation


def show(event: Event) -> None:
    if event.state is not None:
        print(f"State: {event.state.value}", flush=True)
    if event.message is not None:
        print(f"Transcript: {event.message.content}", flush=True)
    if event.failure is not None:
        print(event.failure.message, flush=True)
    if event.outcome is not None:
        print(f"Result: {event.outcome}", flush=True)


async def check(
    capture_settings: CaptureSettings, speech_settings: SpeechSettings, seconds: float
) -> int:
    speech = SpeechWorker(speech_settings)
    controller = Controller(
        TranscriptionComponents(
            capture=MicrophoneCapture(capture_settings),
            vad=SileroVAD(speech),
            stt=WhisperTranscriber(speech),
            history=MemoryConversation(),
        )
    )
    timer: asyncio.TimerHandle | None = None
    sequence = 0
    try:
        print("Microphone off. Loading local small.en on CPU…", flush=True)
        await speech.warmup()
        await controller.set_microphone(True)
        turn = controller.begin_turn()
        outcome = None
        while True:
            for event in controller.events.read(sequence):
                sequence = event.sequence
                show(event)
                if event.state == "listening" and timer is None:
                    print(
                        f"Speak now. Recording for {seconds:g} seconds; Ctrl+C cancels.", flush=True
                    )
                    timer = asyncio.get_running_loop().call_later(seconds, controller.release, turn)
                if event.outcome:
                    outcome = event.outcome
            if outcome is not None or not controller.busy:
                break
            # This CLI observes the bounded event journal; the desktop will use transport events.
            await asyncio.sleep(0.02)
        return 0 if outcome in {"completed", "no_speech"} else 1
    finally:
        if timer is not None:
            timer.cancel()
        try:
            await controller.close()
            for event in controller.events.read(sequence):
                if event.failure is not None:
                    show(event)
        finally:
            await speech.close()
            print("Microphone disabled; speech worker stopped.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device", type=int, help="Input index from python -m voice_assistant.audio"
    )
    parser.add_argument(
        "--seconds", type=float, default=5, help="Recording duration, 0.1–25 (default 5)"
    )
    parser.add_argument("--model-path", type=Path, default=SpeechSettings().model_path)
    args = parser.parse_args()
    if not 0.1 <= args.seconds <= 25:
        parser.error("--seconds must be between 0.1 and 25")
    try:
        settings = CaptureSettings(device=args.device)
        speech = SpeechSettings(model_path=args.model_path)
        return asyncio.run(check(settings, speech, args.seconds))
    except KeyboardInterrupt:
        print("Cancelled.")
        return 130
    except (SpeechError, ValidationError):
        print("Local speech initialization failed. Check the model directory and settings.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
