"""
collect_all_sessions(), is_empty(), is_orphan(), session_title().

Synthetic fixtures only, built in temp dirs -- never touch real
~/Library/Application Support/Code data (same policy as zazzle's tests/).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import vc


def make_workspace(storage_root: Path, workspace_hash: str, real_project_dir: Path | None):
    ws_dir = storage_root / workspace_hash
    ws_dir.mkdir(parents=True)
    if real_project_dir is not None:
        uri = f"file://{real_project_dir}"
        (ws_dir / "workspace.json").write_text(
            json.dumps({"workspace": uri}), encoding="utf-8"
        )
    (ws_dir / "chatSessions").mkdir()
    return ws_dir


def write_flat_session(ws_dir: Path, session_id: str, **fields):
    data = {
        "sessionId": session_id,
        "requesterUsername": "me",
        "customTitle": None,
        "requests": [],
        **fields,
    }
    (ws_dir / "chatSessions" / f"{session_id}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


class CollectAllSessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vscode_root = Path(self.tmp.name)
        self.storage_root = self.vscode_root / "workspaceStorage"
        self.storage_root.mkdir()

    def test_no_workspace_storage_dir_returns_empty_list(self):
        empty_root = Path(self.tmp.name) / "nope"
        self.assertEqual(vc.collect_all_sessions(empty_root), [])

    def test_finds_a_flat_json_session(self):
        real_project = Path(self.tmp.name) / "myproject"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash1", real_project)
        write_flat_session(ws_dir, "sess-1", customTitle="My Chat")

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertEqual(s["session_id"], "sess-1")
        self.assertEqual(s["title"], "My Chat")
        self.assertTrue(s["title_from_index"])
        self.assertEqual(s["format"], "json")
        self.assertTrue(s["project_exists"])
        self.assertFalse(s["is_orphan"])

    def test_project_path_that_no_longer_exists_is_flagged_orphan(self):
        ws_dir = make_workspace(self.storage_root, "hash2", Path("/nonexistent/gone/project"))
        write_flat_session(ws_dir, "sess-2")

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["is_orphan"])
        self.assertFalse(sessions[0]["project_exists"])

    def test_missing_workspace_json_still_surfaces_the_session_as_orphan(self):
        ws_dir = make_workspace(self.storage_root, "hash3", None)
        write_flat_session(ws_dir, "sess-3")

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["is_orphan"])

    def test_title_falls_back_to_first_user_message_when_no_custom_title(self):
        real_project = Path(self.tmp.name) / "p2"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash4", real_project)
        write_flat_session(ws_dir, "sess-4", customTitle=None, requests=[
            {"requestId": "r1", "message": {"text": "help me debug this"}, "response": [], "timestamp": 1},
        ])

        sessions = vc.collect_all_sessions(self.vscode_root)
        s = sessions[0]
        self.assertEqual(s["title"], "help me debug this")
        self.assertFalse(s["title_from_index"])
        self.assertEqual(s["turn_count"], 1)

    def test_title_never_falls_back_to_a_raw_session_id(self):
        # A bare hash reads as noise in a list -- fall back to a
        # human-readable placeholder instead. The id is still available
        # via session_id / the TUI detail line.
        real_project = Path(self.tmp.name) / "p3"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash5", real_project)
        write_flat_session(ws_dir, "sess-5", customTitle=None, requests=[])

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(sessions[0]["title"], "(empty chat)")

    def test_title_falls_back_to_a_turn_count_placeholder_when_turns_exist_but_no_text(self):
        real_project = Path(self.tmp.name) / "p3b"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash5b", real_project)
        write_flat_session(ws_dir, "sess-5b", customTitle=None, requests=[
            {"requestId": "r1", "message": {"text": ""}, "response": [], "timestamp": 1},
        ])

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(sessions[0]["title"], "(untitled, 1 turn)")

    def test_jsonl_sessions_are_discovered_and_marked_with_that_format(self):
        real_project = Path(self.tmp.name) / "p4"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash6", real_project)
        (ws_dir / "chatSessions" / "sess-6.jsonl").write_text(
            json.dumps({"kind": 0, "v": {"customTitle": "jsonl chat", "requests": []}}) + "\n",
            encoding="utf-8",
        )

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["format"], "jsonl")
        self.assertEqual(sessions[0]["title"], "jsonl chat")

    def test_both_formats_can_coexist_in_the_same_workspace(self):
        real_project = Path(self.tmp.name) / "p5"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash7", real_project)
        write_flat_session(ws_dir, "sess-flat")
        (ws_dir / "chatSessions" / "sess-jsonl.jsonl").write_text(
            json.dumps({"kind": 0, "v": {"requests": []}}) + "\n", encoding="utf-8"
        )

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(len(sessions), 2)
        formats = {s["session_id"]: s["format"] for s in sessions}
        self.assertEqual(formats["sess-flat"], "json")
        self.assertEqual(formats["sess-jsonl"], "jsonl")

    def test_editing_dir_is_attached_when_present(self):
        real_project = Path(self.tmp.name) / "p6"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash8", real_project)
        write_flat_session(ws_dir, "sess-7")
        editing_dir = ws_dir / "chatEditingSessions" / "sess-7"
        editing_dir.mkdir(parents=True)

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(sessions[0]["editing_dir"], editing_dir)

    def test_editing_dir_is_none_when_absent(self):
        real_project = Path(self.tmp.name) / "p7"
        real_project.mkdir()
        ws_dir = make_workspace(self.storage_root, "hash9", real_project)
        write_flat_session(ws_dir, "sess-8")

        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertIsNone(sessions[0]["editing_dir"])

    def test_workspace_dir_without_chat_sessions_subdir_is_skipped(self):
        ws_dir = self.storage_root / "hash10"
        ws_dir.mkdir()
        (ws_dir / "workspace.json").write_text(
            json.dumps({"workspace": "file:///tmp/x"}), encoding="utf-8"
        )
        sessions = vc.collect_all_sessions(self.vscode_root)
        self.assertEqual(sessions, [])


class IsEmptyIsOrphanTests(unittest.TestCase):
    def test_is_empty_true_when_zero_turns(self):
        self.assertTrue(vc.is_empty({"turn_count": 0}))

    def test_is_empty_false_when_turns_present(self):
        self.assertFalse(vc.is_empty({"turn_count": 3}))

    def test_is_orphan_reflects_the_flag(self):
        self.assertTrue(vc.is_orphan({"is_orphan": True}))
        self.assertFalse(vc.is_orphan({"is_orphan": False}))


if __name__ == "__main__":
    unittest.main()
