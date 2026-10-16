"""Small, bounded schemas for capture configuration and private worker messages."""

from typing import Literal

from pydantic import Field, model_validator

from voice_assistant.contracts import Schema

TARGET_RATE = 16000
MAX_SECONDS = 30
MAX_PCM_BYTES = TARGET_RATE * MAX_SECONDS * 2
CaptureFailure = Literal["unavailable", "unsupported_format", "overflow", "limit_reached", "failed"]


class CaptureSettings(Schema):
    device: int | None = Field(default=None, ge=0, strict=True)
    max_seconds: float = Field(default=MAX_SECONDS, ge=0.1, le=MAX_SECONDS, allow_inf_nan=False)


class InputDevice(Schema):
    index: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=256)
    sample_rate: int = Field(ge=8000, le=48000)


class WorkerRequest(Schema):
    action: Literal["devices", "capture"]
    settings: CaptureSettings = Field(default_factory=CaptureSettings)


class WorkerReply(Schema):
    status: Literal["started", "audio", "devices", "error"]
    size: int = Field(default=0, ge=0, le=MAX_PCM_BYTES)
    devices: tuple[InputDevice, ...] = Field(default=(), max_length=128)
    error: CaptureFailure | None = None

    @model_validator(mode="after")
    def check_payload(self) -> "WorkerReply":
        if self.status == "audio":
            if self.size < 2 or self.size % 2:
                raise ValueError("Audio reply requires whole PCM frames")
        elif self.size:
            raise ValueError("Only audio replies have a payload")
        if self.devices and self.status != "devices":
            raise ValueError("Only device replies list devices")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("Only error replies carry an error code")
        return self


class CaptureError(RuntimeError):
    """Safe diagnostics, never a native exception or captured audio."""


ERROR_MESSAGES = {
    "unavailable": "Microphone unavailable. Install PortAudio and check the input device.",
    "unsupported_format": "Choose a mono-capable input with a sample rate between 8 and 48 kHz.",
    "overflow": "The microphone dropped audio. Close other audio workloads and try again.",
    "limit_reached": "Recording reached its time limit. Release the button and try a shorter turn.",
    "failed": "Microphone capture failed. Check the input device and try again.",
}
