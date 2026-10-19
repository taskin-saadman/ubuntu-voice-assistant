"""Output-device configuration and bounded private playback protocol."""

from typing import Literal

from pydantic import Field, model_validator

from voice_assistant.contracts import Schema


class OutputDevice(Schema):
    index: int = Field(ge=0, strict=True)
    name: str = Field(min_length=1, max_length=256)
    sample_rate: int = Field(ge=8000, le=48000, strict=True)


class PlaybackSettings(Schema):
    device: int | None = Field(default=None, ge=0, strict=True)


class OutputRequest(Schema):
    action: Literal["devices", "play"]
    settings: PlaybackSettings = Field(default_factory=PlaybackSettings)
    size: int = Field(default=0, ge=0, le=11_520_000, strict=True)
    sample_rate: int = Field(default=22050, ge=8000, le=48000, strict=True)

    @model_validator(mode="after")
    def check_audio(self) -> "OutputRequest":
        if self.action == "play":
            if self.size < 2 or self.size % 2 or self.size > self.sample_rate * 120 * 2:
                raise ValueError("Invalid playback length")
        elif self.size:
            raise ValueError("Device listing cannot contain audio")
        return self


class OutputReply(Schema):
    status: Literal["started", "finished", "devices", "error"]
    devices: tuple[OutputDevice, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def check_devices(self) -> "OutputReply":
        if self.devices and self.status != "devices":
            raise ValueError("Only device replies contain devices")
        return self


class PlaybackError(RuntimeError):
    """Safe output diagnostics without native exceptions or audio."""
