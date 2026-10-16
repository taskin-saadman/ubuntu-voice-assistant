import asyncio
import math
import struct
import sys
from asyncio.subprocess import PIPE, Process
from collections.abc import Buffer, Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from voice_assistant.audio.capture import MicrophoneCapture, input_devices
from voice_assistant.audio.models import CaptureError, CaptureSettings, WorkerReply
from voice_assistant.audio.normalize import normalize
from voice_assistant.audio.worker import RecordingFailed, record
from voice_assistant.contracts import AudioBuffer
from voice_assistant.controller import Controller, Deadlines
from voice_assistant.state import AssistantState

from .fakes import FakeEngines


class SyntheticStream:
    def __init__(self) -> None:
        self.reads = 0
        self.frames = 0
        self.closed = False
        self.fail: str | None = None

    def start(self) -> None:
        if self.fail == "start":
            raise OSError("private native diagnostic")

    def read(self, frames: int) -> tuple[Buffer, bool]:
        self.reads += 1
        self.frames += frames
        if self.fail == "read":
            raise OSError("private native diagnostic")
        return b"\0\0" * (frames - (self.fail == "short")), self.fail == "overflow"

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("rate", [8000, 16000, 44100, 48000])
def test_normalization_preserves_tone_duration_and_amplitude(rate: int) -> None:
    values = [round(12000 * math.sin(2 * math.pi * 440 * n / rate)) for n in range(rate)]
    audio = normalize(AudioBuffer(pcm=struct.pack(f"<{rate}h", *values), sample_rate=rate))
    assert audio.sample_rate == 16000
    assert audio.duration == pytest.approx(1, abs=1 / 16000)
    actual = struct.unpack(f"<{len(audio.pcm) // 2}h", audio.pcm)
    expected = [12000 * math.sin(2 * math.pi * 440 * n / 16000) for n in range(len(actual))]
    # Ignore filter edges; guards against alignment padding, wrong rate and endian errors.
    rms_error = math.sqrt(
        sum((a - b) ** 2 for a, b in zip(actual[100:-100], expected[100:-100], strict=True))
        / (len(actual) - 200)
    )
    assert rms_error < 20


def test_record_closes_before_normalizing_and_empty_release_is_silence() -> None:
    stream = SyntheticStream()
    started: list[bool] = []
    audio = record(stream, 48000, CaptureSettings(), lambda: True, lambda: started.append(True))
    assert started == [True]
    assert stream.closed and stream.reads == 0
    assert audio.pcm == b"\0\0" and audio.sample_rate == 16000


def test_record_buffers_only_until_release() -> None:
    stream = SyntheticStream()
    audio = record(stream, 48000, CaptureSettings(), lambda: stream.reads == 5, lambda: None)
    assert stream.closed and stream.reads == 5
    assert audio.duration == pytest.approx(0.1)
    assert not any(audio.pcm)


@pytest.mark.parametrize("failure", ["start", "read", "short", "overflow"])
def test_device_failures_and_dropped_audio_always_close_capture(failure: str) -> None:
    stream = SyntheticStream()
    stream.fail = failure
    with pytest.raises((OSError, RecordingFailed)):
        record(stream, 16000, CaptureSettings(), lambda: False, lambda: None)
    assert stream.closed


def test_frame_limit_bounds_memory_without_button_release() -> None:
    stream = SyntheticStream()
    with pytest.raises(RecordingFailed) as failure:
        record(stream, 16000, CaptureSettings(max_seconds=0.1), lambda: False, lambda: None)
    assert failure.value.code == "limit_reached"
    assert stream.frames == 1600 and stream.closed


def test_wall_clock_limit_stops_a_slow_stream_before_frame_limit() -> None:
    stream = SyntheticStream()
    ticks = iter([0.0, 0.0, 0.2])
    with pytest.raises(RecordingFailed):
        record(
            stream,
            16000,
            CaptureSettings(max_seconds=0.1),
            lambda: False,
            lambda: None,
            clock=lambda: next(ticks),
        )
    assert stream.reads == 1 and stream.closed


@pytest.mark.parametrize("seconds", [0, -1, 31, float("inf"), float("nan")])
def test_capture_limit_rejects_unsafe_settings(seconds: float) -> None:
    with pytest.raises(ValidationError):
        CaptureSettings(max_seconds=seconds)


def test_ipc_rejects_oversized_or_inconsistent_messages() -> None:
    for payload in [
        {"status": "audio", "size": 99999999},
        {"status": "audio", "size": 3},
        {"status": "started", "size": 100},
        {"status": "error"},
        {"status": "started", "error": "failed"},
    ]:
        with pytest.raises(ValidationError):
            WorkerReply.model_validate(payload)


class WorkerFactory:
    def __init__(self, mode: str = "normal") -> None:
        self.mode = mode
        self.processes: list[Process] = []
        self.spawned = asyncio.Event()
        self.return_gate: asyncio.Event | None = None

    async def launch(self) -> Process:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("audio_worker_fixture.py")),
            self.mode,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
        )
        self.processes.append(process)
        self.spawned.set()
        if self.return_gate is not None:
            await self.return_gate.wait()
        return process

    def assert_reaped(self) -> None:
        assert self.processes and all(p.returncode is not None for p in self.processes)


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():  # noqa: ASYNC110 — bounded observation of external process/state
            await asyncio.sleep(0.001)


async def test_capture_lifecycle_is_lazy_reusable_and_single_owner() -> None:
    factory = WorkerFactory()
    capture = MicrophoneCapture()
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        assert not factory.processes
        for _ in range(2):
            await capture.start()
            with pytest.raises(CaptureError, match="already in use"):
                await capture.start()
            audio = await capture.finish()
            assert audio.duration == 0.1 and audio.sample_rate == 16000
            factory.assert_reaped()
        await capture.abort()
        await capture.abort()


