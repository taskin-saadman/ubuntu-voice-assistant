"""Async ownership of an isolated PortAudio capture worker."""

import asyncio
import sys
from asyncio.subprocess import PIPE, Process
from contextlib import suppress

from voice_assistant.audio.models import (
    ERROR_MESSAGES,
    TARGET_RATE,
    CaptureError,
    CaptureSettings,
    InputDevice,
    WorkerReply,
    WorkerRequest,
)
from voice_assistant.contracts import AudioBuffer


async def _launch() -> Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "voice_assistant.audio.worker",
        stdin=PIPE,
        stdout=PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        # Header JSON is small; PCM uses a separately validated exact byte count.
        limit=65536,
    )


async def _send(process: Process, request: bytes) -> None:
    if process.stdin is None:
        raise CaptureError("Microphone worker is unavailable")
    process.stdin.write(request)
    await process.stdin.drain()


async def _reply(process: Process) -> WorkerReply:
    if process.stdout is None:
        raise CaptureError("Microphone worker is unavailable")
    try:
        message = WorkerReply.model_validate_json(await process.stdout.readline())
    except (ValueError, OSError):
        raise CaptureError("Microphone worker returned an invalid response") from None
    if message.error:
        raise CaptureError(ERROR_MESSAGES[message.error])
    return message


class MicrophoneCapture:
    """One short-lived process owns the device and ephemeral audio per recording.

    No devices are touched until start(). finish() returns mono 16 kHz int16 PCM.
    Cancellation and abort terminate/reap the worker, including blocked native
    calls. Cleanup survives cancellation of its caller and is shared by aborts.
    """

    def __init__(self, settings: CaptureSettings | None = None) -> None:
        self.settings = settings or CaptureSettings()
        self._spawn: asyncio.Task[Process] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._stopping = False
        self._expired = False
        self._finishing = False
        self._generation = 0

    async def start(self) -> None:
        if self._spawn is not None or self._stopping:
            raise CaptureError("Microphone is already in use")
        self._expired = False
        self._generation += 1
        generation = self._generation
        self._spawn = asyncio.create_task(_launch())
        try:
            async with asyncio.timeout(4):
                process = await asyncio.shield(self._spawn)
                if self._stopping or generation != self._generation:
                    raise CaptureError("Microphone capture was cancelled")
                request = WorkerRequest(action="capture", settings=self.settings)
                await _send(process, request.model_dump_json().encode() + b"\n")
                if (await _reply(process)).status != "started":
                    raise CaptureError("Microphone worker did not start recording")
                if self._stopping or generation != self._generation:
                    raise CaptureError("Microphone capture was cancelled")
            self._watchdog = asyncio.create_task(self._expire())
        except asyncio.CancelledError:
            await self.abort()
            raise
        except CaptureError:
            await self.abort()
            raise
        except Exception:
            await self.abort()
            raise CaptureError(ERROR_MESSAGES["failed"]) from None

    async def _expire(self) -> None:
        await asyncio.sleep(self.settings.max_seconds)
        self._expired = True
        try:
            await self.abort()
        except CaptureError:
            # Ownership remains reserved after failed cleanup; finish/abort report it.
            pass

    async def finish(self) -> AudioBuffer:
        if self._expired:
            await self.abort()
            raise CaptureError(ERROR_MESSAGES["limit_reached"])
        if self._spawn is None or self._stopping or self._finishing:
            raise CaptureError("Microphone is not recording")
        self._finishing = True
        if self._watchdog is not None:
            self._watchdog.cancel()
        try:
            async with asyncio.timeout(4):
                process = await asyncio.shield(self._spawn)
                await _send(process, b"finish\n")
                message = await _reply(process)
                if message.status != "audio" or process.stdout is None:
                    raise CaptureError("Microphone worker returned an invalid response")
                pcm = await process.stdout.readexactly(message.size)
                if await process.wait() != 0:
                    raise CaptureError("Microphone worker stopped unexpectedly")
                audio = AudioBuffer(pcm=pcm, sample_rate=TARGET_RATE)
                if audio.duration > self.settings.max_seconds:
                    raise CaptureError("Microphone worker exceeded the recording limit")
                return audio
        except (TimeoutError, EOFError, OSError):
            raise CaptureError(ERROR_MESSAGES["failed"]) from None
        finally:
            self._finishing = False
            await self.abort()

    async def abort(self) -> None:
        self._generation += 1
        self._stopping = True
        if self._watchdog is not None and self._watchdog is not asyncio.current_task():
            self._watchdog.cancel()
        if self._cleanup is None or self._cleanup.done():
            self._cleanup = asyncio.create_task(self._stop())
            self._cleanup.add_done_callback(self._consume_cleanup_error)
        await asyncio.shield(self._cleanup)

    @staticmethod
    def _consume_cleanup_error(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _stop(self) -> None:
        # Keep ownership reserved until the child is reaped. A delayed spawn is
        # inert (waiting for a request), and start checks _stopping before sending.
        if self._spawn is not None:
            try:
                process = await asyncio.shield(self._spawn)
            except Exception:
                self._spawn = None
            else:
                try:
                    if process.returncode is None:
                        with suppress(ProcessLookupError):
                            process.terminate()
                        try:
                            async with asyncio.timeout(0.25):
                                await process.wait()
                        except TimeoutError:
                            with suppress(ProcessLookupError):
                                process.kill()
                            async with asyncio.timeout(0.5):
                                await process.wait()
                    if process.stdin is not None:
                        process.stdin.close()
                    self._spawn = None
                except (OSError, TimeoutError):
                    raise CaptureError(
                        "Microphone could not be stopped. Restart the backend."
                    ) from None
        self._stopping = False


async def input_devices() -> tuple[InputDevice, ...]:
    """Enumerate compatible inputs without recording or changing the default device."""
    owner = MicrophoneCapture()
    owner._spawn = asyncio.create_task(_launch())
    try:
        async with asyncio.timeout(4):
            process = await asyncio.shield(owner._spawn)
            await _send(process, WorkerRequest(action="devices").model_dump_json().encode() + b"\n")
            result = await _reply(process)
            if result.status != "devices" or await process.wait() != 0:
                raise CaptureError("Input devices could not be listed")
            return result.devices
    finally:
        await owner.abort()
