"""Synchronous native inference, used only inside the private speech worker."""

import numpy as np
from numpy.typing import NDArray

from voice_assistant.speech.models import SpeechSettings


class ModelMissing(Exception):
    pass


def validate_model(settings: SpeechSettings) -> None:
    path = settings.model_path
    # WhisperModel otherwise falls back to a pretrained tokenizer lookup.
    required = ("model.bin", "config.json", "tokenizer.json")
    if not path.is_dir() or any(not (path / name).is_file() for name in required):
        raise ModelMissing
    if not any((path / name).is_file() for name in ("vocabulary.txt", "vocabulary.json")):
        raise ModelMissing


def samples(pcm: bytes) -> NDArray[np.float32]:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(32768)


def speech_present(audio: NDArray[np.float32]) -> bool:
    import onnxruntime as ort  # type: ignore[import-untyped]
    from faster_whisper.vad import VadOptions, get_speech_timestamps  # type: ignore[import-untyped]

    ort.disable_telemetry_events()
    # Short clicks are not speech. Model and options are bundled with faster-whisper.
    return bool(
        get_speech_timestamps(
            audio,
            vad_options=VadOptions(min_speech_duration_ms=100, min_silence_duration_ms=500),
            sampling_rate=16000,
        )
    )


class SpeechEngine:
    def __init__(self, settings: SpeechSettings) -> None:
        validate_model(settings)
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]

        self._model = WhisperModel(
            str(settings.model_path),
            device="cpu",
            compute_type="int8",
            cpu_threads=settings.cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
        # Warm the bundled VAD while capture is still closed.
        speech_present(np.zeros(1600, dtype=np.float32))

    def has_speech(self, pcm: bytes) -> bool:
        return speech_present(samples(pcm))

    def transcribe(self, pcm: bytes) -> str:
        audio = samples(pcm)
        # Guard standalone transcription too; no speech must skip the decoder.
        if not speech_present(audio):
            return ""
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_speech_duration_ms": 100, "min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        parts: list[str] = []
        length = 0
        for segment in segments:  # Inference is lazy; consume entirely inside the worker.
            text = segment.text.strip()
            length += len(text) + bool(parts)
            if length > 8192:
                raise ValueError("Transcript exceeds its bound")
            if text:
                parts.append(text)
        return " ".join(parts)
