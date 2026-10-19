"""One-turn asynchronous orchestration, with bounded waits and safe failures."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, TypeVar, cast
from uuid import UUID, uuid4

from pydantic import Field

from voice_assistant.contracts import (
    Capture,
    ContextLimitExceeded,
    ConversationStore,
    InvalidModelResponse,
    LanguageModel,
    Message,
    Playback,
    Schema,
    Synthesizer,
    Transcriber,
    VoiceActivityDetector,
)
from voice_assistant.events import ErrorCode, Event, EventBuffer, Failure
from voice_assistant.state import AssistantState as State
from voice_assistant.state import StateMachine

logger = logging.getLogger(__name__)
T = TypeVar("T")
Outcome = Literal["completed", "cancelled", "no_speech", "failed"]


class Deadlines(Schema):
    capture_start: float = Field(default=5, gt=0, le=120, allow_inf_nan=False)
    recording: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    capture_finish: float = Field(default=5, gt=0, le=120, allow_inf_nan=False)
    transcription: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    generation: float = Field(default=60, gt=0, le=120, allow_inf_nan=False)
    synthesis: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    playback: float = Field(default=120, gt=0, le=120, allow_inf_nan=False)
    cleanup: float = Field(default=2, gt=0, le=30, allow_inf_nan=False)


@dataclass(frozen=True)
class TranscriptionComponents:
    capture: Capture
    vad: VoiceActivityDetector
    stt: Transcriber
    history: ConversationStore


@dataclass(frozen=True)
class ConversationComponents(TranscriptionComponents):
    llm: LanguageModel


@dataclass(frozen=True)
class Components(ConversationComponents):
    tts: Synthesizer
    playback: Playback


class ControllerRejected(RuntimeError):
    """An invalid/busy/privacy-denied control; never includes user content."""


class _Cancelled(Exception):
    pass


class _NoSpeech(Exception):
    pass


class _StageFailed(Exception):
    def __init__(self, failure: Failure) -> None:
        self.failure = failure


_MESSAGES = {
    ErrorCode.CAPTURE_FAILED: "Microphone capture failed. Check the selected device.",
    ErrorCode.STT_UNAVAILABLE: "Speech recognition is unavailable. Check the local model.",
    ErrorCode.LLM_UNAVAILABLE: "The language model is unavailable. Check llama.cpp.",
    ErrorCode.TTS_UNAVAILABLE: "Speech synthesis is unavailable. Check Piper and the voice.",
    ErrorCode.PLAYBACK_FAILED: "Audio playback failed. Check the selected output device.",
    ErrorCode.INVALID_RESPONSE: "Incomplete or invalid model response. Try a shorter question.",
    ErrorCode.CONTEXT_TOO_LONG: "The request exceeds the model context. Try a shorter question.",
    ErrorCode.DEADLINE_EXCEEDED: "This step took too long. Try again when it has stopped.",
    ErrorCode.CLEANUP_FAILED: "Audio resources could not be released. Restart the backend.",
    ErrorCode.INTERNAL_ERROR: "The turn failed. Reset the assistant and try again.",
}


class Controller:
    """Control methods and adapter callbacks run on the same asyncio event loop.

    begin_turn reserves the slot synchronously. Capture/playback callbacks must
    obey the contracts; CPU work belongs in adapter-owned workers. Outstanding
    tasks that ignore cancellation quarantine the controller until they finish.
    """

    def __init__(
        self, components: TranscriptionComponents, deadlines: Deadlines | None = None
    ) -> None:
        self.components = components
        self.deadlines = deadlines or Deadlines()
        self.events = EventBuffer()
        self._machine = StateMachine()
        self._microphone_enabled = False
        self._turn_id: UUID | None = None
        self._task: asyncio.Task[None] | None = None
        self._pending: set[asyncio.Task[object]] = set()
        self._resource_tasks: set[asyncio.Task[object]] = set()
        self._cancel = asyncio.Event()
        self._released = asyncio.Event()
        self._closed = False
        self._cleanup_failed = False
        self._draft = ""
        self.preparing_speech = False

    @property
    def draft(self) -> str:
        return self._draft

    @property
    def state(self) -> State:
        return self._machine.state

    @property
    def microphone_enabled(self) -> bool:
        return self._microphone_enabled

    @property
    def busy(self) -> bool:
        return bool(self._pending) or (self._task is not None and not self._task.done())

    @property
    def turn_id(self) -> UUID | None:
        return self._turn_id

    def _state(self, state: State) -> None:
        self._machine.transition(state)
        self.events.append(
            Event(
                sequence=self.events.next_sequence, turn_id=self._turn_id, kind="state", state=state
            )
        )

    def _message(self, message: Message) -> None:
        self.components.history.append(message)
        self.events.append(
            Event(
                sequence=self.events.next_sequence,
                turn_id=self._turn_id,
                kind="message",
                message=message,
            )
        )

    def _error(self, failure: Failure) -> None:
        if self.state != State.ERROR:
            self._state(State.ERROR)
        self.events.append(
            Event(
                sequence=self.events.next_sequence,
                turn_id=self._turn_id,
                kind="error",
                failure=failure,
            )
        )
        logger.warning("voice_turn_failed", extra={"error_code": failure.code.value})

    async def set_microphone(self, enabled: bool) -> None:
        if self._closed:
            raise ControllerRejected("Controller is closed")
        self._microphone_enabled = enabled
        self.events.append(
            Event(
                sequence=self.events.next_sequence,
                turn_id=self._turn_id,
                kind="microphone",
                microphone_enabled=enabled,
            )
        )
        if not enabled:
            await self.cancel()

    def begin_turn(self) -> UUID:
        if self._closed or self.busy or self.state != State.IDLE:
            raise ControllerRejected("Assistant is not ready for another turn")
        if not self._microphone_enabled:
            raise ControllerRejected("Microphone is off")
        self._turn_id = uuid4()
        self._cancel = asyncio.Event()
        self._released = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="voice-turn")
        return self._turn_id

    def release(self, turn_id: UUID) -> None:
        # Duplicate releases are harmless; releases for older turns cannot affect this one.
        if turn_id == self._turn_id and self._task is not None and not self._task.done():
            self._released.set()

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)

    async def cancel(self, turn_id: UUID | None = None) -> None:
        if turn_id is not None and turn_id != self._turn_id:
            return
        self._cancel.set()
        await self.wait()

    def reset(self) -> None:
        if self._closed or self.busy or self._cleanup_failed:
            raise ControllerRejected("Resources are still active or require a backend restart")
        if self.state == State.ERROR:
            self._state(State.IDLE)

    async def close(self) -> None:
        if not self._closed:
            await self.set_microphone(False)
            self._closed = True

    def _track(self, task: asyncio.Task[object], code: ErrorCode) -> None:
        self._pending.add(task)
        if code in {
            ErrorCode.CAPTURE_FAILED,
            ErrorCode.PLAYBACK_FAILED,
            ErrorCode.CLEANUP_FAILED,
        }:
            self._resource_tasks.add(task)

        def completed(finished: asyncio.Task[object]) -> None:
            self._pending.discard(finished)
            self._resource_tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()  # Consume late failures without logging sensitive details.

        task.add_done_callback(completed)

    async def _perform(
        self,
        operation: Callable[[], Awaitable[T]],
        seconds: float,
        code: ErrorCode,
        *,
        cleanup: bool = False,
    ) -> T:
        async def invoke() -> object:
            return await operation()

        task = asyncio.create_task(invoke())
        self._track(task, code)
        cancellation = asyncio.create_task(self._cancel.wait())
        try:
            if not cleanup and self._cancel.is_set():
                task.cancel()
                raise _Cancelled
            candidates = {task} if cleanup else {task, cancellation}
            done, _ = await asyncio.wait(
                candidates, timeout=seconds, return_when=asyncio.FIRST_COMPLETED
            )
            if not cleanup and self._cancel.is_set():
                task.cancel()
                raise _Cancelled
            if task not in done:
                task.cancel()
                failure_code = code if cleanup else ErrorCode.DEADLINE_EXCEEDED
                raise _StageFailed(Failure(code=failure_code, message=_MESSAGES[failure_code]))
            try:
                return cast(T, task.result())
            except ContextLimitExceeded:
                error_code = ErrorCode.CONTEXT_TOO_LONG
                raise _StageFailed(
                    Failure(code=error_code, message=_MESSAGES[error_code])
                ) from None
            except InvalidModelResponse:
                error_code = ErrorCode.INVALID_RESPONSE
                raise _StageFailed(
                    Failure(code=error_code, message=_MESSAGES[error_code])
                ) from None
            except asyncio.CancelledError:
                raise _StageFailed(Failure(code=code, message=_MESSAGES[code])) from None
            except Exception:
                raise _StageFailed(Failure(code=code, message=_MESSAGES[code])) from None
        finally:
            cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)
            if not task.done() and not task.cancelling():
                task.cancel()

    async def _pipeline(self) -> None:
        c, d = self.components, self.deadlines
        await self._perform(c.capture.start, d.capture_start, ErrorCode.CAPTURE_FAILED)
        self._state(State.LISTENING)
        await self._perform(self._released.wait, d.recording, ErrorCode.CAPTURE_FAILED)
        audio = await self._perform(c.capture.finish, d.capture_finish, ErrorCode.CAPTURE_FAILED)
        if audio.duration > d.recording:
            raise _StageFailed(
                Failure(code=ErrorCode.CAPTURE_FAILED, message=_MESSAGES[ErrorCode.CAPTURE_FAILED])
            )
        self._state(State.TRANSCRIBING)
        speech = await self._perform(
            lambda: c.vad.has_speech(audio), d.transcription, ErrorCode.STT_UNAVAILABLE
        )
        if not speech:
            raise _NoSpeech
        text = await self._perform(
            lambda: c.stt.transcribe(audio), d.transcription, ErrorCode.STT_UNAVAILABLE
        )
        if not text.strip():
            raise _NoSpeech
        self._message(Message(role="user", content=text.strip()))
        if not isinstance(c, ConversationComponents):
            return
        self._state(State.THINKING)
        turn_id = self._turn_id

        def on_delta(delta: str) -> None:
            if turn_id != self._turn_id or self._cancel.is_set() or self.state != State.THINKING:
                return
            if len(self._draft) + len(delta) > 8192:
                raise InvalidModelResponse()
            self._draft += delta

        answer = await self._perform(
            lambda: c.llm.respond(c.history.messages(), on_delta),
            d.generation,
            ErrorCode.LLM_UNAVAILABLE,
        )
        if not answer.strip() or len(answer) > 8192 or "<think>" in answer or "</think>" in answer:
            raise _StageFailed(
                Failure(
                    code=ErrorCode.INVALID_RESPONSE, message=_MESSAGES[ErrorCode.INVALID_RESPONSE]
                )
            )
        self._message(Message(role="assistant", content=answer.strip()))
        self._draft = ""
        if not isinstance(c, Components):
            return
        self.preparing_speech = True
        spoken = await self._perform(
            lambda: c.tts.synthesize(answer.strip()), d.synthesis, ErrorCode.TTS_UNAVAILABLE
        )
        turn_id = self._turn_id

        def on_started() -> None:
            if (
                turn_id == self._turn_id
                and not self._cancel.is_set()
                and self.state == State.THINKING
            ):
                self.preparing_speech = False
                self._state(State.SPEAKING)

        await self._perform(
            lambda: c.playback.play(spoken, on_started), d.playback, ErrorCode.PLAYBACK_FAILED
        )

    async def _run(self) -> None:
        outcome: Outcome = "completed"
        try:
            await self._pipeline()
        except _Cancelled:
            outcome = "cancelled"
        except _NoSpeech:
            outcome = "no_speech"
        except _StageFailed as error:
            outcome = "failed"
            self._error(error.failure)
        except Exception:
            outcome = "failed"
            self._error(
                Failure(code=ErrorCode.INTERNAL_ERROR, message=_MESSAGES[ErrorCode.INTERNAL_ERROR])
            )
        finally:
            self.preparing_speech = False
            self._draft = ""
            # Also invalidate a playback callback retained by a misbehaving adapter.
            self._cancel.set()
            cleanup = [self.components.capture.abort]
            if isinstance(self.components, Components):
                cleanup.append(self.components.playback.stop)
            for operation in cleanup:
                try:
                    await self._perform(
                        operation, self.deadlines.cleanup, ErrorCode.CLEANUP_FAILED, cleanup=True
                    )
                except _StageFailed as error:
                    self._cleanup_failed = True
                    outcome = "failed"
                    self._error(error.failure)
            # Native inference cancellation can also need time to reap its worker.
            pending = {task for task in self._pending if not task.done()}
            if pending:
                await asyncio.wait(pending, timeout=self.deadlines.cleanup)
            # Give cooperative cancellation the bounded cleanup window to finish.
            # A resource operation still running after abort/stop could reopen a device.
            resources_active = any(not task.done() for task in self._resource_tasks)
            if resources_active:
                self._cleanup_failed = True
            if resources_active or (self._pending and outcome != "failed"):
                outcome = "failed"
                self._error(
                    Failure(
                        code=ErrorCode.CLEANUP_FAILED, message=_MESSAGES[ErrorCode.CLEANUP_FAILED]
                    )
                )
            if self.state not in {State.ERROR, State.IDLE}:
                self._state(State.IDLE)
            self.events.append(
                Event(
                    sequence=self.events.next_sequence,
                    turn_id=self._turn_id,
                    kind="finished",
                    outcome=outcome,
                )
            )
