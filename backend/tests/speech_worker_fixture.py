"""Synthetic persistent speech subprocess, independent of models and devices."""

import signal
import sys

from voice_assistant.speech.models import SpeechReply, SpeechRequest
from voice_assistant.speech.worker import reply


def main() -> None:
    mode = sys.argv[1]
    first = SpeechRequest.model_validate_json(sys.stdin.buffer.readline())
    assert first.action == "initialize"
    if mode == "slow_init":
        signal.pause()
        return
    reply(sys.stdout.buffer, SpeechReply(status="ready"))
    while header := sys.stdin.buffer.readline():
        request = SpeechRequest.model_validate_json(header)
        if request.size:
            assert len(sys.stdin.buffer.read(request.size)) == request.size
        if request.action == "warmup":
            reply(sys.stdout.buffer, SpeechReply(status="ready"))
            continue
        if mode == "hang":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.pause()
            return
        if mode == "malformed":
            sys.stdout.buffer.write(b"secret engine diagnostic\n")
            sys.stdout.buffer.flush()
            return
        if mode == "wrong_status":
            reply(sys.stdout.buffer, SpeechReply(status="ready"))
            continue
        if request.action == "vad":
            reply(sys.stdout.buffer, SpeechReply(status="vad", speech=mode != "silence"))
        elif request.action == "transcribe":
            reply(
                sys.stdout.buffer,
                SpeechReply(
                    status="transcript", text="" if mode == "silence" else "Synthetic speech"
                ),
            )


if __name__ == "__main__":
    main()
