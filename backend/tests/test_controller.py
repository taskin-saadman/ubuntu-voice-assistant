import asyncio
from uuid import uuid4

import pytest
from voice_assistant.contracts import Message
from voice_assistant.controller import Controller, ControllerRejected, Deadlines
from voice_assistant.events import ErrorCode
from voice_assistant.state import AssistantState as State

from .fakes import FakeEngines


async def run_turn(controller: Controller) -> None:
    await controller.set_microphone(True)
    turn = controller.begin_turn()
    controller.release(turn)
    await controller.wait()


async def test_complete_turn_has_ordered_states_and_messages() -> None:
    fake = FakeEngines()
    controller = Controller(fake.components())
    await run_turn(controller)
    events = controller.events.read()
    assert [e.state for e in events if e.kind == "state"] == [
        State.LISTENING,
        State.TRANSCRIBING,
        State.THINKING,
        State.SPEAKING,
        State.IDLE,
    ]
    assert [e.message.content for e in events if e.message] == [fake.text, fake.answer]
    assert fake.prompt[-1].content == fake.text
    assert events[-1].outcome == "completed"
    assert not controller.busy
    assert not fake.capturing and not fake.playing
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))


async def test_microphone_off_and_overlapping_turns_are_rejected() -> None:
    fake = FakeEngines()
    controller = Controller(fake.components())
    with pytest.raises(ControllerRejected, match="Microphone is off"):
        controller.begin_turn()
    assert fake.calls == []
    await controller.set_microphone(True)
    controller.begin_turn()
    with pytest.raises(ControllerRejected):
        controller.begin_turn()
    await fake.reached("start")
    await controller.set_microphone(False)
    assert not controller.microphone_enabled
    assert not fake.capturing
    assert controller.state == State.IDLE


@pytest.mark.parametrize(
    "stage", ["start", "finish", "vad", "stt", "llm", "tts", "play_start", "play"]
)
async def test_cancel_at_every_stage(stage: str) -> None:
    fake = FakeEngines()
    fake.gates[stage] = asyncio.Event()
    controller = Controller(fake.components())
    await controller.set_microphone(True)
    turn = controller.begin_turn()
    controller.release(turn)
    await fake.reached(stage)
    await controller.cancel(turn)
    assert controller.state == State.IDLE
    assert controller.events.read()[-1].outcome == "cancelled"
    assert not fake.capturing and not fake.playing
    assert not controller.busy


async def test_stale_and_duplicate_controls_do_not_release_new_recording() -> None:
    fake = FakeEngines()
    controller = Controller(fake.components())
    await controller.set_microphone(True)
    turn = controller.begin_turn()
    await fake.reached("start")
    controller.release(uuid4())
    await controller.cancel(uuid4())
    assert "finish" not in fake.calls
    controller.release(turn)
    controller.release(turn)
    await controller.wait()
    assert fake.calls.count("finish") == 1
    await controller.cancel(turn)
    assert controller.events.read()[-1].outcome == "completed"


@pytest.mark.parametrize("silence", [True, False])
async def test_silence_or_empty_transcript_never_calls_llm(silence: bool) -> None:
    fake = FakeEngines()
    fake.speech = not silence
    fake.text = " "
    controller = Controller(fake.components())
    await run_turn(controller)
    assert controller.events.read()[-1].outcome == "no_speech"
    assert "llm" not in fake.calls and "tts" not in fake.calls
    assert controller.components.history.messages() == ()


