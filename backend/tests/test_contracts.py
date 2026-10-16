from uuid import uuid4

import pytest
from pydantic import ValidationError
from voice_assistant.contracts import AudioBuffer, Message
from voice_assistant.events import Event, EventBuffer
from voice_assistant.state import AssistantState as State
from voice_assistant.state import InvalidTransition, StateMachine
from voice_assistant.storage import MemoryConversation


def test_full_state_path_and_recovery() -> None:
    machine = StateMachine()
    for state in (
        State.LISTENING,
        State.TRANSCRIBING,
        State.THINKING,
        State.ACTING,
        State.THINKING,
        State.SPEAKING,
        State.ERROR,
        State.IDLE,
    ):
        machine.transition(state)
        assert machine.state == state


@pytest.mark.parametrize("target", [State.SPEAKING, State.THINKING, State.IDLE])
def test_rejects_invalid_transition_without_changing_state(target: State) -> None:
    machine = StateMachine()
    with pytest.raises(InvalidTransition):
        machine.transition(target)
    assert machine.state == State.IDLE


@pytest.mark.parametrize("pcm,rate", [(b"", 16000), (b"x", 16000), (b"xx", 0)])
def test_audio_validation(pcm: bytes, rate: int) -> None:
    with pytest.raises(ValidationError):
        AudioBuffer(pcm=pcm, sample_rate=rate)


def test_audio_is_not_serialized_or_represented() -> None:
    audio = AudioBuffer(pcm=b"private audio!", sample_rate=16000)
    assert "private" not in repr(audio)
    assert audio.model_dump() == {"sample_rate": 16000}


def test_events_validate_payload_and_round_trip() -> None:
    event = Event(sequence=1, turn_id=uuid4(), kind="state", state=State.LISTENING)
    assert Event.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError):
        Event(sequence=1, turn_id=None, kind="finished", outcome="completed")
    with pytest.raises(ValidationError):
        Event(sequence=1, turn_id=None, kind="state", microphone_enabled=False)
    with pytest.raises(ValidationError):
        Event(sequence=1, turn_id=None, kind="state", state=State.IDLE, outcome="failed")


def test_event_buffer_bounds_memory_and_preserves_sequence() -> None:
    events = EventBuffer(capacity=2)
    for sequence in range(1, 4):
        events.append(Event(sequence=sequence, turn_id=None, kind="state", state=State.IDLE))
    assert [event.sequence for event in events.read()] == [2, 3]
    assert [event.sequence for event in events.read(after=2)] == [3]
    with pytest.raises(ValueError):
        events.append(Event(sequence=5, turn_id=None, kind="state", state=State.IDLE))


def test_history_is_bounded_and_clearable() -> None:
    history = MemoryConversation(capacity=2)
    for text in ("one", "two", "three"):
        history.append(Message(role="user", content=text))
    assert [message.content for message in history.messages()] == ["two", "three"]
    history.clear()
    assert history.messages() == ()
    with pytest.raises(ValidationError):
        Message(role="user", content=" ")
