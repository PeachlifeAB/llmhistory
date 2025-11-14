"""Message file parsing and metadata extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from llmhistory.storage_index import read_json

if TYPE_CHECKING:
    from pathlib import Path


def _format_model_ref(provider_id: str | None, model_id: str | None) -> str | None:
    """Format model reference for display. Returns None if neither field is present."""
    if provider_id and model_id:
        return f"{provider_id}/{model_id}"
    return model_id or provider_id


def _parse_summary_flag(value: object) -> bool:
    """Parse summary flag from message data."""
    return bool(value)


def _parse_model_fields(data: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract provider_id and model_id from message data.

    Handles two schemas:
    - User messages: data["model"]["providerID"], data["model"]["modelID"]
    - Assistant messages: data["providerID"], data["modelID"]
    """
    provider = data.get("providerID")
    model = data.get("modelID")

    m = data.get("model")
    if isinstance(m, dict):
        provider = provider or m.get("providerID")
        model = model or m.get("modelID")

    provider_s = str(provider) if provider is not None else None
    model_s = str(model) if model is not None else None
    return provider_s, model_s


def parse_message_file(
    msg_file: Path,
) -> (
    tuple[
        str,
        str,
        int,
        str | None,
        str | None,
        str | None,
        bool,
        str | None,
        str | None,
    ]
    | None
):
    """Parse message file and return metadata tuple."""
    data = read_json(msg_file)
    if not data:
        return None

    role = data.get("role")
    if role not in ("user", "assistant"):
        return None

    created_ms = int((data.get("time") or {}).get("created") or 0)
    mid = str(data.get("id") or msg_file.stem)

    parent = data.get("parentID")
    # Some stored message JSONs use the literal string "null" for parentID instead
    # of a proper JSON null; treat both as "no parent".
    parent_id = None if parent in (None, "null") else str(parent)

    agent = data.get("agent")
    agent_str = str(agent) if agent is not None else None

    mode = data.get("mode")
    mode_str = str(mode) if mode is not None else None

    summary_flag = _parse_summary_flag(data.get("summary"))

    provider_id, model_id = _parse_model_fields(data)

    return (
        mid,
        str(role),
        created_ms,
        parent_id,
        agent_str,
        mode_str,
        summary_flag,
        provider_id,
        model_id,
    )
