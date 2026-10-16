"""Authenticated, origin-restricted, single-owner desktop WebSocket transport."""

import asyncio
import secrets
from collections import deque
from contextlib import suppress
from time import monotonic
from typing import Literal, Protocol
from uuid import UUID

from anyio import CancelScope
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import Field, ValidationError, model_validator

from voice_assistant.audio.models import CaptureError, InputDevice
from voice_assistant.contracts import Message, Schema
from voice_assistant.controller import Controller, ControllerRejected
from voice_assistant.events import Event
from voice_assistant.speech.models import SpeechError
from voice_assistant.state import AssistantState

ORIGINS = frozenset({"http://127.0.0.1:1420", "tauri://localhost", "http://tauri.localhost"})


class SessionRuntime(Protocol):
    controller: Controller
    devices: tuple[InputDevice, ...]

    @property
    def ready(self) -> bool: ...
    @property
    def device(self) -> int | None: ...
    async def prepare(self) -> None: ...
    def select_device(self, device: int | None) -> None: ...
    async def microphone(self, enabled: bool) -> None: ...
    async def close(self) -> None: ...


class Authentication(Schema):
    version: Literal[1]
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)


class Command(Schema):
    id: UUID
    action: Literal[
        "ping", "prepare", "device", "microphone", "start", "release", "cancel", "reset"
    ]
    enabled: bool | None = Field(default=None, strict=True)
    device: int | None = Field(default=None, ge=0, strict=True)
    turn_id: UUID | None = None

    @model_validator(mode="after")
    def check_arguments(self) -> "Command":
        if (self.action == "microphone") != (self.enabled is not None):
            raise ValueError("Microphone commands require enabled")
        if (self.action in {"release", "cancel"}) != (self.turn_id is not None):
            raise ValueError("Release/cancel require turn ownership")
        if self.action != "device" and self.device is not None:
            raise ValueError("Unexpected device")
        return self


class Snapshot(Schema):
    kind: Literal["snapshot"] = "snapshot"
    version: Literal[1] = 1
    sequence: int
    state: AssistantState
    busy: bool
    microphone_enabled: bool
    turn_id: UUID | None
    ready: bool
    device: int | None
    devices: tuple[InputDevice, ...]
    messages: tuple[Message, ...] = Field(repr=False)


class Packet(Schema):
    kind: Literal["ack", "event"]
    id: UUID | None = None
    turn_id: UUID | None = None
    error: str | None = None
    event: Event | None = Field(default=None, repr=False)


