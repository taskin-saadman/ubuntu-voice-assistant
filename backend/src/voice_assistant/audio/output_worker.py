"""Private PortAudio playback process. No microphone, disk writes or shell commands."""

import select
import sys
import threading
from collections.abc import Callable
from time import monotonic
from typing import Any, BinaryIO

from voice_assistant.audio.normalize import normalize
from voice_assistant.audio.output_models import OutputDevice, OutputReply, OutputRequest
from voice_assistant.contracts import AudioBuffer


class PCMPlayer:
    """Fill output callback buffers, padding only the final partial block with silence."""

    def __init__(self, pcm: bytes, channels: int) -> None:
        self.pcm = pcm
        self.frame_bytes = channels * 2
        self.offset = 0

    def fill(self, output: Any, frames: int) -> bool:
        size = frames * self.frame_bytes
        part = self.pcm[self.offset : self.offset + size]
        output[:] = part + b"\0" * (size - len(part))
        self.offset += len(part)
        return self.offset == len(self.pcm)


def play(
    audio: AudioBuffer,
    device: int | None,
    started: Callable[[], None],
    disconnected: Callable[[], bool],
) -> None:
    import numpy as np
    import sounddevice as sd  # type: ignore[import-untyped]

    info = sd.query_devices(device, "output")
    rate = int(info["default_samplerate"])
    channels = min(2, int(info["max_output_channels"]))
    if channels < 1 or not 8000 <= rate <= 48000:
        raise ValueError("Unsupported output device")
    audio = normalize(audio, rate)
    pcm = audio.pcm
    if channels == 2:
        pcm = np.repeat(np.frombuffer(pcm, dtype="<i2"), 2).tobytes()
    sd.check_output_settings(device=device, channels=channels, dtype="int16", samplerate=rate)
    player = PCMPlayer(pcm, channels)
    first = threading.Event()
    finished = threading.Event()
    failed = threading.Event()
    dac_time = 0.0

    def callback(output: Any, frames: int, timing: Any, status: Any) -> None:
        nonlocal dac_time
        try:
            if status:
                raise ValueError("Output underflow")
            last = player.fill(output, frames)
            if not first.is_set():
                dac_time = float(timing.outputBufferDacTime)
                first.set()
        except Exception:
            output[:] = b"\0" * (frames * channels * 2)
            failed.set()
            raise sd.CallbackAbort from None
        if last:
            raise sd.CallbackStop

    stream = sd.RawOutputStream(
        device=device,
        channels=channels,
        samplerate=rate,
        dtype="int16",
        blocksize=max(1, rate // 50),
        callback=callback,
        finished_callback=finished.set,
    )
    try:
        stream.start()
        deadline = monotonic() + 3
        while not first.wait(0.005):
            if failed.is_set() or finished.is_set() or disconnected() or monotonic() > deadline:
                raise RuntimeError("Output did not start")
        # The callback runs ahead of the DAC. Announce speaking at its first buffer's
        # scheduled device time, not at device-open or buffer-enqueue time.
        while stream.time < dac_time:
            if failed.is_set() or disconnected() or monotonic() > deadline:
                raise RuntimeError("Output did not start")
            threading.Event().wait(0.005)
        if failed.is_set() or disconnected():
            raise RuntimeError("Output stopped")
        started()
        deadline = monotonic() + audio.duration + 3
        while not finished.wait(0.01):
            if failed.is_set() or disconnected() or monotonic() > deadline:
                raise RuntimeError("Output did not finish")
        if failed.is_set():
            raise RuntimeError("Output failed")
    finally:
        # Normal completion has already drained; errors discard queued audio.
        try:
            stream.abort()
        finally:
            stream.close()


def reply(output: BinaryIO, message: OutputReply) -> None:
    output.write(message.model_dump_json().encode() + b"\n")
    output.flush()


def run(source: BinaryIO, output: BinaryIO) -> None:
    try:
        request = OutputRequest.model_validate_json(source.readline(4096))
        if request.action == "devices":
            import sounddevice as sd

            devices = tuple(
                OutputDevice(index=i, name=str(d["name"])[:256], sample_rate=int(rate))
                for i, d in enumerate(sd.query_devices())
                if d["max_output_channels"] >= 1
                and 8000 <= (rate := d["default_samplerate"]) <= 48000
            )[:128]
            reply(output, OutputReply(status="devices", devices=devices))
            return
        pcm = source.read(request.size)
        if len(pcm) != request.size:
            raise ValueError("Incomplete audio")
        audio = AudioBuffer(pcm=pcm, sample_rate=request.sample_rate)
        play(
            audio,
            request.settings.device,
            lambda: reply(output, OutputReply(status="started")),
            lambda: bool(select.select([source], [], [], 0)[0]),
        )
        reply(output, OutputReply(status="finished"))
    except Exception:
        reply(output, OutputReply(status="error"))


if __name__ == "__main__":
    run(sys.stdin.buffer, sys.stdout.buffer)
