"""Resident Piper process. Text and PCM travel only through private pipes."""

import logging
import sys
from typing import BinaryIO

from voice_assistant.tts.models import PiperSettings, SynthesisReply, SynthesisRequest


def run(source: BinaryIO, output: BinaryIO) -> None:
    logging.disable(logging.CRITICAL)
    try:
        settings = PiperSettings.model_validate_json(source.readline(16384))
        from voice_assistant.tts.engine import PiperEngine

        engine = PiperEngine(settings)
        while line := source.readline(65536):
            request = SynthesisRequest.model_validate_json(line)
            audio = engine.synthesize(request.text)
            output.write(
                SynthesisReply(status="audio", size=len(audio.pcm), sample_rate=audio.sample_rate)
                .model_dump_json()
                .encode()
                + b"\n"
            )
            output.write(audio.pcm)
            output.flush()
    except Exception:
        output.write(SynthesisReply(status="error").model_dump_json().encode() + b"\n")
        output.flush()


if __name__ == "__main__":
    run(sys.stdin.buffer, sys.stdout.buffer)
