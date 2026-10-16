"""Subprocess fixture using synthetic PCM only. Never imports sounddevice."""

import signal
import sys

from voice_assistant.audio.models import InputDevice, WorkerReply, WorkerRequest
from voice_assistant.audio.worker import reply


def main() -> None:
    mode = sys.argv[1]
    request = WorkerRequest.model_validate_json(sys.stdin.buffer.readline())
    if mode == "slow_start":
        signal.pause()
        return
    if mode == "devices":
        assert request.action == "devices"
        reply(
            sys.stdout.buffer,
            WorkerReply(
                status="devices",
                devices=(InputDevice(index=2, name="Synthetic input", sample_rate=48000),),
            ),
        )
        return
    assert request.action == "capture"
    if mode == "unavailable":
        reply(sys.stdout.buffer, WorkerReply(status="error", error="unavailable"))
        return
    if mode == "ignore_term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    reply(sys.stdout.buffer, WorkerReply(status="started"))
    sys.stdin.buffer.readline()
    if mode in {"hang_read", "ignore_term"}:
        signal.pause()
    elif mode == "malformed":
        sys.stdout.buffer.write(b"secret diagnostic\n")
    elif mode == "oversized":
        sys.stdout.buffer.write(b'{"status":"audio","size":99999999}\n')
    elif mode == "truncated":
        reply(sys.stdout.buffer, WorkerReply(status="audio", size=3200), b"\0\0")
    else:
        reply(sys.stdout.buffer, WorkerReply(status="audio", size=3200), b"\0\0" * 1600)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
