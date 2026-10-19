"""Bounded, loopback-only Qwen settings."""

from typing import Literal

from pydantic import Field

from voice_assistant.contracts import Schema


class LlamaSettings(Schema):
    port: int = Field(default=8080, ge=1, le=65535, strict=True)
    model: Literal["qwen3-4b"] = "qwen3-4b"
    context_size: Literal[4096] = 4096
    max_tokens: int = Field(default=384, ge=1, le=512, strict=True)
    timeout: float = Field(default=55, gt=0, le=60, allow_inf_nan=False)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