@pytest.mark.parametrize(
    "stage,code",
    [
        ("start", ErrorCode.CAPTURE_FAILED),
        ("stt", ErrorCode.STT_UNAVAILABLE),
        ("llm", ErrorCode.LLM_UNAVAILABLE),
        ("tts", ErrorCode.TTS_UNAVAILABLE),
        ("play", ErrorCode.PLAYBACK_FAILED),
    ],
)
async def test_failures_are_safe_and_recoverable(
    stage: str,
    code: ErrorCode,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeEngines()
    fake.fail_at = stage
    controller = Controller(fake.components())
    await run_turn(controller)
    assert controller.state == State.ERROR
    failures = [e.failure for e in controller.events.read() if e.failure]
    assert failures[-1].code == code
    assert "sensitive" not in caplog.text
    assert fake.text not in caplog.text and fake.answer not in caplog.text
    if stage == "tts":
        assert controller.components.history.messages()[-1].content == fake.answer
    controller.reset()
    fake.fail_at = None
    await run_turn(controller)
    assert controller.events.read()[-1].outcome == "completed"


async def test_recording_deadline_handles_lost_release() -> None:
    fake = FakeEngines()
    controller = Controller(fake.components(), Deadlines(recording=0.01))
    await controller.set_microphone(True)
    controller.begin_turn()
    await controller.wait()
    assert not fake.capturing
    assert controller.state == State.ERROR
    assert any(
        e.failure and e.failure.code == ErrorCode.DEADLINE_EXCEEDED
        for e in controller.events.read()
    )
    assert "stt" not in fake.calls


async def test_speaking_begins_on_playback_callback_not_synthesis() -> None:
    fake = FakeEngines()
    fake.gates["play_start"] = asyncio.Event()
    controller = Controller(fake.components())
    task = asyncio.create_task(run_turn(controller))
    await fake.reached("play_start")
    assert controller.state.value == "thinking"
    fake.gates["play_start"].set()
    await task
    assert fake.callback is not None
    fake.callback()  # An old adapter callback must not change an idle controller.
    assert controller.state == State.IDLE


async def test_cleanup_failure_requires_restart() -> None:
    fake = FakeEngines()
    fake.fail_at = "abort"
    controller = Controller(fake.components())
    await run_turn(controller)
    assert controller.state == State.ERROR
    assert "stop" in fake.calls
    with pytest.raises(ControllerRejected):
        controller.reset()


async def test_shutdown_is_idempotent_and_prevents_new_turns() -> None:
    fake = FakeEngines()
    controller = Controller(fake.components())
    await controller.set_microphone(True)
    controller.begin_turn()
    await controller.close()
    await controller.close()
    assert not fake.capturing and not controller.microphone_enabled
    with pytest.raises(ControllerRejected):
        controller.begin_turn()


@pytest.mark.parametrize("answer", ["", " ", "<think>private</think>answer", "x" * 8193])
async def test_invalid_answers_are_not_spoken(answer: str) -> None:
    fake = FakeEngines()
    fake.answer = answer
    controller = Controller(fake.components())
    await run_turn(controller)
    assert "tts" not in fake.calls
    assert any(
        e.failure and e.failure.code == ErrorCode.INVALID_RESPONSE for e in controller.events.read()
    )


async def test_late_response_after_timeout_is_ignored_and_quarantined() -> None:
    class StubbornModel(FakeEngines):
        async def respond(self, messages: tuple[Message, ...]) -> str:
            await self.step("llm")
            while not gate.is_set():
                try:
                    await gate.wait()
                except asyncio.CancelledError:
                    continue
            return "A stale answer"

    gate = asyncio.Event()
    fake = StubbornModel()
    controller = Controller(fake.components(), Deadlines(generation=0.01))
    try:
        await run_turn(controller)
        assert controller.busy
        with pytest.raises(ControllerRejected):
            controller.reset()
        gate.set()
        # Drain the detached task without sleeping for a real model's duration.
        for _ in range(5):
            await asyncio.sleep(0)
        assert not controller.busy
        assert "tts" not in fake.calls
        assert all(m.content != "A stale answer" for m in controller.components.history.messages())
        controller.reset()
        assert controller.state == State.IDLE
    finally:
        gate.set()


async def test_slow_engine_does_not_block_event_loop_and_times_out() -> None:
    fake = FakeEngines()
    fake.gates["llm"] = asyncio.Event()
    controller = Controller(fake.components(), Deadlines(generation=0.02))
    task = asyncio.create_task(run_turn(controller))
    await fake.reached("llm")
    heartbeat = asyncio.Event()
    asyncio.get_running_loop().call_soon(heartbeat.set)
    async with asyncio.timeout(0.5):
        await heartbeat.wait()
        await task
    assert controller.state == State.ERROR
    assert "tts" not in fake.calls
    assert not controller.busy


async def test_cancelling_a_waiter_does_not_cancel_the_owned_turn() -> None:
    fake = FakeEngines()
    fake.gates["llm"] = asyncio.Event()
    controller = Controller(fake.components())
    await controller.set_microphone(True)
    turn = controller.begin_turn()
    controller.release(turn)
    await fake.reached("llm")
    waiter = asyncio.create_task(controller.wait())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert controller.busy
    await controller.cancel(turn)
    assert not controller.busy


async def test_cleanup_timeout_does_not_leave_controller_waiting_forever() -> None:
    fake = FakeEngines()
    fake.gates["abort"] = asyncio.Event()
    controller = Controller(fake.components(), Deadlines(cleanup=0.01))
    async with asyncio.timeout(1):
        await run_turn(controller)
    assert controller.state == State.ERROR
    assert "stop" in fake.calls
    assert controller.events.read()[-1].failure is None
    assert controller.events.read()[-1].outcome == "failed"
    with pytest.raises(ControllerRejected):
        controller.reset()


async def test_cooperative_device_cancellation_can_finish_during_cleanup() -> None:
    stopped = asyncio.Event()

    class ReapingCapture(FakeEngines):
        async def start(self) -> None:
            await self.step("start")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await stopped.wait()
                raise

        async def abort(self) -> None:
            await self.step("abort")
            stopped.set()
            await asyncio.sleep(0)

    fake = ReapingCapture()
    controller = Controller(fake.components())
    await controller.set_microphone(True)
    turn = controller.begin_turn()
    await fake.reached("start")
    await controller.cancel(turn)
    assert stopped.is_set() and not controller.busy
    controller.reset()
    assert controller.state == State.IDLE
    await controller.close()


async def test_device_operation_outliving_cleanup_requires_restart_even_after_it_finishes() -> None:
    gate = asyncio.Event()

    class BrokenCapture(FakeEngines):
        async def start(self) -> None:
            await self.step("start")
            while not gate.is_set():
                try:
                    await gate.wait()
                except asyncio.CancelledError:
                    continue

    fake = BrokenCapture()
    controller = Controller(fake.components())
    try:
        await controller.set_microphone(True)
        turn = controller.begin_turn()
        await fake.reached("start")
        await controller.cancel(turn)
        assert controller.state == State.ERROR and controller.busy
        gate.set()
        for _ in range(5):
            await asyncio.sleep(0)
        assert not controller.busy
        with pytest.raises(ControllerRejected):
            controller.reset()
    finally:
        gate.set()
        await controller.close()
