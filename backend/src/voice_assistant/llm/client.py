"""Persistent async HTTP client for one local Qwen server, with no proxy or redirects."""

import asyncio
import json
from collections.abc import Callable

import httpx

from voice_assistant.contracts import ContextLimitExceeded, InvalidModelResponse, Message
from voice_assistant.llm.models import LlamaSettings
from voice_assistant.llm.stream import MAX_BODY, AnswerParser, sse_data

SYSTEM_PROMPT = (
    "You are a private voice assistant running locally on the user's laptop. "
    "Answer briefly in plain text, usually one to three sentences. "
    "You have no tools and cannot perform actions or access live external information. "
    "Do not claim to have performed actions. Return only the answer, without reasoning "
    "or control markup."
)


class LlamaClient:
    def __init__(
        self,
        settings: LlamaSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or LlamaSettings()
        self._client = httpx.AsyncClient(
            base_url=self.settings.base_url,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(15, connect=2, pool=2),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            transport=transport,
        )
        self._busy = False

    async def close(self) -> None:
        await self._client.aclose()

    async def _json(self, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        async with self._client.stream(
            "GET" if payload is None else "POST", path, json=payload
        ) as r:
            r.raise_for_status()
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    raise InvalidModelResponse()
        try:
            result: object = json.loads(body)
        except ValueError:
            raise InvalidModelResponse() from None
        if not isinstance(result, dict):
            raise InvalidModelResponse()
        return result

    async def available(self) -> bool:
        try:
            async with asyncio.timeout(2):
                return (await self._json("/health")).get("status") == "ok"
        except (httpx.HTTPError, TimeoutError, InvalidModelResponse):
            return False

    def _body(self, messages: list[dict[str, str]]) -> dict[str, object]:
        return {
            "model": self.settings.model,
            "messages": messages,
            "max_tokens": self.settings.max_tokens,
            "temperature": 0.7,
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning_format": "deepseek",
            "stream": True,
        }

    async def _fit(self, messages: tuple[Message, ...]) -> dict[str, object]:
        if not messages or messages[-1].role != "user" or len(messages) > 20:
            raise ContextLimitExceeded()
        # Keep complete prior pairs only: failed/cancelled user-only turns aren't context.
        pairs: list[list[dict[str, str]]] = []
        for previous, answer in zip(messages[:-2], messages[1:-1], strict=False):
            if previous.role == "user" and answer.role == "assistant":
                pairs.append([previous.model_dump(), answer.model_dump()])
        while True:
            prompt = [{"role": "system", "content": SYSTEM_PROMPT}]
            prompt.extend(m for pair in pairs for m in pair)
            prompt.append(messages[-1].model_dump())
            # Bound template/tokenizer traffic before exact counting, even for long
            # multibyte transcripts. Only prior pairs may be discarded.
            if pairs and sum(len(m["content"].encode("utf-8")) for m in prompt) > 65536:
                pairs.pop(0)
                continue
            body = self._body(prompt)
            template = await self._json("/apply-template", body)
            formatted = template.get("prompt")
            if not isinstance(formatted, str) or not formatted:
                raise InvalidModelResponse()
            tokenized = await self._json(
                "/tokenize",
                {
                    "content": formatted,
                    "add_special": True,
                    "parse_special": True,
                },
            )
            tokens = tokenized.get("tokens")
            if (
                not isinstance(tokens, list)
                or not tokens
                or not all(type(t) is int and t >= 0 for t in tokens)
            ):
                raise InvalidModelResponse()
            # Reserve output plus a small margin for server-side template/BOS variation.
            if len(tokens) + self.settings.max_tokens + 32 <= self.settings.context_size:
                return body
            if not pairs:
                raise ContextLimitExceeded()
            pairs.pop(0)

    async def respond(
        self,
        messages: tuple[Message, ...],
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        if self._busy:
            raise RuntimeError("Language model request already active")
        self._busy = True
        try:
            async with asyncio.timeout(self.settings.timeout):
                body = await self._fit(messages)
                parser = AnswerParser()
                async with self._client.stream("POST", "/v1/chat/completions", json=body) as r:
                    r.raise_for_status()
                    if r.headers.get("content-type", "").split(";", 1)[0] != "text/event-stream":
                        raise InvalidModelResponse()
                    async for data in sse_data(r.aiter_bytes()):
                        delta = parser.feed(data)
                        if delta and on_delta:
                            on_delta(delta)
                        if parser.done:
                            break
                    return parser.result()
        except httpx.HTTPError:
            # Don't expose native HTTP exceptions, bodies, prompts or proxy credentials.
            raise RuntimeError("Local language model unavailable") from None
        finally:
            self._busy = False
