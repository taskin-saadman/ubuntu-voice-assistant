import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from voice_assistant.contracts import ContextLimitExceeded, InvalidModelResponse, Message
from voice_assistant.llm.client import LlamaClient
from voice_assistant.llm.models import LlamaSettings
from voice_assistant.llm.stream import AnswerParser, sse_data


def event(content: str = "", finish: str | None = None, **extra: object) -> str:
    return json.dumps(
        {
            "choices": [
                {"index": 0, "delta": {"content": content, **extra}, "finish_reason": finish}
            ]
        },
        ensure_ascii=False,
    )


def wire(*events: str) -> bytes:
    return "".join(f"data: {item}\r\n\r\n" for item in events).encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, data: bytes, *, blocked: bool = False) -> None:
        self.data = data
        self.closed = False
        self.entered = asyncio.Event()
        self.blocked = blocked

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for byte in self.data:
            yield bytes([byte])
        self.entered.set()
        if self.blocked:
            await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


class Server:
    def __init__(self, stream: Stream | None = None) -> None:
        self.stream = stream or Stream(wire(event("Hello café 👋"), event(finish="stop"), "[DONE]"))
        self.calls: list[httpx.Request] = []
        self.prompts: list[dict[str, object]] = []
        self.tokens = 100
        self.trim = False
        self.failure = ""

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.url.host == "127.0.0.1"
        path = request.url.path
        if self.failure == "redirect":
            return httpx.Response(307, headers={"location": "https://example.invalid/private"})
        if self.failure == "offline":
            raise httpx.ConnectError("private native error", request=request)
        if self.failure == "unavailable":
            return httpx.Response(503, json={"error": "private server detail"})
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/apply-template":
            self.prompts.append(json.loads(request.content))
            return httpx.Response(200, json={"prompt": "synthetic template"})
        if path == "/tokenize":
            count = self.tokens
            if self.trim and len(self.prompts[-1]["messages"]) > 2:  # type: ignore[arg-type]
                count = 4096
            return httpx.Response(200, json={"tokens": [1] * count})
        assert path == "/v1/chat/completions"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=self.stream
        )

    def client(self, timeout: float = 55) -> LlamaClient:
        return LlamaClient(
            LlamaSettings(timeout=timeout), transport=httpx.MockTransport(self.handle)
        )


QUESTION = (Message(role="user", content="Synthetic question"),)


async def test_unicode_stream_and_request_options() -> None:
    server = Server()
    client = server.client()
    pieces: list[str] = []
    try:
        assert await client.available()
        assert await client.respond(QUESTION, pieces.append) == "Hello café 👋"
        assert "".join(pieces) == "Hello café 👋"
        body = json.loads(server.calls[-1].content)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["reasoning_format"] == "deepseek" and body["stream"] is True
        assert body["max_tokens"] == 384 and "tools" not in body
        assert server.stream.closed
    finally:
        await client.close()


async def test_context_drops_old_pairs_and_orphan_messages_without_changing_history() -> None:
    server = Server()
    server.trim = True
    client = server.client()
    history = (
        Message(role="assistant", content="orphan"),
        Message(role="user", content="failed"),
        Message(role="user", content="old question"),
        Message(role="assistant", content="old answer"),
        *QUESTION,
    )
    try:
        await client.respond(history)
        assert len(server.prompts) == 2
        first = server.prompts[0]["messages"]
        assert isinstance(first, list) and len(first) == 4
        assert "failed" not in json.dumps(first) and "orphan" not in json.dumps(first)
        assert len(history) == 5
        assert len(server.prompts[-1]["messages"]) == 2  # type: ignore[arg-type]
    finally:
        await client.close()


async def test_oversized_latest_prompt_is_rejected_without_generation() -> None:
    server = Server()
    server.tokens = 4096
    client = server.client()
    try:
        with pytest.raises(ContextLimitExceeded):
            await client.respond(QUESTION)
        assert all(r.url.path != "/v1/chat/completions" for r in server.calls)
    finally:
        await client.close()


@pytest.mark.parametrize("failure", ["offline", "unavailable", "redirect"])
async def test_server_failure_and_redirect_are_safe(failure: str) -> None:
    server = Server()
    server.failure = failure
    client = server.client()
    try:
        assert not await client.available()
        with pytest.raises(RuntimeError, match="Local language model unavailable") as caught:
            await client.respond(QUESTION)
        assert "private" not in str(caught.value)
        assert len(server.calls) == 2  # Redirect never followed.
    finally:
        await client.close()


