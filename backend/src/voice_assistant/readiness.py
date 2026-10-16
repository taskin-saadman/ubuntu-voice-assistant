"""Bounded dependency checks, separate from process liveness and route handlers."""

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from enum import StrEnum
from typing import Literal

from voice_assistant.contracts import Schema


class ComponentName(StrEnum):
    CAPTURE = "capture"
    VAD = "vad"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    PLAYBACK = "playback"
    STORAGE = "storage"


class ComponentHealth(Schema):
    name: ComponentName
    status: Literal["ready", "not_configured", "unavailable", "timeout"]


class Readiness(Schema):
    status: Literal["ready", "not_ready"]
    components: tuple[ComponentHealth, ...]


Probe = Callable[[], Awaitable[bool]]


class ReadinessService:
    """Probes must be non-blocking and must not open the microphone or load models.

    Concurrent requests share each in-flight probe. A cancellation-resistant probe
    remains tracked, so polling readiness cannot create unbounded background work.
    """

    def __init__(
        self, probes: Mapping[ComponentName, Probe] | None = None, deadline: float = 1.0
    ) -> None:
        if not math.isfinite(deadline) or not 0 < deadline <= 10:
            raise ValueError("Readiness deadline must be between zero and ten seconds")
        self._probes = dict(probes or {})
        self._deadline = deadline
        self._pending: dict[ComponentName, asyncio.Task[bool]] = {}
        self._closed = False

    async def _check(self, name: ComponentName) -> ComponentHealth:
        if self._closed:
            return ComponentHealth(name=name, status="unavailable")
        probe = self._probes.get(name)
        if probe is None:
            return ComponentHealth(name=name, status="not_configured")
        task = self._pending.get(name)
        if task is None:

            async def invoke() -> bool:
                return await probe()

            task = asyncio.create_task(invoke(), name=f"readiness-{name.value}")
            self._pending[name] = task

            def finished(done: asyncio.Task[bool]) -> None:
                if self._pending.get(name) is done:
                    del self._pending[name]
                if not done.cancelled():
                    done.exception()

            task.add_done_callback(finished)
        done, _ = await asyncio.wait({task}, timeout=self._deadline)
        if not done:
            task.cancel()
            return ComponentHealth(name=name, status="timeout")
        try:
            ready = task.result()
        except (Exception, asyncio.CancelledError):
            ready = False
        return ComponentHealth(name=name, status="ready" if ready else "unavailable")

    async def check(self) -> Readiness:
        components = tuple(await asyncio.gather(*(self._check(name) for name in ComponentName)))
        ready = all(component.status == "ready" for component in components)
        return Readiness(status="ready" if ready else "not_ready", components=components)

    async def close(self) -> None:
        self._closed = True
        tasks = set(self._pending.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self._deadline)
