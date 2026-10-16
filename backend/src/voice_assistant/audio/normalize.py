"""Resample in the audio worker, reusing the project's existing PyAV dependency."""

import av

from voice_assistant.audio.models import TARGET_RATE
from voice_assistant.contracts import AudioBuffer


def normalize(audio: AudioBuffer) -> AudioBuffer:
    if audio.sample_rate == TARGET_RATE:
        return audio
    frame = av.AudioFrame(format="s16", layout="mono", samples=len(audio.pcm) // 2)
    frame.sample_rate = audio.sample_rate
    frame.planes[0].update(audio.pcm)
    resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)
    frames = [*resampler.resample(frame), *resampler.resample(None)]
    # FFmpeg planes include alignment padding, which is not captured audio.
    pcm = b"".join(bytes(item.planes[0])[: item.samples * 2] for item in frames)
    return AudioBuffer(pcm=pcm or b"\0\0", sample_rate=TARGET_RATE)
