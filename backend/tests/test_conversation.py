import asyncio
from collections.abc import Callable

import pytest
from voice_assistant.contracts import ContextLimitExceeded, InvalidModelResponse, Message
from voice_assistant.controller import Controller, ConversationComponents, Deadlines
from voice_assistant.events import ErrorCode
from voice_assistant.state import AssistantState
from voice_assistant.transport import DesktopTransport

from .fakes import FakeEngines
from .test_transport import TOKEN, FakeRuntime


class StreamingFake(FakeEngines):
    def __init__(self) -> None:
        super().__init__()
        self.delta: Callable[[str], None] | None = None
        self.failure: Exception | None = None

    async def respond(
        self,
        messages: tuple[Message, ...],
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        self.delta = on_delta
        self.prompt = messages
        assert on_delta is not None
        on_delta("Partial answer")
        await self.step("llm")
        if self.failure:
            raise self.failure
        return self.answer


def controller_for(fake: StreamingFake, deadlines: Deadlines | None = None) -> Controller:
    return Controller(
        ConversationComponents(
            capture=fake, vad=fake, stt=fake, history=fake.components().history, llm=fake
        ),
        deadlines,
    )


async def start(controller: Controller) -> None:
    await controller.set_microphone(True)
    controller.release(controller.begin_turn())


async def test_conversation_streams_draft_and_commits_only_completed_answer() -> None:
    fake = StreamingFake()
    fake.gates["llm"] = asyncio.Event()
    controller = controller_for(fake)
    try:
        await start(controller)
        await fake.reached("llm")
        assert controller.state == AssistantState.THINKING and controller.draft == "Partial answer"
        assert len(controller.components.history.messages()) == 1
        runtime = FakeRuntime()
        runtime.controller = controller
        snapshot = DesktopTransport(runtime, TOKEN).snapshot()
        assert snapshot.draft == "Partial answer" and snapshot.state == AssistantState.THINKING
        fake.gates["llm"].set()
        await controller.wait()
        assert controller.draft == "" and controller.state.value == "idle"
        assert [m.role for m in controller.components.history.messages()] == ["user", "assistant"]
        assert not {"tts", "play", "stop"}.intersection(fake.calls)
        assert [e.state.value for e in controller.events.read() if e.state] == [
            "listening",
            "transcribing",
            "thinking",
            "idle",
        ]
    finally:
        await controller.close()


async def test_cancel_clears_draft_and_rejects_late_updates_during_next_turn() -> None:
    fake = StreamingFake()
    fake.gates["llm"] = asyncio.Event()
    controller = controller_for(fake)
    try:
        await start(controller)
        await fake.reached("llm")
        old_delta = fake.delta
        assert old_delta is not None
        await controller.set_microphone(False)
        assert controller.draft == "" and len(controller.components.history.messages()) == 1
        fake.entered["llm"].clear()
        await start(controller)
        await fake.reached("llm")
        old_delta("stale answer")
        assert controller.draft == "Partial answer"
        fake.gates["llm"].set()
        await controller.wait()
        assert len(controller.components.history.messages()) == 3
    finally:
        await controller.close()


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        (RuntimeError("private native error"), ErrorCode.LLM_UNAVAILABLE),
        (InvalidModelResponse(), ErrorCode.INVALID_RESPONSE),
        (ContextLimitExceeded(), ErrorCode.CONTEXT_TOO_LONG),
    ],
)
async def test_failed_generation_keeps_transcript_and_discards_draft(
    failure: Exception,
    code: ErrorCode,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = StreamingFake()
    fake.failure = failure
    controller = controller_for(fake)
    try:
        await start(controller)
        await controller.wait()
        assert controller.state == AssistantState.ERROR and controller.draft == ""
        assert [m.role for m in controller.components.history.messages()] == ["user"]
        assert any(e.failure and e.failure.code == code for e in controller.events.read())
        assert "private" not in caplog.text
        controller.reset()
        fake.failure = None
        await start(controller)
        await controller.wait()
        assert controller.state.value == "idle"
    finally:
        await controller.close()


async def test_generation_deadline_discards_draft() -> None:
    fake = StreamingFake()
    fake.gates["llm"] = asyncio.Event()
    controller = controller_for(fake, Deadlines(generation=0.01))
    try:
        await start(controller)
        await controller.wait()
        assert controller.draft == "" and not controller.busy
        assert any(
            e.failure and e.failure.code == ErrorCode.DEADLINE_EXCEEDED
            for e in controller.events.read()
        )
    finally:
        await controller.close()


async def test_silence_never_calls_qwen() -> None:
    fake = StreamingFake()
    fake.speech = False
    controller = controller_for(fake)
    try:
        await start(controller)
        await controller.wait()
        assert "llm" not in fake.calls
        assert controller.components.history.messages() == ()
    finally:
        await controller.close()
