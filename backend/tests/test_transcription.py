import asyncio
from unittest.mock import patch

import pytest
from voice_assistant.audio.models import CaptureSettings
from voice_assistant.controller import Controller, TranscriptionComponents
from voice_assistant.speech.adapters import SileroVAD, SpeechWorker, WhisperTranscriber
from voice_assistant.speech.models import SpeechSettings
from voice_assistant.state import AssistantState
from voice_assistant.transcribe import check

from .fakes import FakeEngines
from .test_speech import SpeechFactory


@pytest.mark.parametrize("speech", [True, False])
async def test_transcription_only_turn_has_no_thinking_or_speaking(speech: bool) -> None:
    fake = FakeEngines()
    fake.speech = speech
    controller = Controller(
        TranscriptionComponents(capture=fake, vad=fake, stt=fake, history=fake.components().history)
    )
    await controller.set_microphone(True)
    controller.release(controller.begin_turn())
    await controller.wait()
    events = controller.events.read()
    assert [e.state.value for e in events if e.state] == ["listening", "transcribing", "idle"]
    assert len(controller.components.history.messages()) == int(speech)
    assert events[-1].outcome == ("completed" if speech else "no_speech")
    assert "llm" not in fake.calls and "tts" not in fake.calls and "play" not in fake.calls
    if not speech:
        assert "stt" not in fake.calls
    await controller.close()


async def test_controller_cancellation_waits_for_native_speech_cleanup() -> None:
    factory = SpeechFactory("hang")
    worker = SpeechWorker()
    fake = FakeEngines()
    controller = Controller(
        TranscriptionComponents(
            capture=fake,
            vad=SileroVAD(worker),
            stt=WhisperTranscriber(worker),
            history=fake.components().history,
        )
    )
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        try:
            await worker.warmup()
            await controller.set_microphone(True)
            controller.release(controller.begin_turn())
            await fake.reached("finish")
            await asyncio.sleep(0.05)
            await controller.set_microphone(False)
            assert not controller.busy
            assert controller.state == AssistantState.IDLE
            assert controller.events.read()[-1].outcome == "cancelled"
            factory.assert_reaped()
        finally:
            await controller.close()
            await worker.close()


@pytest.mark.parametrize("mode", ["normal", "silence"])
async def test_diagnostic_wires_capture_to_worker_and_closes_everything(
    mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    factory = SpeechFactory(mode)
    fake = FakeEngines()
    with (
        patch("voice_assistant.speech.adapters._launch", factory.launch),
        patch("voice_assistant.transcribe.MicrophoneCapture", return_value=fake),
    ):
        assert await check(CaptureSettings(), SpeechSettings(), seconds=0.1) == 0
    output = capsys.readouterr().out
    assert "State: listening" in output and "State: transcribing" in output
    assert "Microphone disabled; speech worker stopped." in output
    if mode == "normal":
        assert "Transcript: Synthetic speech" in output and "Result: completed" in output
    else:
        assert "Transcript:" not in output and "Result: no_speech" in output
    assert not fake.capturing
    factory.assert_reaped()


async def test_diagnostic_cancellation_during_capture_releases_devices() -> None:
    factory = SpeechFactory()
    fake = FakeEngines()
    with (
        patch("voice_assistant.speech.adapters._launch", factory.launch),
        patch("voice_assistant.transcribe.MicrophoneCapture", return_value=fake),
    ):
        task = asyncio.create_task(check(CaptureSettings(), SpeechSettings(), seconds=5))
        await fake.reached("start")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not fake.capturing
    factory.assert_reaped()
