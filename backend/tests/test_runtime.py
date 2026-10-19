import pytest
from voice_assistant import runtime as runtime_module
from voice_assistant.audio.models import InputDevice
from voice_assistant.controller import ControllerRejected
from voice_assistant.runtime import TranscriptionRuntime


async def test_runtime_requires_loaded_model_and_listed_inactive_device() -> None:
    runtime = TranscriptionRuntime()
    try:
        with pytest.raises(ControllerRejected, match="Load"):
            await runtime.microphone(True)
        with pytest.raises(ControllerRejected, match="listed"):
            runtime.select_device(3)
        runtime.devices = (InputDevice(index=3, name="Synthetic input", sample_rate=48000),)
        runtime.select_device(3)
        assert runtime.device == 3
        await runtime.controller.set_microphone(True)
        with pytest.raises(ControllerRejected, match="Disable"):
            runtime.select_device(None)
        with pytest.raises(ControllerRejected, match="Disable"):
            await runtime.prepare()
        await runtime.microphone(False)
        runtime.select_device(None)
        assert runtime.device is None
    finally:
        await runtime.close()


async def test_prepare_warms_model_and_lists_devices_without_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = TranscriptionRuntime()
    calls: list[str] = []

    async def warmup() -> None:
        calls.append("warmup")

    async def devices() -> tuple[InputDevice, ...]:
        calls.append("devices")
        return (InputDevice(index=3, name="Synthetic input", sample_rate=48000),)

    monkeypatch.setattr(runtime.speech, "warmup", warmup)
    monkeypatch.setattr(runtime_module, "input_devices", devices)
    try:
        await runtime.prepare()
        assert calls == ["warmup", "devices"]
        assert runtime.devices[0].index == 3
        assert not runtime.controller.microphone_enabled
        assert not runtime.controller.busy
    finally:
        await runtime.close()


async def test_conversation_runtime_wires_qwen_and_closes_client() -> None:
    from voice_assistant.controller import ConversationComponents
    from voice_assistant.runtime import ConversationRuntime

    runtime = ConversationRuntime()
    assert isinstance(runtime.controller.components, ConversationComponents)
    assert runtime.controller.components.llm is runtime.llm
    assert not runtime.controller.microphone_enabled and not runtime.ready
    await runtime.close()
    assert runtime.llm._client.is_closed


async def test_voice_runtime_wires_speech_output_and_restricts_device_changes() -> None:
    from voice_assistant.audio.output_models import OutputDevice
    from voice_assistant.controller import Components
    from voice_assistant.runtime import VoiceRuntime

    runtime = VoiceRuntime()
    try:
        assert isinstance(runtime.controller.components, Components)
        assert runtime.controller.components.tts is runtime.tts
        assert runtime.controller.components.playback is runtime.playback
        assert not runtime.ready and not runtime.controller.microphone_enabled
        with pytest.raises(ControllerRejected, match="listed"):
            runtime.select_output(4)
        runtime.outputs = (OutputDevice(index=4, name="Synthetic output", sample_rate=48000),)
        runtime.select_output(4)
        assert runtime.output_device == 4
        await runtime.controller.set_microphone(True)
        with pytest.raises(ControllerRejected, match="Disable"):
            runtime.select_output(None)
        await runtime.controller.set_microphone(False)
        runtime.select_output(None)
        assert runtime.output_device is None
    finally:
        await runtime.close()
    assert runtime.tts._closed and runtime.llm._client.is_closed


async def test_voice_prepare_lists_outputs_without_synthesis_or_playback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from voice_assistant.audio.output_models import OutputDevice
    from voice_assistant.runtime import VoiceRuntime

    runtime = VoiceRuntime()

    async def prepare() -> None:
        pass

    async def outputs() -> tuple[OutputDevice, ...]:
        return (OutputDevice(index=4, name="Synthetic output", sample_rate=48000),)

    monkeypatch.setattr(runtime.speech, "warmup", prepare)
    monkeypatch.setattr(runtime_module, "output_devices", outputs)

    async def inputs() -> tuple[InputDevice, ...]:
        return ()

    monkeypatch.setattr(runtime_module, "input_devices", inputs)
    try:
        await runtime.prepare()
        assert runtime.outputs[0].index == 4
        assert runtime.tts.worker._spawn is None and runtime.playback.worker._spawn is None
    finally:
        await runtime.close()
