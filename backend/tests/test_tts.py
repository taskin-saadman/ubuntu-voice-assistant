import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from voice_assistant.tts.engine import PiperEngine
from voice_assistant.tts.models import (
    PiperSettings,
    SynthesisError,
    SynthesisReply,
    SynthesisRequest,
)
from voice_assistant.tts.piper import PiperSynthesizer

from .test_audio import WorkerFactory, until


class OutputFactory(WorkerFactory):
    fixture = "output_worker_fixture.py"


@pytest.mark.parametrize("text", ["", "   ", "bad\0text", "x" * 8193])
def test_reject_invalid_synthesis_text(text: str) -> None:
    with pytest.raises(ValidationError):
        SynthesisRequest(text=text)


def test_piper_phoneme_markup_is_not_interpreted() -> None:
    assert SynthesisRequest(text="Say [[test]]").text == "Say  test "


@pytest.mark.parametrize("size", [0, 3, 22050 * 90 * 2 + 2, 10**9])
def test_reject_invalid_synthesis_pcm_sizes(size: int) -> None:
    with pytest.raises(ValidationError):
        SynthesisReply(status="audio", size=size, sample_rate=22050)


def test_missing_voice_and_unsupported_phonemizer_fail_before_native_load(tmp_path: Path) -> None:
    model = tmp_path / "voice.onnx"
    settings = PiperSettings(model_path=model)
    with patch("onnxruntime.InferenceSession") as load:
        with pytest.raises(ValueError, match="missing"):
            PiperEngine(settings)
        model.write_bytes(b"fixture")
        with pytest.raises(ValueError, match="missing"):
            PiperEngine(settings)
        Path(str(model) + ".json").write_text(json.dumps({"phoneme_type": "text"}))
        with pytest.raises(ValueError, match="English"):
            PiperEngine(settings)
        load.assert_not_called()


@pytest.mark.parametrize("language", ["en", "en-us"])
def test_engine_cpu_thread_limits_and_no_arabic_resource_download(
    tmp_path: Path, language: str
) -> None:
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"fixture")
    Path(str(model) + ".json").write_text(
        json.dumps(
            {
                "phoneme_type": "espeak",
                "espeak": {"voice": language},
                "audio": {"sample_rate": 22050},
                "num_symbols": 256,
                "num_speakers": 1,
                "phoneme_id_map": {},
            }
        )
    )
    with (
        patch("onnxruntime.InferenceSession") as load,
        patch("onnxruntime.disable_telemetry_events") as telemetry,
    ):
        engine = PiperEngine(PiperSettings(model_path=model))
        assert load.call_args.kwargs["providers"] == ["CPUExecutionProvider"]
        options = load.call_args.kwargs["sess_options"]
        assert options.intra_op_num_threads == 2 and options.inter_op_num_threads == 1
        assert not engine.voice.use_tashkeel
        telemetry.assert_called_once()


@pytest.mark.parametrize("kind", ["empty", "stereo", "rate", "long", "odd", "normal"])
def test_engine_bounds_audio_and_keeps_native_voice_rate(kind: str) -> None:
    chunk = SimpleNamespace(
        sample_channels=2 if kind == "stereo" else 1,
        sample_width=2,
        sample_rate=48000 if kind == "rate" else 22050,
        audio_int16_bytes=b"\0"
        * (22050 * 90 * 2 + 2 if kind == "long" else 3 if kind == "odd" else 200),
    )
    engine = object.__new__(PiperEngine)
    cast(Any, engine).voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda text: iter([] if kind == "empty" else [chunk]),
    )
    if kind == "normal":
        audio = engine.synthesize("Synthetic answer")
        assert audio.sample_rate == 22050 and len(audio.pcm) == 200
    else:
        with pytest.raises(ValueError):
            engine.synthesize("Synthetic answer")


