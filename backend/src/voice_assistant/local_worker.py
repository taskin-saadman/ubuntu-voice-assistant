"""Ownership of an inert subprocess, including cancellation during process creation."""

import asyncio
import sys
from asyncio.subprocess import PIPE, Process
from contextlib import suppress


class LocalWorker:
    def __init__(self, module: str) -> None:
        self.module = module
        self._spawn: asyncio.Task[Process] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._generation = 0
        self._stopping = False

    async def _launch(self) -> Process:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            self.module,
            stdin=PIPE,
            stdout=PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            limit=65536,
        )

    async def start(self) -> Process:
        if self._stopping:
            raise RuntimeError("Worker is stopping")
        generation = self._generation
        if self._spawn is None:
            self._spawn = asyncio.create_task(self._launch())
        process = await asyncio.shield(self._spawn)
        if self._stopping or generation != self._generation:
            raise RuntimeError("Worker start cancelled")
        return process

    async def stop(self) -> None:
        self._generation += 1
        self._stopping = True
        if self._cleanup is None or self._cleanup.done():
            self._cleanup = asyncio.create_task(self._stop())
            self._cleanup.add_done_callback(self._consume)
        await asyncio.shield(self._cleanup)

    @staticmethod
    def _consume(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    async def _stop(self) -> None:
        if self._spawn is not None:
            try:
                process = await asyncio.shield(self._spawn)
            except Exception:
                self._spawn = None
            else:
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
        self._stopping = False
