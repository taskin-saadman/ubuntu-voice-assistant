"""Private subprocess protocol; stdout is IPC, never application logging.

The worker starts inert and only opens a microphone after a capture request.
Blocking PortAudio reads and PyAV resampling stay outside the API process.
"""

import os
import select
import sys
from collections.abc import Buffer, Callable
from time import monotonic
from typing import BinaryIO, Protocol

from voice_assistant.audio.models import (
    CaptureSettings,
    InputDevice,
    WorkerReply,
    WorkerRequest,
)
from voice_assistant.audio.normalize import normalize
from voice_assistant.contracts import AudioBuffer


class InputStream(Protocol):
    def start(self) -> None: ...
    def read(self, frames: int) -> tuple[Buffer, bool]: ...
    def close(self) -> None: ...


class RecordingFailed(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def record(
    stream: InputStream,
    sample_rate: int,
    settings: CaptureSettings,
    released: Callable[[], bool],
    started: Callable[[], None],
    clock: Callable[[], float] = monotonic,
) -> AudioBuffer:
    """Bounded blocking capture, independently testable without an audio device."""
    chunks = bytearray()
    block = max(1, sample_rate // 50)
    limit = int(sample_rate * settings.max_seconds)
    try:
        stream.start()
        deadline = clock() + settings.max_seconds
        started()
        while True:
            if released():
                break
            remaining = limit - len(chunks) // 2
            if remaining <= 0 or clock() >= deadline:
                raise RecordingFailed("limit_reached")
            count = min(block, remaining)
            data, overflow = stream.read(count)
            if overflow:
                raise RecordingFailed("overflow")
            # sounddevice returns a CFFI buffer supporting bytes().
            pcm = bytes(data)
            if len(pcm) != count * 2:
                raise RecordingFailed("failed")
            chunks.extend(pcm)
    finally:
        # close() discards pending input; no stop/drain delay is necessary.
        stream.close()
    return normalize(AudioBuffer(pcm=bytes(chunks) or b"\0\0", sample_rate=sample_rate))


def reply(output: BinaryIO, message: WorkerReply, pcm: bytes = b"") -> None:
    output.write(message.model_dump_json().encode() + b"\n")
    output.write(pcm)
    output.flush()


def run(input_file: BinaryIO, output: BinaryIO) -> None:
    try:
        request = WorkerRequest.model_validate_json(input_file.readline(4096))
        try:
            import sounddevice as sd  # type: ignore[import-untyped]
        except (ImportError, OSError):
            reply(output, WorkerReply(status="error", error="unavailable"))
            return
        if request.action == "devices":
            devices = tuple(
                InputDevice(index=index, name=str(item["name"])[:256], sample_rate=int(rate))
                for index, item in enumerate(sd.query_devices())
                if item["max_input_channels"] >= 1
                and 8000 <= (rate := item["default_samplerate"]) <= 48000
            )[:128]
            reply(output, WorkerReply(status="devices", devices=devices))
            return
        device = sd.query_devices(request.settings.device, "input")
        sample_rate = int(device["default_samplerate"])
        if not 8000 <= sample_rate <= 48000 or device["max_input_channels"] < 1:
            raise RecordingFailed("unsupported_format")
        sd.check_input_settings(
            device=request.settings.device, channels=1, dtype="int16", samplerate=sample_rate
        )
        stream = sd.RawInputStream(
            device=request.settings.device,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )

        def released() -> bool:
            if not select.select([input_file], [], [], 0)[0]:
                return False
            # EOF (parent gone) is also a stop signal. The parent sends one command.
            command = os.read(input_file.fileno(), 16)
            if command not in {b"finish\n", b""}:
                raise RecordingFailed("failed")
            return True

        audio = record(
            stream,
            sample_rate,
            request.settings,
            released,
            lambda: reply(output, WorkerReply(status="started")),
        )
        reply(output, WorkerReply(status="audio", size=len(audio.pcm)), audio.pcm)
    except RecordingFailed as error:
        # The whitelist prevents native diagnostics entering the IPC response.
        code = (
            error.code
            if error.code in {"unsupported_format", "overflow", "limit_reached"}
            else "failed"
        )
        reply(output, WorkerReply.model_validate({"status": "error", "error": code}))
    except Exception:
        reply(output, WorkerReply(status="error", error="failed"))


if __name__ == "__main__":
    run(sys.stdin.buffer, sys.stdout.buffer)
