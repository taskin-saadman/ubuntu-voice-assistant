"""In-memory session storage; no persistent conversation history."""

from collections import deque

from voice_assistant.contracts import Message


class MemoryConversation:
    def __init__(self, capacity: int = 20) -> None:
        if capacity < 2:
            raise ValueError("History capacity must allow a user and assistant message")
        self._messages: deque[Message] = deque(maxlen=capacity)

    def append(self, message: Message) -> None:
        self._messages.append(message)

    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def clear(self) -> None:
        self._messages.clear()
