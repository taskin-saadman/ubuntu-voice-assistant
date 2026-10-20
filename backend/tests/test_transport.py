import asyncio
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from voice_assistant.api import create_app
from voice_assistant.audio.models import InputDevice
from voice_assistant.audio.output_models import OutputDevice
from voice_assistant.controller import Controller, TranscriptionComponents
from voice_assistant.transport import DesktopTransport

from .fakes import FakeEngines

TOKEN = "a" * 43
ORIGIN = {"origin": "http://127.0.0.1:1420"}


class FakeRuntime:
    def __init__(self) -> None:
        self.fake = FakeEngines()
        self.controller = Controller(
            TranscriptionComponents(
                capture=self.fake,
                vad=self.fake,
                stt=self.fake,
                history=self.fake.components().history,
            )
        )
        self.ready = False
        self.device: int | None = None
        self.devices: tuple[InputDevice, ...] = ()
        self.outputs: tuple[OutputDevice, ...] = ()
        self.output_device: int | None = None

    async def prepare(self) -> None:
        self.ready = True
        self.devices = (InputDevice(index=3, name="Synthetic input", sample_rate=48000),)

    def select_device(self, device: int | None) -> None:
        self.device = device

    def select_output(self, device: int | None) -> None:
        self.output_device = device

    async def microphone(self, enabled: bool) -> None:
        await self.controller.set_microphone(enabled)

    async def close(self) -> None:
        await self.controller.close()


def receive(socket: Any, kind: str) -> dict[str, Any]:
    for _ in range(50):
        packet: dict[str, Any] = socket.receive_json()
        if packet["kind"] == kind:
            return packet
    raise AssertionError("Expected packet was not received")


def command(socket: Any, action: str, **arguments: object) -> dict[str, Any]:
    request_id = str(uuid4())
    socket.send_json({"id": request_id, "action": action, **arguments})
    response = receive(socket, "ack")
    assert response["id"] == request_id
    return response


