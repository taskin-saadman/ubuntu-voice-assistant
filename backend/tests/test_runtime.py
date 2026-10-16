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