@pytest.mark.parametrize(
    "data",
    [
        wire(event("partial")),
        wire(event("partial", finish="length"), "[DONE]"),
        wire(event(finish="stop"), "[DONE]"),
        wire(event("answer"), "[DONE]"),
        wire(event("answer"), event(finish="tool_calls"), "[DONE]"),
        wire(event(reasoning_content="private reasoning")),
        wire(event(tool_calls=[{"id": "bad"}])),
        wire(event("<think>private</think>")),
        wire("{broken"),
        wire(event("x" * 8193)),
        wire(event("unsafe\x00")),
        wire(event("answer", role="user")),
        wire(json.dumps({"error": "failure", "choices": []})),
    ],
)
async def test_malformed_incomplete_or_control_output_is_rejected(data: bytes) -> None:
    server = Server(Stream(data))
    client = server.client()
    try:
        with pytest.raises(InvalidModelResponse):
            await client.respond(QUESTION)
        assert server.stream.closed
    finally:
        await client.close()


@pytest.mark.parametrize(
    "marker", ["<think>", "</think>", "<|im_start|>", "<tool_call>", "[TOOL_CALLS]"]
)
def test_split_markers_are_never_emitted(marker: str) -> None:
    for split in range(1, len(marker)):
        parser = AnswerParser()
        emitted = ""
        with pytest.raises(InvalidModelResponse):
            emitted += parser.feed(event(marker[:split]))
            emitted += parser.feed(event(marker[split:] + "private"))
        assert not emitted


async def test_cancellation_closes_stream_and_allows_retry() -> None:
    server = Server(Stream(wire(event("partial")), blocked=True))
    client = server.client()
    task = asyncio.create_task(client.respond(QUESTION))
    try:
        await asyncio.wait_for(server.stream.entered.wait(), 1)
        with pytest.raises(RuntimeError, match="already active"):
            await client.respond(QUESTION)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert server.stream.closed
        server.stream = Stream(wire(event("retry", finish="stop"), "[DONE]"))
        assert await client.respond(QUESTION) == "retry"
    finally:
        task.cancel()
        await client.close()


async def test_total_deadline_closes_stalled_stream() -> None:
    server = Server(Stream(b"", blocked=True))
    client = server.client(timeout=0.01)
    try:
        with pytest.raises(TimeoutError):
            await client.respond(QUESTION)
        assert server.stream.closed
    finally:
        await client.close()


@pytest.mark.parametrize("data", [b"data: " + b"x" * 32769, b"data: \xff\n\n", b"data: unfinished"])
async def test_sse_bounds_and_utf8(data: bytes) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        yield data

    with pytest.raises(InvalidModelResponse):
        async for _ in sse_data(chunks()):
            pass


@pytest.mark.parametrize("payload", [{}, {"prompt": None}, {"prompt": ""}])
async def test_invalid_template_response(payload: dict[str, object]) -> None:
    client = LlamaClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    try:
        with pytest.raises(InvalidModelResponse):
            await client.respond(QUESTION)
    finally:
        await client.close()


@pytest.mark.parametrize("tokens", [None, [], [True], [-1], ["1"]])
async def test_invalid_tokenizer_response(tokens: object) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = (
            {"prompt": "template"} if request.url.path == "/apply-template" else {"tokens": tokens}
        )
        return httpx.Response(200, json=payload)

    client = LlamaClient(transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(InvalidModelResponse):
            await client.respond(QUESTION)
    finally:
        await client.close()


async def test_valid_sse_comments_multiline_json_and_usage() -> None:
    content = (
        ': heartbeat\n\ndata: {"choices":\n'
        'data: [{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
    )
    stream = Stream(content.encode() + wire('{"choices":[],"usage":{"total_tokens":2}}', "[DONE]"))
    client = Server(stream).client()
    try:
        assert await client.respond(QUESTION) == "ok"
    finally:
        await client.close()


async def test_large_multibyte_history_is_bounded_before_template_request() -> None:
    server = Server()
    client = server.client()
    history = (
        tuple(
            Message(role=role, content="語" * 8192)
            for role in ("user", "assistant", "user", "assistant")
        )
        + QUESTION
    )
    try:
        await client.respond(history)
        messages = server.prompts[0]["messages"]
        assert isinstance(messages, list) and len(messages) == 4
        assert len(server.calls[0].content) < 66000
    finally:
        await client.close()


async def test_exact_context_boundary_reserves_output_and_margin() -> None:
    server = Server()
    server.tokens = 4096 - 384 - 32
    client = server.client()
    try:
        assert await client.respond(QUESTION)
        server.tokens += 1
        with pytest.raises(ContextLimitExceeded):
            await client.respond(QUESTION)
    finally:
        await client.close()