@pytest.mark.parametrize(
    "origin", [None, "null", "https://evil.example", "http://127.0.0.1:1420.evil"]
)
def test_untrusted_or_missing_origins_cannot_connect(origin: str | None) -> None:
    runtime = FakeRuntime()
    with TestClient(
        create_app(desktop=DesktopTransport(runtime, TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://127.0.0.1/session", headers={} if origin is None else {"origin": origin}
            ):
                pass
    assert "start" not in runtime.fake.calls


def test_wrong_key_no_data_or_controls_and_no_key_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    runtime = FakeRuntime()
    with TestClient(
        create_app(desktop=DesktopTransport(runtime, TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": "b" * 43})
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_json()
            assert error.value.code == 4401
    assert TOKEN not in caplog.text and "start" not in runtime.fake.calls


def test_query_credentials_are_rejected() -> None:
    with TestClient(
        create_app(desktop=DesktopTransport(FakeRuntime(), TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://127.0.0.1/session?token=anything", headers=ORIGIN):
                pass


def test_authenticated_turn_streams_state_and_transcript() -> None:
    runtime = FakeRuntime()
    with TestClient(
        create_app(desktop=DesktopTransport(runtime, TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            initial = receive(socket, "snapshot")
            assert initial["microphone_enabled"] is False and initial["messages"] == []
            assert command(socket, "start")["error"] is not None
            assert command(socket, "prepare")["error"] is None
            command(socket, "device", device=3)
            command(socket, "microphone", enabled=True)
            turn = command(socket, "start")["turn_id"]
            assert turn
            command(socket, "release", turn_id=str(uuid4()))  # Stale control is harmless.
            command(socket, "release", turn_id=turn)
            while True:
                snapshot = receive(socket, "snapshot")
                if snapshot["state"] == "idle" and not snapshot["busy"]:
                    break
            assert snapshot["messages"][0]["content"] == runtime.fake.text
            assert snapshot["sequence"] > initial["sequence"]
    assert not runtime.fake.capturing and not runtime.controller.microphone_enabled


def test_second_authenticated_client_cannot_take_over() -> None:
    runtime = FakeRuntime()
    with TestClient(
        create_app(desktop=DesktopTransport(runtime, TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as first:
            first.send_json({"version": 1, "token": TOKEN})
            receive(first, "snapshot")
            with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as second:
                second.send_json({"version": 1, "token": TOKEN})
                with pytest.raises(WebSocketDisconnect) as error:
                    second.receive_json()
                assert error.value.code == 4409
            assert command(first, "ping")["error"] is None


@pytest.mark.parametrize(
    "reason", ["disconnect", "heartbeat", "invalid", "binary", "unknown", "oversized"]
)
def test_loss_of_control_stops_microphone(reason: str) -> None:
    runtime = FakeRuntime()
    transport = DesktopTransport(runtime, TOKEN, heartbeat_timeout=0.2)
    with TestClient(create_app(desktop=transport), base_url="http://127.0.0.1") as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            receive(socket, "snapshot")
            command(socket, "prepare")
            command(socket, "microphone", enabled=True)
            command(socket, "start")
            if reason == "invalid":
                socket.send_json({"id": str(uuid4()), "action": "microphone", "enabled": "false"})
            elif reason == "binary":
                socket.send_bytes(b"invalid binary control")
            elif reason == "unknown":
                socket.send_json({"id": str(uuid4()), "action": "shell"})
            elif reason == "oversized":
                socket.send_text("x" * 2049)
            if reason != "disconnect":
                with pytest.raises(WebSocketDisconnect):
                    while True:
                        socket.receive_json()
        # Check before application lifespan cleanup can mask a disconnected-session leak.
        assert not runtime.fake.capturing and not runtime.controller.microphone_enabled
        assert not runtime.controller.busy
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as retry:
            retry.send_json({"version": 1, "token": TOKEN})
            assert receive(retry, "snapshot")["microphone_enabled"] is False


def test_replayed_command_closes_session() -> None:
    with TestClient(
        create_app(desktop=DesktopTransport(FakeRuntime(), TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            receive(socket, "snapshot")
            request = {"id": str(uuid4()), "action": "ping"}
            socket.send_json(request)
            receive(socket, "ack")
            socket.send_json(request)
            with pytest.raises(WebSocketDisconnect):
                while True:
                    socket.receive_json()


def test_heartbeat_remains_responsive_while_model_loads() -> None:
    class SlowRuntime(FakeRuntime):
        async def prepare(self) -> None:
            await asyncio.Event().wait()  # Deliberately stalled until disconnect cancels it.

    runtime = SlowRuntime()
    with TestClient(
        create_app(desktop=DesktopTransport(runtime, TOKEN, heartbeat_timeout=0.2)),
        base_url="http://127.0.0.1",
    ) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            receive(socket, "snapshot")
            prepare_id = str(uuid4())
            socket.send_json({"id": prepare_id, "action": "prepare"})
            for _ in range(4):
                assert command(socket, "ping")["error"] is None
            # Model loading has not blocked the independent receive/send loops.
            assert not runtime.ready


def test_authenticated_streaming_draft_and_disconnect_cleanup() -> None:
    from .test_conversation import StreamingFake, controller_for

    fake = StreamingFake()
    fake.gates["llm"] = asyncio.Event()
    runtime = FakeRuntime()
    runtime.controller = controller_for(fake)
    with TestClient(
        create_app(desktop=DesktopTransport(runtime, TOKEN)), base_url="http://127.0.0.1"
    ) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            assert receive(socket, "snapshot")["draft"] == ""
            command(socket, "prepare")
            command(socket, "microphone", enabled=True)
            turn = command(socket, "start")["turn_id"]
            command(socket, "release", turn_id=turn)
            while True:
                snapshot = receive(socket, "snapshot")
                if snapshot["draft"]:
                    break
            assert snapshot["state"] == "thinking"
            assert snapshot["draft"] == "Partial answer"
            assert len(snapshot["messages"]) == 1
        assert runtime.controller.draft == ""
        assert not runtime.controller.busy and not runtime.controller.microphone_enabled


def test_output_selection_and_preparing_speech_snapshot() -> None:
    runtime = FakeRuntime()
    runtime.outputs = (OutputDevice(index=4, name="Synthetic output", sample_rate=48000),)
    runtime.controller.preparing_speech = True
    with TestClient(create_app(desktop=DesktopTransport(runtime, TOKEN))) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            snapshot = receive(socket, "snapshot")
            assert snapshot["preparing_speech"]
            assert snapshot["outputs"][0]["index"] == 4
            assert command(socket, "output", device=4)["error"] is None
            assert runtime.output_device == 4
            assert command(socket, "output", device=None)["error"] is None
            assert runtime.output_device is None


def test_disconnect_cancels_playback_and_preserves_completed_answer() -> None:
    runtime = FakeRuntime()
    runtime.controller = Controller(runtime.fake.components())
    runtime.fake.gates["play"] = asyncio.Event()
    with TestClient(create_app(desktop=DesktopTransport(runtime, TOKEN))) as client:
        with client.websocket_connect("ws://127.0.0.1/session", headers=ORIGIN) as socket:
            socket.send_json({"version": 1, "token": TOKEN})
            receive(socket, "snapshot")
            command(socket, "prepare")
            command(socket, "microphone", enabled=True)
            turn = command(socket, "start")["turn_id"]
            command(socket, "release", turn_id=turn)
            for _ in range(50):
                if receive(socket, "snapshot")["state"] == "speaking":
                    break
            else:
                raise AssertionError("Speaking was not reached")
        # A new session is not admitted until prior playback is stopped.
        assert client.portal is not None
        client.portal.call(runtime.controller.wait)
    assert not runtime.fake.playing and not runtime.controller.microphone_enabled
    assert runtime.controller.components.history.messages()[-1].role == "assistant"
