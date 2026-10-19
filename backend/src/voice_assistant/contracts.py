"""Typed, replaceable component boundaries for the voice pipeline."""

from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AudioBuffer(Schema):
    """Mono signed 16-bit little-endian PCM; never part of transport JSON."""

    pcm: bytes = Field(repr=False, exclude=True, min_length=2, max_length=11_520_000)
    sample_rate: int = Field(ge=8000, le=48000)

    @model_validator(mode="after")
    def check_frames(self) -> "AudioBuffer":
        if len(self.pcm) % 2 or self.duration > 120:
            raise ValueError("Audio must contain whole frames and at most 120 seconds")
        return self

    @property
    def duration(self) -> float:
        return len(self.pcm) / (2 * self.sample_rate)


class Message(Schema):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8192, repr=False)

    @model_validator(mode="after")
    def check_text(self) -> "Message":
        if not self.content.strip():
            raise ValueError("Message must contain text")
        return self


class Capture(Protocol):
    """start opens the device; finish closes it; abort is idempotent.

    Implementations must bound buffers, avoid blocking the event loop, and release
    devices on cancellation. A cancelled start must not later reopen a device.
    """

    async def start(self) -> None: ...
    async def finish(self) -> AudioBuffer: ...
    async def abort(self) -> None: ...


class VoiceActivityDetector(Protocol):
    async def has_speech(self, audio: AudioBuffer) -> bool: ...


class Transcriber(Protocol):
    async def transcribe(self, audio: AudioBuffer) -> str: ...


class LanguageModel(Protocol):
    async def respond(
        self, messages: tuple[Message, ...], on_delta: Callable[[str], None] | None = None
    ) -> str: ...


class InvalidModelResponse(RuntimeError):
    """The model response is incomplete, malformed or contains control content."""


class ContextLimitExceeded(RuntimeError):
    """The latest user message cannot fit with the system instruction and output budget."""


class Synthesizer(Protocol):
    async def synthesize(self, text: str) -> AudioBuffer: ...


class Playback(Protocol):
    """Call on_started only once audio begins; return after playback ends.

    stop is idempotent. Cancellation must release the output device. Adapters
    must not execute blocking inference/playback directly on the event loop.
    """

    async def play(self, audio: AudioBuffer, on_started: Callable[[], None]) -> None: ...
    async def stop(self) -> None: ...


class ConversationStore(Protocol):
    """Bounded session history; no disk writes in Phase 2."""

    def append(self, message: Message) -> None: ...
    def messages(self) -> tuple[Message, ...]: ...
    def clear(self) -> None: ...
