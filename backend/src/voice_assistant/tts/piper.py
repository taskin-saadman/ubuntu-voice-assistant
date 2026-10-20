"""Cancellable async adapter for the resident CPU synthesis worker."""

import asyncio

from voice_assistant.contracts import AudioBuffer
from voice_assistant.local_worker import LocalWorker
from voice_assistant.tts.models import (
    PiperSettings,
    SynthesisError,
    SynthesisReply,
    SynthesisRequest,
)


class PiperSynthesizer:
    def __init__(self, settings: PiperSettings | None = None) -> None:
        self.settings = settings or PiperSettings()
        self.worker = LocalWorker("voice_assistant.tts.worker")
        self._initialized = False
        self._busy = False
        self._closed = False

    async def synthesize(self, text: str) -> AudioBuffer:
        if self._closed or self._busy:
            raise SynthesisError("Speech synthesis is busy or closed")
        self._busy = True
        try:
            request = SynthesisRequest(text=text)
            async with asyncio.timeout(self.settings.timeout):
                process = await self.worker.start()
                if self._closed or process.stdin is None or process.stdout is None:
                    raise RuntimeError("Synthesis worker unavailable")
                if not self._initialized:
                    process.stdin.write(self.settings.model_dump_json().encode() + b"\n")
                    self._initialized = True
                process.stdin.write(request.model_dump_json().encode() + b"\n")
                await process.stdin.drain()
                reply = SynthesisReply.model_validate_json(await process.stdout.readline())
                if reply.status != "audio":
                    raise RuntimeError("Synthesis failed")
                pcm = await process.stdout.readexactly(reply.size)
                return AudioBuffer(pcm=pcm, sample_rate=reply.sample_rate)
        except asyncio.CancelledError:
            await self._reset()
            raise
        except Exception:
            await self._reset()
            raise SynthesisError(
                "Speech synthesis failed. Check Piper and the local voice."
            ) from None
        finally:
            self._busy = False

    async def _reset(self) -> None:
        self._initialized = False
        await self.worker.stop()

    async def close(self) -> None:
        self._closed = True
        await self._reset()
