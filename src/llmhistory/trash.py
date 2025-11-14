"""Move sessions and orphaned artifacts into the system trash."""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

from llmhistory.utils import eprint


def get_trash_dir() -> Path:
    """Return the supported system trash directory for the current platform."""
    if sys.platform == "darwin":
        return Path.home() / ".Trash"
    if sys.platform.startswith("linux"):
        return Path.home() / ".local/share/Trash"
    if sys.platform.startswith("win"):
        message = "Windows trash is not supported without a Recycle Bin integration"
        raise NotImplementedError(message)
    message = f"Unsupported trash platform: {sys.platform}"
    raise NotImplementedError(message)


def _unique_dest(base_dir: Path, name: str) -> Path:
    dest = base_dir / name
    if not dest.exists():
        return dest
    index = 1
    while True:
        candidate = base_dir / f"{name} ({index})"
        if not candidate.exists():
            return candidate
        index += 1


def _safe_move(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    current_dest = dest
    for _ in range(3):
        try:
            shutil.move(str(src), str(current_dest))
        except FileExistsError:
            current_dest = _unique_dest(dest.parent, dest.name)
        except (OSError, shutil.Error) as exc:
            eprint(f"warning: failed to move {src} to trash: {exc}")
            return False
        else:
            return True
    eprint(f"warning: failed to move {src} to trash after collision retries")
    return False


def _collect_valid_message_ids(message_root: Path) -> set[str]:
    valid_message_ids: set[str] = set()
    if not message_root.is_dir():
        return valid_message_ids
    for session_dir in message_root.iterdir():
        if not session_dir.is_dir():
            continue
        for message_file in session_dir.glob("msg_*.json"):
            message_id = message_file.stem.removeprefix("msg_")
            if message_id:
                valid_message_ids.add(message_id)
    return valid_message_ids


def _iter_orphan_part_dirs(part_root: Path, valid_message_ids: set[str]) -> list[Path]:
    orphan_dirs: list[Path] = []
    for part_dir in part_root.iterdir():
        if not part_dir.is_dir() or not part_dir.name.startswith("msg_"):
            continue
        message_id = part_dir.name.removeprefix("msg_")
        if message_id in valid_message_ids:
            continue
        orphan_dirs.append(part_dir)
    return orphan_dirs


def trash_orphan_parts(storage: Path, *, dry_run: bool = False) -> int:
    """Trash part directories that do not map to any existing message."""
    part_root = storage / "part"
    message_root = storage / "message"

    if not part_root.is_dir():
        return 0

    valid_message_ids = _collect_valid_message_ids(message_root)
    orphan_part_dirs = _iter_orphan_part_dirs(part_root, valid_message_ids)

    trash_root = get_trash_dir()

    for part_dir in orphan_part_dirs:
        if dry_run:
            continue

        destination = _unique_dest(trash_root, f"opencode-orphan-{part_dir.name}")
        _safe_move(part_dir, destination)

    return len(orphan_part_dirs)


def trash_session(
    storage: Path,
    project_id: str,
    session_id: str,
) -> bool:
    """Move a session and its message/part artifacts into a trash bundle."""
    raw_id = session_id.removeprefix("ses_")

    trash_root = get_trash_dir()
    trash_root.mkdir(parents=True, exist_ok=True)
    bundle_name = f"opencode-session-{project_id}-{raw_id}"
    bundle_dest = _unique_dest(trash_root, bundle_name)
    bundle_dest.mkdir(parents=True, exist_ok=True)

    session_file = storage / "session" / project_id / f"ses_{raw_id}.json"
    message_dir = storage / "message" / f"ses_{raw_id}"
    part_root = storage / "part"

    moved_any = False
    if session_file.exists():
        moved_any |= _safe_move(session_file, bundle_dest / "session.json")

    message_ids: set[str] = set()
    if message_dir.exists():
        for message_file in message_dir.glob("msg_*.json"):
            message_id = message_file.stem.removeprefix("msg_")
            if message_id:
                message_ids.add(message_id)
        moved_any |= _safe_move(message_dir, bundle_dest / "messages")

    for message_id in sorted(message_ids):
        parts_dir = part_root / f"msg_{message_id}"
        if parts_dir.exists():
            moved_any |= _safe_move(
                parts_dir,
                bundle_dest / "parts" / f"msg_{message_id}",
            )

    if moved_any:
        return True

    # No files found — try deleting from the SQLite DB directly.
    # Schema uses ON DELETE CASCADE: deleting session row cascades to
    # message, part, todo, session_share automatically.
    db_deleted = _delete_session_from_db(storage, session_id)

    try:
        if bundle_dest.exists() and not any(bundle_dest.iterdir()):
            bundle_dest.rmdir()
    except OSError:
        pass
    return db_deleted


def _delete_session_from_db(storage: Path, session_id: str) -> bool:
    db_path = storage.parent / "opencode.db"
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute("DELETE FROM session WHERE id = ?", (session_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        eprint(f"warning: failed to delete session {session_id} from DB: {exc}")
        return False
