"""Own the transcription components used by the authenticated desktop session."""

from voice_assistant.audio.capture import MicrophoneCapture, input_devices
from voice_assistant.audio.models import CaptureSettings, InputDevice
from voice_assistant.controller import Controller, ControllerRejected, TranscriptionComponents
from voice_assistant.speech.adapters import SileroVAD, SpeechWorker, WhisperTranscriber
from voice_assistant.storage import MemoryConversation


class TranscriptionRuntime:
    def __init__(self) -> None:
        self.capture = MicrophoneCapture()
        self.speech = SpeechWorker()
        self.controller = Controller(
            TranscriptionComponents(
                capture=self.capture,
                vad=SileroVAD(self.speech),
                stt=WhisperTranscriber(self.speech),
                history=MemoryConversation(),
            )
        )
        self.devices: tuple[InputDevice, ...] = ()

    @property
    def ready(self) -> bool:
        return self.speech.ready

    @property
    def device(self) -> int | None:
        return self.capture.settings.device

    def _require_inactive(self) -> None:
        if self.controller.busy or self.controller.microphone_enabled:
            raise ControllerRejected("Disable the microphone and wait for the turn to stop first")

    async def prepare(self) -> None:
        self._require_inactive()
        await self.speech.warmup()
        self.devices = await input_devices()

    def select_device(self, device: int | None) -> None:
        self._require_inactive()
        if device is not None and device not in {item.index for item in self.devices}:
            raise ControllerRejected("Choose a listed input device")
        self.capture.settings = CaptureSettings(device=device)

    async def microphone(self, enabled: bool) -> None:
        if enabled and not self.ready:
            raise ControllerRejected("Load the local speech model before enabling the microphone")
        await self.controller.set_microphone(enabled)

    async def close(self) -> None:
        try:
            await self.controller.close()
        finally:
            await self.speech.close()
