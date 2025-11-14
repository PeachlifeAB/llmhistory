"""Tests for core immutable model normalization."""

from llmhistory.models import Message, SessionExport


def test_message_normalizes_tool_calls_to_tuple() -> None:
    """Normalize incoming tool-call lists to an immutable tuple."""
    message = Message(
        mid="msg_1",
        role="assistant",
        created_ms=1,
        parent_id=None,
        agent=None,
        mode=None,
        summary=False,
        content="hello",
        tool_calls=[{"id": "tool_1"}],
    )

    assert isinstance(message.tool_calls, tuple)
    assert message.tool_calls == ({"id": "tool_1"},)


def test_session_export_normalizes_messages_to_tuple() -> None:
    """Normalize incoming message lists to an immutable tuple."""
    message = Message(
        mid="msg_1",
        role="assistant",
        created_ms=1,
        parent_id=None,
        agent=None,
        mode=None,
        summary=False,
        content="hello",
        tool_calls=[],
    )
    session = SessionExport(
        title="Demo",
        created_ms=1,
        updated_ms=2,
        modified_timestamp=3.0,
        messages=[message],
    )

    assert isinstance(session.messages, tuple)
    assert session.messages == (message,)