async def test_device_listing_uses_separate_worker_without_capture_request() -> None:
    factory = WorkerFactory("devices")
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        devices = await input_devices()
    assert devices[0].index == 2 and devices[0].sample_rate == 48000
    factory.assert_reaped()


async def test_unavailable_device_has_safe_error_and_releases_worker() -> None:
    factory = WorkerFactory("unavailable")
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        with pytest.raises(CaptureError, match="PortAudio"):
            await MicrophoneCapture().start()
    factory.assert_reaped()


@pytest.mark.parametrize("mode", ["malformed", "oversized", "truncated"])
async def test_bad_worker_response_is_rejected_without_content_leak(mode: str) -> None:
    factory = WorkerFactory(mode)
    capture = MicrophoneCapture()
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await capture.start()
        with pytest.raises(CaptureError) as failure:
            await capture.finish()
    assert "secret" not in str(failure.value)
    factory.assert_reaped()


async def test_cancelled_start_reaps_worker_before_returning() -> None:
    factory = WorkerFactory("slow_start")
    capture = MicrophoneCapture()
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        start = asyncio.create_task(capture.start())
        await factory.spawned.wait()
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start
    factory.assert_reaped()


async def test_abort_during_delayed_spawn_never_sends_capture_request() -> None:
    factory = WorkerFactory()
    factory.return_gate = asyncio.Event()
    capture = MicrophoneCapture()
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        start = asyncio.create_task(capture.start())
        await factory.spawned.wait()
        abort = asyncio.create_task(capture.abort())
        await asyncio.sleep(0)
        factory.return_gate.set()
        with pytest.raises(CaptureError, match="cancelled"):
            await start
        await abort
    factory.assert_reaped()


@pytest.mark.parametrize("mode", ["hang_read", "ignore_term"])
async def test_cancelling_blocked_finish_terminates_even_a_stubborn_worker(mode: str) -> None:
    factory = WorkerFactory(mode)
    capture = MicrophoneCapture()
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await capture.start()
        finish = asyncio.create_task(capture.finish())
        await asyncio.sleep(0.02)
        finish.cancel()
        async with asyncio.timeout(2):
            with pytest.raises(asyncio.CancelledError):
                await finish
    factory.assert_reaped()


async def test_adapter_watchdog_stops_capture_when_release_is_lost() -> None:
    factory = WorkerFactory("hang_read")
    capture = MicrophoneCapture(CaptureSettings(max_seconds=0.1))
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await capture.start()
        await until(lambda: factory.processes[0].returncode is not None)
        with pytest.raises(CaptureError, match="time limit"):
            await capture.finish()
    factory.assert_reaped()


async def test_controller_microphone_off_stops_process_and_remains_reusable() -> None:
    factory = WorkerFactory("hang_read")
    capture = MicrophoneCapture()
    fake = FakeEngines()
    controller = Controller(replace(fake.components(), capture=capture))
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        for _ in range(2):
            await controller.set_microphone(True)
            controller.begin_turn()
            await until(lambda: controller.state == AssistantState.LISTENING)
            await controller.set_microphone(False)
            factory.assert_reaped()
            assert controller.state == AssistantState.IDLE
            assert not controller.busy
        await controller.close()


async def test_controller_release_and_silence_never_reaches_llm() -> None:
    factory = WorkerFactory()
    fake = FakeEngines()
    fake.speech = False
    controller = Controller(replace(fake.components(), capture=MicrophoneCapture()))
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await controller.set_microphone(True)
        controller.release(controller.begin_turn())
        await controller.wait()
        await controller.close()
    factory.assert_reaped()
    assert "llm" not in fake.calls
    assert controller.state == AssistantState.IDLE
    assert any(e.outcome == "no_speech" for e in controller.events.read())


async def test_controller_deadline_releases_worker_and_can_reset() -> None:
    factory = WorkerFactory("hang_read")
    fake = FakeEngines()
    controller = Controller(
        replace(fake.components(), capture=MicrophoneCapture()), Deadlines(recording=0.05)
    )
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await controller.set_microphone(True)
        controller.begin_turn()
        await controller.wait()
        factory.assert_reaped()
        assert controller.state == AssistantState.ERROR
        controller.reset()
        await controller.close()


@pytest.mark.parametrize("mode", ["slow_start", "ignore_term"])
async def test_controller_cancel_during_native_work_allows_next_turn(mode: str) -> None:
    factory = WorkerFactory(mode)
    fake = FakeEngines()
    controller = Controller(replace(fake.components(), capture=MicrophoneCapture()))
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await controller.set_microphone(True)
        turn = controller.begin_turn()
        if mode == "slow_start":
            await factory.spawned.wait()
        else:
            await until(lambda: controller.state == AssistantState.LISTENING)
            controller.release(turn)
            await asyncio.sleep(0.02)
        await controller.cancel(turn)
        factory.assert_reaped()
        assert not controller.busy
        # A cooperatively cancelled adapter may need a few ms to reap its process.
        # Successful cleanup must not permanently poison the controller.
        controller.reset()
        factory.mode = "normal"
        fake.speech = False
        controller.release(controller.begin_turn())
        await controller.wait()
        await controller.close()
    factory.assert_reaped()
    assert controller.state == AssistantState.IDLE


async def test_cancelled_abort_waiter_does_not_abandon_cleanup() -> None:
    factory = WorkerFactory("ignore_term")
    capture = MicrophoneCapture()
    with patch("voice_assistant.audio.capture._launch", factory.launch):
        await capture.start()
        abort = asyncio.create_task(capture.abort())
        await asyncio.sleep(0.02)
        abort.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abort
        await capture.abort()
    factory.assert_reaped()
