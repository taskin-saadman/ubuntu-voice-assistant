"""Own local engines and controller lifetimes for desktop sessions."""

from voice_assistant.audio.capture import MicrophoneCapture, input_devices
from voice_assistant.audio.models import CaptureSettings, InputDevice
from voice_assistant.audio.output_models import OutputDevice, PlaybackSettings
from voice_assistant.audio.playback import AudioPlayback, output_devices
from voice_assistant.contracts import LanguageModel
from voice_assistant.controller import (
    Components,
    Controller,
    ControllerRejected,
    ConversationComponents,
    TranscriptionComponents,
)
from voice_assistant.llm.client import LlamaClient
from voice_assistant.speech.adapters import SileroVAD, SpeechWorker, WhisperTranscriber
from voice_assistant.storage import MemoryConversation
from voice_assistant.tts.piper import PiperSynthesizer


class TranscriptionRuntime:
    def __init__(self, llm: LanguageModel | None = None) -> None:
        self.capture = MicrophoneCapture()
        self.speech = SpeechWorker()
        components = TranscriptionComponents(
            capture=self.capture,
            vad=SileroVAD(self.speech),
            stt=WhisperTranscriber(self.speech),
            history=MemoryConversation(),
        )
        if llm is not None:
            components = ConversationComponents(
                capture=components.capture,
                vad=components.vad,
                stt=components.stt,
                history=components.history,
                llm=llm,
            )
        self.controller = Controller(components)
        self.devices: tuple[InputDevice, ...] = ()
        self.outputs: tuple[OutputDevice, ...] = ()

    @property
    def ready(self) -> bool:
        return self.speech.ready

    @property
    def device(self) -> int | None:
        return self.capture.settings.device

    @property
    def output_device(self) -> int | None:
        return None

    def select_output(self, device: int | None) -> None:
        raise ControllerRejected("Playback is not enabled in this runtime")

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


class ConversationRuntime(TranscriptionRuntime):
    def __init__(self) -> None:
        self.llm = LlamaClient()
        super().__init__(llm=self.llm)

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            await self.llm.close()


class VoiceRuntime(ConversationRuntime):
    """Full turn with lazy CPU synthesis and selected-device playback."""

    def __init__(self) -> None:
        super().__init__()
        self.tts = PiperSynthesizer()
        self.playback = AudioPlayback()
        c = self.controller.components
        self.controller = Controller(
            Components(
                capture=c.capture,
                vad=c.vad,
                stt=c.stt,
                history=c.history,
                llm=self.llm,
                tts=self.tts,
                playback=self.playback,
            )
        )

    @property
    def output_device(self) -> int | None:
        return self.playback.settings.device

    async def prepare(self) -> None:
        await super().prepare()
        self.outputs = await output_devices()

    def select_output(self, device: int | None) -> None:
        self._require_inactive()
        if device is not None and device not in {item.index for item in self.outputs}:
            raise ControllerRejected("Choose a listed output device")
        self.playback.settings = PlaybackSettings(device=device)

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            try:
                await self.tts.close()
            finally:
                await self.playback.stop()
