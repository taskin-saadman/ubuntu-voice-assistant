"""Non-blocking VAD and STT boundaries sharing one bounded native worker."""

import asyncio
import os
import sys
from asyncio.subprocess import PIPE, Process
from contextlib import suppress
from typing import Literal

from voice_assistant.audio.models import MAX_PCM_BYTES, TARGET_RATE
from voice_assistant.contracts import AudioBuffer
from voice_assistant.speech.models import (
    ERROR_MESSAGES,
    SpeechError,
    SpeechReply,
    SpeechRequest,
    SpeechSettings,
)


async def _launch() -> Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "voice_assistant.speech.worker",
        stdin=PIPE,
        stdout=PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=65536,
        env={
            **os.environ,
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "TOKENIZERS_PARALLELISM": "false",
        },
    )


async def _exchange(process: Process, request: SpeechRequest, pcm: bytes = b"") -> SpeechReply:
    if process.stdin is None or process.stdout is None:
        raise SpeechError(ERROR_MESSAGES["failed"])
    process.stdin.write(request.model_dump_json().encode() + b"\n")
    process.stdin.write(pcm)
    await process.stdin.drain()
    result = SpeechReply.model_validate_json(await process.stdout.readline())
    if result.error:
        raise SpeechError(ERROR_MESSAGES[result.error])
    return result


class SpeechWorker:
    """Lazy resident CPU worker. Cancellation kills inference, then permits reload.

    Methods must run on one asyncio loop. Overlap is rejected, not queued.
    close() is permanent; a cancelled request only resets the worker process.
    """

    def __init__(self, settings: SpeechSettings | None = None) -> None:
        self.settings = settings or SpeechSettings()
        self._spawn: asyncio.Task[Process] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._busy = False
        self._ready = False
        self._closed = False

    async def warmup(self) -> None:
        await self.request("warmup")

    async def request(
        self, action: Literal["warmup", "vad", "transcribe"], audio: AudioBuffer | None = None
    ) -> SpeechReply:
        if self._closed or self._busy or (self._cleanup and not self._cleanup.done()):
            raise SpeechError("Speech worker is busy or closed")
        if action != "warmup" and (
            audio is None or audio.sample_rate != TARGET_RATE or len(audio.pcm) > MAX_PCM_BYTES
        ):
            raise SpeechError(ERROR_MESSAGES["invalid_audio"])
        self._busy = True
        try:
            async with asyncio.timeout(self.settings.timeout):
                if self._spawn is None:
                    self._spawn = asyncio.create_task(_launch())
                process = await asyncio.shield(self._spawn)
                if self._closed:
                    raise SpeechError("Speech worker is closed")
                if not self._ready:
                    initialized = await _exchange(
                        process, SpeechRequest(action="initialize", settings=self.settings)
                    )
                    if initialized.status != "ready":
                        raise SpeechError(ERROR_MESSAGES["failed"])
                    self._ready = True
                pcm = audio.pcm if audio is not None else b""
                result = await _exchange(process, SpeechRequest(action=action, size=len(pcm)), pcm)
                expected = {"warmup": "ready", "vad": "vad", "transcribe": "transcript"}[action]
                if result.status != expected or self._closed:
                    raise SpeechError(ERROR_MESSAGES["failed"])
                return result
        except asyncio.CancelledError:
            await self._reset()
            raise
        except SpeechError:
            await self._reset()
            raise
        except TimeoutError:
            await self._reset()
            raise SpeechError("Speech recognition timed out. Try a shorter recording.") from None
        except Exception:
            await self._reset()
            raise SpeechError(ERROR_MESSAGES["failed"]) from None
        finally:
            self._busy = False

    async def close(self) -> None:
        self._closed = True
        await self._reset()

    async def _reset(self) -> None:
        self._ready = False
        if self._cleanup is None or self._cleanup.done():
            self._cleanup = asyncio.create_task(self._stop())
            self._cleanup.add_done_callback(self._consume_error)
        await asyncio.shield(self._cleanup)

    @staticmethod
    def _consume_error(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _stop(self) -> None:
        if self._spawn is None:
            return
        try:
            process = await asyncio.shield(self._spawn)
        except Exception:
            self._spawn = None
            return
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                async with asyncio.timeout(0.25):
                    await process.wait()
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                try:
                    async with asyncio.timeout(0.5):
                        await process.wait()
                except TimeoutError:
                    self._closed = True
                    raise SpeechError(
                        "Speech worker could not stop. Restart the backend."
                    ) from None
        if process.stdin is not None:
            process.stdin.close()
        self._spawn = None


class SileroVAD:
    def __init__(self, worker: SpeechWorker) -> None:
        self.worker = worker

    async def has_speech(self, audio: AudioBuffer) -> bool:
        result = await self.worker.request("vad", audio)
        assert result.speech is not None  # Validated by the reply schema and expected status.
        return result.speech


class WhisperTranscriber:
    def __init__(self, worker: SpeechWorker) -> None:
        self.worker = worker

    async def transcribe(self, audio: AudioBuffer) -> str:
        result = await self.worker.request("transcribe", audio)
        assert result.text is not None
        return result.text.strip()
