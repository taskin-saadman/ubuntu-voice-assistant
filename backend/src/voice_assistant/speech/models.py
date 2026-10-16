"""Bounded configuration and private speech worker protocol."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from voice_assistant.audio.models import MAX_PCM_BYTES
from voice_assistant.contracts import Schema


class SpeechSettings(Schema):
    model_path: Path = Field(
        default_factory=lambda: (
            Path.home() / ".local/share/ubuntu-voice-assistant/models/whisper-small.en"
        ),
        repr=False,
    )
    cpu_threads: int = Field(default=8, ge=1, le=16, strict=True)
    timeout: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)

    @field_validator("model_path")
    @classmethod
    def local_directory(cls, path: Path) -> Path:
        path = path.expanduser()
        if not path.is_absolute():
            raise ValueError("Use an absolute path to the downloaded small.en model")
        return path


class SpeechRequest(Schema):
    action: Literal["initialize", "warmup", "vad", "transcribe"]
    size: int = Field(default=0, ge=0, le=MAX_PCM_BYTES)
    settings: SpeechSettings | None = None

    @model_validator(mode="after")
    def check_payload(self) -> "SpeechRequest":
        if self.action in {"vad", "transcribe"}:
            if self.size < 2 or self.size % 2:
                raise ValueError("Expected whole PCM frames")
        elif self.size:
            raise ValueError("Control requests cannot carry PCM")
        if (self.action == "initialize") != (self.settings is not None):
            raise ValueError("Only initialization carries settings")
        return self


class SpeechReply(Schema):
    status: Literal["ready", "vad", "transcript", "error"]
    speech: bool | None = Field(default=None, strict=True)
    text: str | None = Field(default=None, max_length=8192, repr=False)
    error: Literal["model_missing", "failed", "invalid_audio", "invalid_result"] | None = None

    @model_validator(mode="after")
    def check_payload(self) -> "SpeechReply":
        if (self.status == "vad") != (self.speech is not None):
            raise ValueError("VAD replies require a speech decision")
        if (self.status == "transcript") != (self.text is not None):
            raise ValueError("Transcript replies require text")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("Error replies require an error code")
        return self


class SpeechError(RuntimeError):
    """Safe errors without raw diagnostics, paths or transcripts."""


ERROR_MESSAGES = {
    "model_missing": "Local small.en files are missing. Check the configured model directory.",
    "failed": "Speech recognition failed. Check the local model and try again.",
    "invalid_audio": "Speech recognition requires at most 30 seconds of mono 16 kHz PCM.",
    "invalid_result": "Speech recognition returned an invalid result. Try a shorter recording.",
}
