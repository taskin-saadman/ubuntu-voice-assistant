import asyncio
import sys
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from voice_assistant.audio.output_models import PlaybackError
from voice_assistant.audio.output_worker import PCMPlayer, play
from voice_assistant.audio.playback import AudioPlayback, output_devices
from voice_assistant.controller import Controller
from voice_assistant.local_worker import LocalWorker
from voice_assistant.state import AssistantState

from .fakes import AUDIO, FakeEngines
from .test_audio import until
from .test_tts import OutputFactory


@pytest.mark.parametrize("channels", [1, 2])
def test_callback_preserves_every_frame_and_zero_pads_final_block(channels: int) -> None:
    pcm = bytes(range(24))
    player = PCMPlayer(pcm, channels)
    output = bytearray(8 * channels)
    chunks = []
    while True:
        final = player.fill(output, 4)
        chunks.append(bytes(output))
        if final:
            break
    result = b"".join(chunks)
    assert result[: len(pcm)] == pcm
    assert set(result[len(pcm) :]) <= {0}


@pytest.mark.parametrize("failure", [None, "start", "underflow", "disconnect"])
def test_native_callback_timing_completion_and_cleanup_without_hardware(
    failure: str | None,
) -> None:
    calls: list[str] = []

    class CallbackStop(Exception):
        pass

    class CallbackAbort(Exception):
        pass

    class Stream:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.tick = 0
            assert kwargs["channels"] == 2 and kwargs["samplerate"] == 48000

        def start(self) -> None:
            calls.append("open")
            if failure == "start":
                raise OSError("private diagnostic")
            while True:
                output = bytearray(b"\xff" * (960 * 4))
                try:
                    self.kwargs["callback"](
                        output,
                        960,
                        SimpleNamespace(outputBufferDacTime=2.0),
                        failure == "underflow",
                    )
                except (CallbackStop, CallbackAbort):
                    if failure == "underflow":
                        assert not any(output)
                    calls.append("queued")
                    break

        @property
        def time(self) -> float:
            self.tick += 1
            if self.tick >= 2:
                calls.append("device_time")
                self.kwargs["finished_callback"]()
            return 1.0 if self.tick == 1 else 2.0

        def abort(self) -> None:
            calls.append("abort")

        def close(self) -> None:
            calls.append("close")

    sd = SimpleNamespace(
        RawOutputStream=Stream,
        CallbackStop=CallbackStop,
        CallbackAbort=CallbackAbort,
        check_output_settings=lambda **kw: None,
        query_devices=lambda *args: {"default_samplerate": 48000, "max_output_channels": 2},
    )
    with patch.dict(sys.modules, {"sounddevice": sd}):
        if failure:
            with pytest.raises((OSError, RuntimeError)):
                play(AUDIO, None, lambda: calls.append("started"), lambda: failure == "disconnect")
            assert "started" not in calls
        else:
            play(AUDIO, None, lambda: calls.append("started"), lambda: False)
            assert calls.index("device_time") < calls.index("started")
        assert calls[-2:] == ["abort", "close"]


async def test_playback_signals_start_once_reaps_and_supports_next_turn() -> None:
    factory = OutputFactory()
    playback = AudioPlayback()
    calls: list[str] = []
    with patch.object(playback.worker, "_launch", factory.launch):
        for _ in range(2):
            await playback.play(AUDIO, lambda: calls.append("started"))
            factory.assert_reaped()
        await playback.stop()
    assert calls == ["started", "started"]


@pytest.mark.parametrize("mode", ["early_error", "late_error", "malformed"])
async def test_playback_errors_do_not_leak_or_leave_processes(mode: str) -> None:
    factory = OutputFactory(mode)
    playback = AudioPlayback()
    started: list[bool] = []
    with patch.object(playback.worker, "_launch", factory.launch):
        with pytest.raises(PlaybackError) as error:
            await playback.play(AUDIO, lambda: started.append(True))
        assert "diagnostic" not in str(error.value)
        assert started == ([True] if mode == "late_error" else [])
    factory.assert_reaped()


@pytest.mark.parametrize("mode", ["slow_start", "hang"])
async def test_cancel_before_or_during_playback_reaps_and_allows_retry(mode: str) -> None:
    factory = OutputFactory(mode)
    playback = AudioPlayback()
    started = asyncio.Event()
    with patch.object(playback.worker, "_launch", factory.launch):
        task = asyncio.create_task(playback.play(AUDIO, started.set))
        if mode == "hang":
            await asyncio.wait_for(started.wait(), 2)
        else:
            await factory.spawned.wait()
        with pytest.raises(PlaybackError, match="active"):
            await playback.play(AUDIO, lambda: None)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        factory.assert_reaped()
        factory.mode = "normal"
        await playback.play(AUDIO, lambda: None)
    factory.assert_reaped()


async def test_stop_during_delayed_spawn_cannot_later_start_audio() -> None:
    factory = OutputFactory()
    factory.return_gate = asyncio.Event()
    playback = AudioPlayback()
    calls: list[bool] = []
    with patch.object(playback.worker, "_launch", factory.launch):
        playing = asyncio.create_task(playback.play(AUDIO, lambda: calls.append(True)))
        await factory.spawned.wait()
        stopping = asyncio.create_task(playback.stop())
        await until(lambda: playback.worker._stopping)
        factory.return_gate.set()
        with pytest.raises(PlaybackError):
            await playing
        await stopping
    assert not calls
    factory.assert_reaped()


async def test_output_enumeration_does_not_play_audio() -> None:
    factory = OutputFactory()
    with patch.object(LocalWorker, "_launch", lambda self: factory.launch()):
        devices = await output_devices()
    assert devices[0].index == 4
    factory.assert_reaped()


async def test_controller_keeps_answer_on_playback_failure() -> None:
    factory = OutputFactory("late_error")
    playback = AudioPlayback()
    fake = FakeEngines()
    c = Controller(replace(fake.components(), playback=playback))
    with patch.object(playback.worker, "_launch", factory.launch):
        await c.set_microphone(True)
        c.release(c.begin_turn())
        await c.wait()
        assert c.state == AssistantState.ERROR and not c.busy
        assert c.components.history.messages()[-1].content == fake.answer
        assert any(e.failure and e.failure.code.value == "playback_failed" for e in c.events.read())
        await c.close()
    factory.assert_reaped()


async def test_cancelled_stop_waiter_does_not_abandon_native_cleanup() -> None:
    factory = OutputFactory("hang")
    playback = AudioPlayback()
    started = asyncio.Event()
    with patch.object(playback.worker, "_launch", factory.launch):
        task = asyncio.create_task(playback.play(AUDIO, started.set))
        await asyncio.wait_for(started.wait(), 2)
        stopping = asyncio.create_task(playback.stop())
        await asyncio.sleep(0.02)
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        await playback.stop()
        with pytest.raises(PlaybackError):
            await task
    factory.assert_reaped()
