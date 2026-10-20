"""Bounded settings and IPC for complete-answer synthesis."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from voice_assistant.contracts import Schema

MAX_SECONDS = 90


class PiperSettings(Schema):
    model_path: Path = Field(
        default_factory=lambda: (
            Path.home()
            / ".local/share/ubuntu-voice-assistant/models/piper/en_US-ljspeech-medium.onnx"
        ),
        repr=False,
    )
    timeout: float = Field(default=25, gt=0, le=30, allow_inf_nan=False)

    @field_validator("model_path")
    @classmethod
    def local_path(cls, path: Path) -> Path:
        path = path.expanduser()
        if not path.is_absolute():
            raise ValueError("Use an absolute path to the downloaded Piper voice")
        return path


class SynthesisRequest(Schema):
    text: str = Field(min_length=1, max_length=8192, repr=False)

    @field_validator("text")
    @classmethod
    def plain_text(cls, text: str) -> str:
        if not text.strip() or any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise ValueError("Expected plain answer text")
        # Piper interprets these as explicit phonemes; answers are always literal speech.
        return text.replace("[[", " ").replace("]]", " ")


class SynthesisReply(Schema):
    status: Literal["audio", "error"]
    size: int = Field(default=0, ge=0, le=48000 * MAX_SECONDS * 2, strict=True)
    sample_rate: int = Field(default=22050, ge=8000, le=48000, strict=True)

    @model_validator(mode="after")
    def check_audio(self) -> "SynthesisReply":
        if self.status == "audio":
            if self.size < 2 or self.size % 2 or self.size > self.sample_rate * MAX_SECONDS * 2:
                raise ValueError("Invalid synthesis audio length")
        elif self.size:
            raise ValueError("Errors cannot contain audio")
        return self


class SynthesisError(RuntimeError):
    """Safe diagnostic without model paths, text or native exceptions."""