async def test_persistent_worker_reuses_model_and_close_is_permanent() -> None:
    factory = OutputFactory()
    tts = PiperSynthesizer()
    with patch.object(tts.worker, "_launch", factory.launch):
        assert not factory.processes
        for _ in range(2):
            assert (await tts.synthesize("Synthetic answer")).sample_rate == 22050
        assert len(factory.processes) == 1
        await tts.close()
        await tts.close()
        with pytest.raises(SynthesisError, match="closed"):
            await tts.synthesize("Synthetic answer")
    factory.assert_reaped()


@pytest.mark.parametrize("mode", ["malformed", "oversized", "truncated", "error"])
async def test_bad_worker_output_is_private_reaped_and_retryable(mode: str) -> None:
    factory = OutputFactory(mode)
    tts = PiperSynthesizer()
    with patch.object(tts.worker, "_launch", factory.launch):
        with pytest.raises(SynthesisError) as error:
            await tts.synthesize("Private test text")
        assert "Private" not in str(error.value) and "diagnostic" not in str(error.value)
        factory.assert_reaped()
        factory.mode = "normal"
        await tts.synthesize("Synthetic retry")
        await tts.close()
    factory.assert_reaped()


async def test_cancellation_kills_inference_and_lazy_retry_reloads() -> None:
    factory = OutputFactory("hang")
    tts = PiperSynthesizer()
    with patch.object(tts.worker, "_launch", factory.launch):
        task = asyncio.create_task(tts.synthesize("Synthetic answer"))
        await factory.spawned.wait()
        await asyncio.sleep(0.15)
        with pytest.raises(SynthesisError, match="busy"):
            await tts.synthesize("Overlapping answer")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        factory.assert_reaped()
        factory.mode = "normal"
        await tts.synthesize("Synthetic retry")
        await tts.close()
    factory.assert_reaped()


async def test_synthesis_timeout_reaps_worker() -> None:
    factory = OutputFactory("hang")
    tts = PiperSynthesizer(PiperSettings(timeout=0.15))
    with patch.object(tts.worker, "_launch", factory.launch):
        with pytest.raises(SynthesisError):
            await tts.synthesize("Synthetic answer")
    factory.assert_reaped()


async def test_close_during_delayed_spawn_never_sends_text_and_reaps() -> None:
    factory = OutputFactory()
    factory.return_gate = asyncio.Event()
    tts = PiperSynthesizer()
    with patch.object(tts.worker, "_launch", factory.launch):
        task = asyncio.create_task(tts.synthesize("Synthetic answer"))
        await factory.spawned.wait()
        closing = asyncio.create_task(tts.close())
        await until(lambda: tts.worker._stopping)
        factory.return_gate.set()
        with pytest.raises(SynthesisError):
            await task
        await closing
    factory.assert_reaped()


@pytest.mark.parametrize("mode", ["error", "hang"])
async def test_synthesis_failure_or_cancel_keeps_visible_answer_and_allows_retry(mode: str) -> None:
    from dataclasses import replace

    from voice_assistant.controller import Controller
    from voice_assistant.state import AssistantState

    from .fakes import FakeEngines

    fake = FakeEngines()
    tts = PiperSynthesizer()
    factory = OutputFactory(mode)
    c = Controller(replace(fake.components(), tts=tts))
    with patch.object(tts.worker, "_launch", factory.launch):
        await c.set_microphone(True)
        c.release(c.begin_turn())
        await factory.spawned.wait()
        if mode == "hang":
            assert c.preparing_speech and c.state == AssistantState.THINKING
            await c.set_microphone(False)
        await c.wait()
        factory.assert_reaped()
        assert c.components.history.messages()[-1].content == fake.answer
        assert "play" not in fake.calls
        assert not c.preparing_speech and not c.busy
        if mode == "error":
            assert any(
                e.failure and e.failure.code.value == "tts_unavailable" for e in c.events.read()
            )
        c.reset()
        factory.mode = "normal"
        await c.set_microphone(True)
        c.release(c.begin_turn())
        await c.wait()
        assert c.state == AssistantState.IDLE and "play" in fake.calls
        await c.close()
        await tts.close()
    factory.assert_reaped()
