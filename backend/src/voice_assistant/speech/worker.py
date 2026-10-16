"""Persistent single-request-at-a-time speech worker. No microphone or files written."""

import logging
import os
import sys
from typing import BinaryIO

from voice_assistant.speech.models import SpeechReply, SpeechRequest


def reply(output: BinaryIO, message: SpeechReply) -> None:
    output.write(message.model_dump_json().encode() + b"\n")
    output.flush()


def run(input_file: BinaryIO, output: BinaryIO) -> None:
    # Set these before importing any inference libraries, including for direct launches.
    os.environ.update(
        HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1"
    )
    logging.disable(logging.CRITICAL)
    from voice_assistant.speech.engine import ModelMissing, SpeechEngine

    try:
        initial = SpeechRequest.model_validate_json(input_file.readline(16384))
        if initial.action != "initialize" or initial.settings is None:
            raise ValueError("Expected initialization")
        engine = SpeechEngine(initial.settings)
        reply(output, SpeechReply(status="ready"))
        while header := input_file.readline(16384):
            request = SpeechRequest.model_validate_json(header)
            if request.action == "warmup":
                reply(output, SpeechReply(status="ready"))
                continue
            if request.action not in {"vad", "transcribe"}:
                raise ValueError("Unexpected request")
            pcm = input_file.read(request.size)
            if len(pcm) != request.size:
                raise ValueError("Incomplete PCM")
            if request.action == "vad":
                reply(output, SpeechReply(status="vad", speech=engine.has_speech(pcm)))
            else:
                reply(output, SpeechReply(status="transcript", text=engine.transcribe(pcm)))
            del pcm
    except ModelMissing:
        reply(output, SpeechReply(status="error", error="model_missing"))
    except Exception:
        reply(output, SpeechReply(status="error", error="failed"))


if __name__ == "__main__":
    run(sys.stdin.buffer, sys.stdout.buffer)
