"""Explicit state transitions independent of engines and HTTP."""

from enum import StrEnum


class AssistantState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    ACTING = "acting"
    SPEAKING = "speaking"
    ERROR = "error"


class InvalidTransition(ValueError):
    pass


class StateMachine:
    _allowed = {
        AssistantState.IDLE: {AssistantState.LISTENING, AssistantState.ERROR},
        AssistantState.LISTENING: {
            AssistantState.TRANSCRIBING,
            AssistantState.IDLE,
            AssistantState.ERROR,
        },
        AssistantState.TRANSCRIBING: {
            AssistantState.THINKING,
            AssistantState.IDLE,
            AssistantState.ERROR,
        },
        AssistantState.THINKING: {
            AssistantState.ACTING,
            AssistantState.SPEAKING,
            AssistantState.IDLE,
            AssistantState.ERROR,
        },
        AssistantState.ACTING: {
            AssistantState.THINKING,
            AssistantState.IDLE,
            AssistantState.ERROR,
        },
        AssistantState.SPEAKING: {AssistantState.IDLE, AssistantState.ERROR},
        AssistantState.ERROR: {AssistantState.IDLE},
    }

    def __init__(self) -> None:
        self._state = AssistantState.IDLE

    @property
    def state(self) -> AssistantState:
        return self._state

    def transition(self, target: AssistantState) -> None:
        if target not in self._allowed[self._state]:
            raise InvalidTransition(f"Cannot transition from {self._state} to {target}")
        self._state = target
