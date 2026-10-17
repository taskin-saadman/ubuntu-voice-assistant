"""Deterministic adapters: no devices, downloads or native inference imports."""

import asyncio
from collections.abc import Callable

from voice_assistant.contracts import AudioBuffer, Message
from voice_assistant.controller import Components
from voice_assistant.storage import MemoryConversation

AUDIO = AudioBuffer(pcm=b"\0\0" * 1600, sample_rate=16000)


class FakeEngines:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.entered: dict[str, asyncio.Event] = {}
        self.gates: dict[str, asyncio.Event] = {}
        self.fail_at: str | None = None
        self.speech = True
        self.text = "A synthetic test question"
        self.answer = "A synthetic test answer"
        self.callback: Callable[[], None] | None = None
        self.capturing = False
        self.playing = False
        self.prompt: tuple[Message, ...] = ()

    async def step(self, name: str) -> None:
        self.calls.append(name)
        self.entered.setdefault(name, asyncio.Event()).set()
        if name in self.gates:
            await self.gates[name].wait()
        if name == self.fail_at:
            raise RuntimeError("sensitive engine diagnostic must never be logged")

    async def reached(self, name: str) -> None:
        async with asyncio.timeout(1):
            await self.entered.setdefault(name, asyncio.Event()).wait()

    async def start(self) -> None:
        await self.step("start")
        self.capturing = True

    async def finish(self) -> AudioBuffer:
        await self.step("finish")
        self.capturing = False
        return AUDIO

    async def abort(self) -> None:
        await self.step("abort")
        self.capturing = False

    async def has_speech(self, audio: AudioBuffer) -> bool:
        await self.step("vad")
        return self.speech

    async def transcribe(self, audio: AudioBuffer) -> str:
        await self.step("stt")
        return self.text

    async def respond(
        self, messages: tuple[Message, ...], on_delta: Callable[[str], None] | None = None
    ) -> str:
        self.prompt = messages
        await self.step("llm")
        return self.answer

    async def synthesize(self, text: str) -> AudioBuffer:
        await self.step("tts")
        return AUDIO

    async def play(self, audio: AudioBuffer, on_started: Callable[[], None]) -> None:
        self.callback = on_started
        await self.step("play_start")
        self.playing = True
        on_started()
        await self.step("play")
        self.playing = False

    async def stop(self) -> None:
        await self.step("stop")
        self.playing = False

    def components(self) -> Components:
        return Components(
            capture=self,
            vad=self,
            stt=self,
            llm=self,
            tts=self,
            playback=self,
            history=MemoryConversation(),
        )
