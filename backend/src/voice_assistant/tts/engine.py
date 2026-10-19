"""CPU Piper engine; local assets only, no synthesis files or downloads."""

import json

from voice_assistant.contracts import AudioBuffer
from voice_assistant.tts.models import MAX_SECONDS, PiperSettings, SynthesisRequest


class PiperEngine:
    def __init__(self, settings: PiperSettings) -> None:
        model = settings.model_path
        config = model.with_suffix(model.suffix + ".json")
        if not model.is_file() or not config.is_file():
            raise ValueError("Local Piper voice files are missing")
        data = json.loads(config.read_text())
        # This milestone uses the verified English eSpeak voice. Other phonemizers
        # may download resources; do not silently load them from a changed config.
        if data.get("phoneme_type") != "espeak" or data.get("espeak", {}).get("voice") not in {
            "en",
            "en-us",
        }:
            raise ValueError("Expected the local English eSpeak voice")
        import onnxruntime as ort  # type: ignore[import-untyped]
        from piper.config import PiperConfig
        from piper.voice import PiperVoice

        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.log_severity_level = 4
        self.voice = PiperVoice(
            config=PiperConfig.from_dict(data),
            session=ort.InferenceSession(
                str(model), sess_options=options, providers=["CPUExecutionProvider"]
            ),
            use_tashkeel=False,
        )

    def synthesize(self, text: str) -> AudioBuffer:
        text = SynthesisRequest(text=text).text
        pcm = bytearray()
        rate = self.voice.config.sample_rate
        if not 8000 <= rate <= 48000:
            raise ValueError("Unsupported voice rate")
        for chunk in self.voice.synthesize(text):
            if chunk.sample_channels != 1 or chunk.sample_width != 2 or chunk.sample_rate != rate:
                raise ValueError("Invalid voice output format")
            data = chunk.audio_int16_bytes
            if len(data) % 2 or len(pcm) + len(data) > rate * MAX_SECONDS * 2:
                raise ValueError("Speech exceeds output limit")
            pcm.extend(data)
        return AudioBuffer(pcm=bytes(pcm), sample_rate=rate)
