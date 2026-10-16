"""List compatible input devices without opening a recording stream."""

import asyncio

from voice_assistant.audio.capture import input_devices
from voice_assistant.audio.models import CaptureError


async def list_inputs() -> int:
    try:
        devices = await input_devices()
    except (CaptureError, TimeoutError, OSError):
        print("Input devices unavailable. Check PortAudio and the desktop audio session.")
        return 1
    if not devices:
        print("No compatible input devices found.")
        return 1
    for device in devices:
        print(f"{device.index}: {device.name} ({device.sample_rate} Hz)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(list_inputs()))
