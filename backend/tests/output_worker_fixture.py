"""Synthetic TTS/playback IPC processes; never access models or devices."""

import json
import signal
import sys


def send(value: object, data: bytes = b"") -> None:
    sys.stdout.buffer.write(json.dumps(value).encode() + b"\n" + data)
    sys.stdout.buffer.flush()


def main() -> None:
    mode = sys.argv[1]
    source = sys.stdin.buffer
    request = json.loads(source.readline())
    if "action" not in request:  # Initial TTS settings, followed by synthesis requests.
        while source.readline():
            if mode == "hang":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                signal.pause()
            elif mode == "malformed":
                print("private diagnostic", flush=True)
                return
            elif mode == "oversized":
                send({"status": "audio", "sample_rate": 22050, "size": 10**9})
            elif mode == "truncated":
                send({"status": "audio", "sample_rate": 22050, "size": 200}, b"\0\0")
                return
            elif mode == "error":
                send({"status": "error"})
            else:
                send({"status": "audio", "sample_rate": 22050, "size": 200}, b"\0\0" * 100)
        return
    if request["action"] == "devices":
        send(
            {
                "status": "devices",
                "devices": [{"index": 4, "name": "Synthetic output", "sample_rate": 48000}],
            }
        )
        return
    assert len(source.read(request["size"])) == request["size"]
    if mode == "early_error":
        send({"status": "error"})
        return
    if mode == "slow_start":
        signal.pause()
    if mode == "malformed":
        print("private diagnostic", flush=True)
        return
    send({"status": "started"})
    if mode == "hang":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.pause()
    if mode == "late_error":
        send({"status": "error"})
    else:
        send({"status": "finished"})


if __name__ == "__main__":
    main()
