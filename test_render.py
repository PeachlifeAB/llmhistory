
# mock sys.argv if needed
from pathlib import Path

from llmhistory.export_source_runner import (
    _PreparedSession,
    _render_prepared_session_statuses,
    _SessionOutputPaths,
)
from llmhistory.models import SessionExport, SessionRef


def test_run() -> None:
    # 1. Setup a dummy source
    class DummySource:
        def __init__(self) -> None:
            self.source_name = "opencode"
        def get_session_project_name(self, sid) -> str:
            return "SuperProject"

    source = DummySource()

    # 2. Setup an out-of-scope session
    updated_ms = 1711234567000
    sort_key = updated_ms / 1000.0
    base = Path("dummy")
    session = _PreparedSession(
        session_ref=SessionRef(
            sid="ses_child_123",
            session_file=base,
            message_dir=base,
            sort_key=sort_key,
            parent_id="ses_parent_999",
        ),
        exported=SessionExport(
            title="Dummy_Session",
            created_ms=updated_ms,
            updated_ms=updated_ms,
            modified_timestamp=sort_key,
            messages=[]
        ),
        safe_title="Dummy_Session",
        paths=_SessionOutputPaths(
            md_path=base, jsonl_path=base, compactions_path=base
        ),
        is_selected=True,
        should_write=False
    )

    # 3. Call rendering
    lines = _render_prepared_session_statuses(source, [session])
    for _line in lines:
        pass

if __name__ == "__main__":
    test_run()
