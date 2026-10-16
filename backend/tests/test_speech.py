import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from pydantic import ValidationError
from voice_assistant.contracts import AudioBuffer
from voice_assistant.speech.adapters import SileroVAD, SpeechWorker, WhisperTranscriber
from voice_assistant.speech.engine import ModelMissing, SpeechEngine, samples, speech_present
from voice_assistant.speech.models import SpeechError, SpeechReply, SpeechRequest, SpeechSettings

from .fakes import AUDIO
from .test_audio import WorkerFactory


def local_model(tmp_path: Path) -> SpeechSettings:
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        (tmp_path / name).write_bytes(b"synthetic fixture")
    return SpeechSettings(model_path=tmp_path)


@pytest.mark.parametrize(
    "missing", ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]
)
def test_incomplete_model_fails_before_native_loader_or_tokenizer_lookup(
    tmp_path: Path, missing: str
) -> None:
    settings = local_model(tmp_path)
    (tmp_path / missing).unlink()
    with patch("faster_whisper.WhisperModel") as load:
        with pytest.raises(ModelMissing):
            SpeechEngine(settings)
        load.assert_not_called()


def test_settings_require_local_paths_and_finite_bounded_resources() -> None:
    for settings in [
        {"model_path": "small.en"},
        {"model_path": "https://example.org/model"},
        {"timeout": float("inf")},
        {"timeout": -1},
        {"cpu_threads": 17},
    ]:
        with pytest.raises(ValidationError):
            SpeechSettings.model_validate(settings)


def test_pcm_conversion_preserves_signed_scale_and_real_silero_rejects_silence() -> None:
    assert samples(b"\0\x80\0\0\xff\x7f").tolist() == [-1, 0, 32767 / 32768]
    for length in (1, 16000):
        assert not speech_present(np.zeros(length, dtype=np.float32))


def test_native_engine_stays_cpu_local_and_skips_decoder_for_silence(tmp_path: Path) -> None:
    settings = local_model(tmp_path)
    with (
        patch("faster_whisper.WhisperModel") as load,
        patch("voice_assistant.speech.engine.speech_present", return_value=False),
    ):
        engine = SpeechEngine(settings)
        assert engine.transcribe(AUDIO.pcm) == ""
        load.return_value.transcribe.assert_not_called()
        assert load.call_args.kwargs == {
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 8,
            "num_workers": 1,
            "local_files_only": True,
        }


@dataclass
class Segment:
    text: str


def test_transcription_consumes_lazy_segments_and_bounds_result(tmp_path: Path) -> None:
    settings = local_model(tmp_path)
    consumed: list[bool] = []

    def segments() -> Iterator[Segment]:
        yield Segment(" First")
        consumed.append(True)
        yield Segment(" sentence. ")

    with (
        patch("faster_whisper.WhisperModel") as load,
        patch("voice_assistant.speech.engine.speech_present", return_value=True),
    ):
        engine = SpeechEngine(settings)
        load.return_value.transcribe.return_value = (segments(), None)
        assert engine.transcribe(AUDIO.pcm) == "First sentence."
        assert consumed == [True]
        assert load.return_value.transcribe.call_args.kwargs["condition_on_previous_text"] is False
        load.return_value.transcribe.return_value = (iter([Segment("x" * 8193)]), None)
        with pytest.raises(ValueError):
            engine.transcribe(AUDIO.pcm)


def test_worker_schemas_reject_invalid_sizes_and_wrong_payloads() -> None:
    for payload in [
        {"action": "vad", "size": 3},
        {"action": "transcribe", "size": 960002},
        {"action": "initialize"},
        {"action": "warmup", "size": 2},
    ]:
        with pytest.raises(ValidationError):
            SpeechRequest.model_validate(payload)
    for payload in [
        {"status": "vad"},
        {"status": "ready", "text": "private"},
        {"status": "transcript", "text": "x" * 8193},
        {"status": "vad", "speech": "yes"},
    ]:
        with pytest.raises(ValidationError):
            SpeechReply.model_validate(payload)
    assert "private" not in repr(SpeechReply(status="transcript", text="private"))


class SpeechFactory(WorkerFactory):
    fixture = "speech_worker_fixture.py"


async def test_adapters_share_resident_worker_and_close_prevents_reuse() -> None:
    factory = SpeechFactory()
    worker = SpeechWorker()
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        assert not factory.processes
        await worker.warmup()
        for _ in range(2):
            assert await SileroVAD(worker).has_speech(AUDIO)
            assert await WhisperTranscriber(worker).transcribe(AUDIO) == "Synthetic speech"
        assert len(factory.processes) == 1
        await worker.close()
        await worker.close()
        with pytest.raises(SpeechError, match="closed"):
            await worker.warmup()
    factory.assert_reaped()


async def test_invalid_audio_never_starts_worker() -> None:
    factory = SpeechFactory()
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        for audio in [
            AudioBuffer(pcm=b"\0\0", sample_rate=48000),
            AudioBuffer(pcm=b"\0\0" * 480001, sample_rate=16000),
        ]:
            with pytest.raises(SpeechError, match="16 kHz"):
                await SileroVAD(SpeechWorker()).has_speech(audio)
    assert not factory.processes


@pytest.mark.parametrize("mode", ["malformed", "wrong_status"])
async def test_invalid_response_is_safe_and_releases_worker(mode: str) -> None:
    factory = SpeechFactory(mode)
    worker = SpeechWorker()
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        with pytest.raises(SpeechError) as failure:
            await SileroVAD(worker).has_speech(AUDIO)
        assert "secret" not in str(failure.value)
        await worker.close()
    factory.assert_reaped()


async def test_cancelled_inference_kills_stubborn_worker_and_next_request_reloads() -> None:
    factory = SpeechFactory("hang")
    worker = SpeechWorker()
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        await worker.warmup()
        task = asyncio.create_task(WhisperTranscriber(worker).transcribe(AUDIO))
        await asyncio.sleep(0.05)
        with pytest.raises(SpeechError, match="busy"):
            await worker.warmup()
        # Event loop stays responsive while native worker is deliberately blocked.
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await heartbeat.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        factory.assert_reaped()
        factory.mode = "normal"
        assert await WhisperTranscriber(worker).transcribe(AUDIO) == "Synthetic speech"
        assert len(factory.processes) == 2
        await worker.close()
    factory.assert_reaped()


async def test_request_timeout_stops_worker() -> None:
    factory = SpeechFactory("hang")
    worker = SpeechWorker(SpeechSettings(timeout=2))
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        await worker.warmup()
        worker.settings = SpeechSettings(timeout=0.1)
        with pytest.raises(SpeechError, match="timed out"):
            await WhisperTranscriber(worker).transcribe(AUDIO)
        factory.assert_reaped()
        await worker.close()


async def test_cancel_during_initialization_reaps_child() -> None:
    factory = SpeechFactory("slow_init")
    worker = SpeechWorker()
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        task = asyncio.create_task(worker.warmup())
        await factory.spawned.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await worker.close()
    factory.assert_reaped()


async def test_close_during_delayed_spawn_does_not_load_model() -> None:
    factory = SpeechFactory()
    factory.return_gate = asyncio.Event()
    worker = SpeechWorker()
    with patch("voice_assistant.speech.adapters._launch", factory.launch):
        task = asyncio.create_task(worker.warmup())
        await factory.spawned.wait()
        close = asyncio.create_task(worker.close())
        await asyncio.sleep(0)
        factory.return_gate.set()
        with pytest.raises(SpeechError):
            await task
        await close
    factory.assert_reaped()
