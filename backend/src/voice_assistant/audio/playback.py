"""Each playback owns an isolated PortAudio worker until audio drains or is stopped."""

import asyncio
from collections.abc import Callable

from voice_assistant.audio.output_models import (
    OutputDevice,
    OutputReply,
    OutputRequest,
    PlaybackError,
    PlaybackSettings,
)
from voice_assistant.contracts import AudioBuffer
from voice_assistant.local_worker import LocalWorker


class AudioPlayback:
    def __init__(self, settings: PlaybackSettings | None = None) -> None:
        self.settings = settings or PlaybackSettings()
        self.worker = LocalWorker("voice_assistant.audio.output_worker")
        self._busy = False

    async def play(self, audio: AudioBuffer, on_started: Callable[[], None]) -> None:
        if self._busy:
            raise PlaybackError("Playback already active")
        self._busy = True
        try:
            async with asyncio.timeout(5):
                process = await self.worker.start()
                if process.stdin is None or process.stdout is None:
                    raise RuntimeError("Playback worker unavailable")
                request = OutputRequest(
                    action="play",
                    settings=self.settings,
                    size=len(audio.pcm),
                    sample_rate=audio.sample_rate,
                )
                process.stdin.write(request.model_dump_json().encode() + b"\n")
                process.stdin.write(audio.pcm)
                await process.stdin.drain()
                reply = OutputReply.model_validate_json(await process.stdout.readline())
                if reply.status != "started":
                    raise RuntimeError("Playback did not start")
                on_started()
            async with asyncio.timeout(audio.duration + 5):
                reply = OutputReply.model_validate_json(await process.stdout.readline())
                if reply.status != "finished" or await process.wait() != 0:
                    raise RuntimeError("Playback did not finish")
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PlaybackError(
                "Audio playback failed. Check the selected output device."
            ) from None
        finally:
            try:
                await self.stop()
            finally:
                self._busy = False

    async def stop(self) -> None:
        try:
            await self.worker.stop()
        except Exception:
            raise PlaybackError("Audio output could not stop. Restart the backend.") from None


async def output_devices() -> tuple[OutputDevice, ...]:
    worker = LocalWorker("voice_assistant.audio.output_worker")
    try:
        async with asyncio.timeout(4):
            process = await worker.start()
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Output worker unavailable")
            process.stdin.write(OutputRequest(action="devices").model_dump_json().encode() + b"\n")
            await process.stdin.drain()
            reply = OutputReply.model_validate_json(await process.stdout.readline())
            if reply.status != "devices" or await process.wait() != 0:
                raise RuntimeError("Invalid output devices")
            return reply.devices
    except Exception:
        raise PlaybackError("Audio outputs could not be listed. Check PortAudio.") from None
    finally:
        await worker.stop()