class DesktopTransport:
    def __init__(self, runtime: SessionRuntime, token: str, heartbeat_timeout: float = 6) -> None:
        Authentication(version=1, token=token)
        self.runtime = runtime
        self._token = token
        self._owned = False
        self.heartbeat_timeout = heartbeat_timeout

    def snapshot(self) -> Snapshot:
        c = self.runtime.controller
        return Snapshot(
            sequence=c.events.next_sequence - 1,
            state=c.state,
            busy=c.busy,
            microphone_enabled=c.microphone_enabled,
            turn_id=c.turn_id,
            ready=self.runtime.ready,
            device=self.runtime.device,
            devices=self.runtime.devices,
            messages=c.components.history.messages(),
        )

    async def serve(self, socket: WebSocket) -> None:
        if socket.headers.get("origin") not in ORIGINS or socket.query_params:
            await socket.close(code=4403)
            return
        await socket.accept()
        acquired = False
        tasks: list[asyncio.Task[None]] = []
        try:
            async with asyncio.timeout(3):
                raw = await socket.receive_text()
                if len(raw) > 1024:
                    raise ValueError("Oversized authentication")
                authentication = Authentication.model_validate_json(raw)
            if not secrets.compare_digest(authentication.token, self._token):
                await socket.close(code=4401)
                return
            if self._owned:
                await socket.close(code=4409)
                return
            self._owned = acquired = True
            # One sender serializes all writes. A bounded queue applies backpressure to controls.
            acknowledgements: asyncio.Queue[Packet] = asyncio.Queue(maxsize=16)
            controls: asyncio.Queue[Command] = asyncio.Queue(maxsize=8)
            tasks = [
                asyncio.create_task(self._receive(socket, acknowledgements, controls)),
                asyncio.create_task(self._control(controls, acknowledgements)),
                asyncio.create_task(self._send(socket, acknowledgements)),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ValueError, ValidationError, KeyError):
            with suppress(RuntimeError, OSError, WebSocketDisconnect):
                await socket.close(code=4400)
        except TimeoutError:
            with suppress(RuntimeError, OSError, WebSocketDisconnect):
                await socket.close(code=4408)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            # ASGI shutdown may cancel this scope repeatedly. Finish resource cleanup
            # before another window can acquire microphone ownership.
            with CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if acquired:
                    try:
                        await self.runtime.microphone(False)
                    finally:
                        self._owned = False

    async def _receive(
        self, socket: WebSocket, queue: asyncio.Queue[Packet], controls: asyncio.Queue[Command]
    ) -> None:
        recent: deque[float] = deque()
        seen: set[UUID] = set()
        order: deque[UUID] = deque()
        while True:
            async with asyncio.timeout(self.heartbeat_timeout):
                raw = await socket.receive_text()
            now = monotonic()
            while recent and recent[0] < now - 10:
                recent.popleft()
            if len(raw) > 2048 or len(recent) >= 60:
                raise ValueError("Control limit exceeded")
            recent.append(now)
            command = Command.model_validate_json(raw)
            if command.id in seen:
                raise ValueError("Repeated command")
            seen.add(command.id)
            order.append(command.id)
            if len(order) > 256:
                seen.remove(order.popleft())
            async with asyncio.timeout(1):
                if command.action == "ping":
                    await queue.put(Packet(kind="ack", id=command.id))
                else:
                    await controls.put(command)

    async def _control(
        self, controls: asyncio.Queue[Command], queue: asyncio.Queue[Packet]
    ) -> None:
        while True:
            command = await controls.get()
            response = await self._execute(command)
            async with asyncio.timeout(1):
                await queue.put(response)

    async def _execute(self, command: Command) -> Packet:
        c = self.runtime.controller
        turn_id = None
        try:
            if command.action == "prepare":
                await self.runtime.prepare()
            elif command.action == "device":
                self.runtime.select_device(command.device)
            elif command.action == "microphone":
                assert command.enabled is not None
                await self.runtime.microphone(command.enabled)
            elif command.action == "start":
                if not self.runtime.ready:
                    raise ControllerRejected("Load the speech model first")
                turn_id = c.begin_turn()
            elif command.action == "release":
                assert command.turn_id is not None
                c.release(command.turn_id)
            elif command.action == "cancel":
                await c.cancel(command.turn_id)
            elif command.action == "reset":
                c.reset()
        except (ControllerRejected, SpeechError, CaptureError):
            return Packet(
                kind="ack",
                id=command.id,
                error="Control failed. Check devices/model and reset if needed.",
            )
        return Packet(kind="ack", id=command.id, turn_id=turn_id)

    async def _send(self, socket: WebSocket, queue: asyncio.Queue[Packet]) -> None:
        previous = ""
        sequence = self.runtime.controller.events.next_sequence - 1
        while True:
            while not queue.empty():
                packet = queue.get_nowait()
                async with asyncio.timeout(1):
                    await socket.send_text(packet.model_dump_json())
            for event in self.runtime.controller.events.read(sequence):
                async with asyncio.timeout(1):
                    await socket.send_text(Packet(kind="event", event=event).model_dump_json())
                sequence = event.sequence
            snapshot = self.snapshot().model_dump_json()
            if snapshot != previous:
                async with asyncio.timeout(1):
                    await socket.send_text(snapshot)
                previous = snapshot
            await asyncio.sleep(0.025)
