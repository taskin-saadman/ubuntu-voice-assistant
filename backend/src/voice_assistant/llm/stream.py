"""Bounded SSE framing and strict single-answer parsing for llama.cpp."""

import json
from collections.abc import AsyncIterator

from pydantic import BaseModel, Field, ValidationError

from voice_assistant.contracts import InvalidModelResponse

MAX_BODY = 1_048_576
MAX_EVENT = 32768
MARKERS = ("<think", "</think", "<|", "<tool_call", "</tool_call", "[tool_calls]")


async def sse_data(chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
    pending = b""
    fields: list[str] = []
    event_size = total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > MAX_BODY:
            raise InvalidModelResponse()
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            line = line.removesuffix(b"\r")
            event_size += len(line) + 1
            if event_size > MAX_EVENT:
                raise InvalidModelResponse()
            if not line:
                if fields:
                    yield "\n".join(fields)
                fields = []
                event_size = 0
            elif line.startswith(b"data:"):
                try:
                    fields.append(line[5:].removeprefix(b" ").decode("utf-8", errors="strict"))
                except UnicodeError:
                    raise InvalidModelResponse() from None
            elif not line.startswith((b":", b"event:", b"id:", b"retry:")):
                raise InvalidModelResponse()
        if len(pending) + event_size > MAX_EVENT:
            raise InvalidModelResponse()
    if pending or fields:
        raise InvalidModelResponse()


class Delta(BaseModel):
    role: str | None = None
    content: str | None = Field(default=None, max_length=8192)
    reasoning_content: str | None = None
    reasoning: str | None = None
    tool_calls: list[object] | None = None
    function_call: dict[str, object] | None = None


class Choice(BaseModel):
    index: int = Field(strict=True)
    delta: Delta
    finish_reason: str | None = None


class Chunk(BaseModel):
    choices: list[Choice] = Field(max_length=1)
    error: object | None = None


class AnswerParser:
    def __init__(self) -> None:
        self.text = ""
        self.pending = ""
        self.stopped = False
        self.done = False

    def feed(self, data: str) -> str:
        if self.done:
            raise InvalidModelResponse()
        if data == "[DONE]":
            if not self.stopped or not self.text.strip() or self.pending:
                raise InvalidModelResponse()
            self.done = True
            return ""
        try:
            chunk = Chunk.model_validate(json.loads(data))
        except (ValueError, ValidationError):
            raise InvalidModelResponse() from None
        if chunk.error is not None:
            raise InvalidModelResponse()
        if not chunk.choices:  # Optional final usage-only chunk.
            if not self.stopped:
                raise InvalidModelResponse()
            return ""
        choice = chunk.choices[0]
        d = choice.delta
        if (
            self.stopped
            or choice.index != 0
            or d.role not in {None, "assistant"}
            or d.reasoning_content
            or d.reasoning
            or d.tool_calls
            or d.function_call
        ):
            raise InvalidModelResponse()
        content = self.pending + (d.content or "")
        if any(marker in content.lower() for marker in MARKERS):
            raise InvalidModelResponse()
        if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in content):
            raise InvalidModelResponse()
        if len(self.text) + len(content) > 8192:
            raise InvalidModelResponse()
        # Withhold marker prefixes even when a model splits them across token chunks.
        held = max(
            (
                n
                for n in range(1, min(len(content), 20) + 1)
                if any(m.startswith(content[-n:].lower()) for m in MARKERS)
            ),
            default=0,
        )
        self.pending = content[-held:] if held else ""
        safe = content[:-held] if held else content
        self.text += safe
        if choice.finish_reason is not None:
            if choice.finish_reason != "stop" or self.pending:
                raise InvalidModelResponse()
            self.stopped = True
        return safe

    def result(self) -> str:
        if not self.done:
            raise InvalidModelResponse()
        return self.text.strip()
