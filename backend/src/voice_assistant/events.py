"""Versioned events for a future authenticated UI transport, not log records."""

from collections import deque
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from voice_assistant.contracts import Message, Schema
from voice_assistant.state import AssistantState


class ErrorCode(StrEnum):
    CAPTURE_FAILED = "capture_failed"
    STT_UNAVAILABLE = "stt_unavailable"
    LLM_UNAVAILABLE = "llm_unavailable"
    TTS_UNAVAILABLE = "tts_unavailable"
    PLAYBACK_FAILED = "playback_failed"
    INVALID_RESPONSE = "invalid_response"
    CONTEXT_TOO_LONG = "context_too_long"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CLEANUP_FAILED = "cleanup_failed"
    INTERNAL_ERROR = "internal_error"


class Failure(Schema):
    code: ErrorCode
    message: str


class Event(Schema):
    version: Literal[1] = 1
    sequence: int = Field(ge=1)
    turn_id: UUID | None
    kind: Literal["state", "message", "error", "finished", "microphone"]
    state: AssistantState | None = None
    message: Message | None = Field(default=None, repr=False)
    failure: Failure | None = None
    outcome: Literal["completed", "cancelled", "no_speech", "failed"] | None = None
    microphone_enabled: bool | None = None

    @model_validator(mode="after")
    def check_payload(self) -> "Event":
        fields = {
            "state": self.state,
            "message": self.message,
            "error": self.failure,
            "finished": self.outcome,
            "microphone": self.microphone_enabled,
        }
        if fields[self.kind] is None or sum(value is not None for value in fields.values()) != 1:
            raise ValueError("Event must have exactly the payload matching its kind")
        if self.kind in {"message", "finished"} and self.turn_id is None:
            raise ValueError("Turn events require a turn ID")
        return self


class EventBuffer:
    """A bounded local journal. Sequence gaps require the UI to request a snapshot."""

    def __init__(self, capacity: int = 256) -> None:
        if capacity < 1:
            raise ValueError("Event capacity must be positive")
        self._events: deque[Event] = deque(maxlen=capacity)
        self._sequence = 0

    @property
    def next_sequence(self) -> int:
        return self._sequence + 1

    def append(self, event: Event) -> None:
        if event.sequence != self.next_sequence:
            raise ValueError("Event sequence must increase without gaps")
        self._sequence = event.sequence
        self._events.append(event)

    def read(self, after: int = 0) -> tuple[Event, ...]:
        return tuple(event for event in self._events if event.sequence > after)
