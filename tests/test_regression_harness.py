#!/usr/bin/env python3
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dpx_claude_Cleaner as cleaner  # noqa: E402


class SessionLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()

    def _project_dir(self, cwd: str) -> Path:
        project_dir = self.root / "projects" / cleaner.encode_path(Path(cwd))
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )

    def _write_index(self, project_dir: Path, entries: list[dict]) -> None:
        (project_dir / cleaner.INDEX_FILE).write_text(
            json.dumps(entries), encoding="utf-8"
        )

    def test_get_session_title_prefers_latest_custom_title(self) -> None:
        project_dir = self._project_dir("/tmp/proj")
        jsonl = project_dir / "session-1.jsonl"
        self._write_jsonl(
            jsonl,
            [
                {"type": "summary", "summary": "summary title"},
                {"type": "custom-title", "customTitle": "older custom"},
                {"type": "custom-title", "customTitle": "newest custom"},
            ],
        )

        title, authoritative = cleaner.get_session_title_from_jsonl(jsonl)
        self.assertEqual(title, "newest custom")
        self.assertTrue(authoritative)

    def test_get_session_title_fallbacks(self) -> None:
        project_dir = self._project_dir("/tmp/proj")

        with_summary = project_dir / "session-2.jsonl"
        self._write_jsonl(
            with_summary,
            [{"type": "summary", "summary": "summary title"}],
        )
        self.assertEqual(
            cleaner.get_session_title_from_jsonl(with_summary),
            ("summary title", True),
        )

        with_user = project_dir / "session-3.jsonl"
        self._write_jsonl(
            with_user,
            [{"type": "user", "message": {"content": "hello world"}}],
        )
        self.assertEqual(
            cleaner.get_session_title_from_jsonl(with_user),
            ("hello world", False),
        )

        empty = project_dir / "session-4.jsonl"
        self._write_jsonl(empty, [])
        self.assertEqual(
            cleaner.get_session_title_from_jsonl(empty),
            ("session-4", False),
        )

    def test_extract_message_text_shapes(self) -> None:
        self.assertEqual(cleaner._extract_message_text("hello"), "hello")
        self.assertIsNone(cleaner._extract_message_text("   "))
        self.assertEqual(
            cleaner._extract_message_text(
                [
                    {"type": "tool_use", "name": "x"},
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ]
            ),
            "hello world",
        )
        self.assertIsNone(
            cleaner._extract_message_text([{"type": "tool_use", "name": "x"}])
        )
        self.assertIsNone(cleaner._extract_message_text({"type": "text"}))

    def test_get_project_cwd_from_jsonl(self) -> None:
        project_dir = self._project_dir("/tmp/proj")
        jsonl = project_dir / "session-cwd.jsonl"
        self._write_jsonl(
            jsonl,
            [
                {"type": "summary", "summary": "title"},
                {"type": "user", "cwd": "/real/path", "message": {"content": "hi"}},
            ],
        )
        self.assertEqual(cleaner.get_project_cwd_from_jsonl(jsonl), "/real/path")

        no_cwd = project_dir / "session-no-cwd.jsonl"
        self._write_jsonl(no_cwd, [{"type": "assistant", "message": {"content": "x"}}])
        self.assertIsNone(cleaner.get_project_cwd_from_jsonl(no_cwd))

    def test_encode_decode_known_lossy_case(self) -> None:
        original = Path("/Users/demo/my-project")
        encoded = cleaner.encode_path(original)
        decoded = cleaner.decode_encoded(encoded)
        self.assertEqual(encoded, "-Users-demo-my-project")
        self.assertEqual(decoded, "/Users/demo/my/project")

    def test_rename_session_updates_index_and_replaces_summary(self) -> None:
        project_dir = self._project_dir("/tmp/proj")
        sid = "session-rename"
        jsonl = project_dir / f"{sid}.jsonl"
        self._write_jsonl(
            jsonl,
            [
                {"type": "summary", "summary": "old", "leafUuid": sid},
                {"type": "user", "message": {"content": "hello"}},
            ],
        )
        self._write_index(
            project_dir,
            [
                {
                    "sessionId": sid,
                    "fullPath": str(jsonl),
                    "summary": "old",
                    "messageCount": 1,
                    "fileMtime": 0,
                    "created": "2026-01-01T00:00:00.000Z",
                }
            ],
        )
        session = {
            "session_id": sid,
            "project_dir": project_dir,
            "path": jsonl,
            "file_exists": True,
            "in_index": True,
            "title": "old",
            "title_from_index": True,
        }

        err = cleaner.rename_session(session, "new title", self.root)
        self.assertIsNone(err)
        entries = cleaner.read_index(project_dir / cleaner.INDEX_FILE)
        self.assertEqual(entries[0]["summary"], "new title")
        first_line = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(first_line["type"], "summary")
        self.assertEqual(first_line["summary"], "new title")

    def test_rename_session_injects_summary_when_missing(self) -> None:
        project_dir = self._project_dir("/tmp/proj")
        sid = "session-inject"
        jsonl = project_dir / f"{sid}.jsonl"
        self._write_jsonl(jsonl, [{"type": "user", "message": {"content": "hello"}}])
        session = {
            "session_id": sid,
            "project_dir": project_dir,
            "path": jsonl,
            "file_exists": True,
            "in_index": False,
            "title": "old",
            "title_from_index": False,
        }

        err = cleaner.rename_session(session, "inserted title", self.root)
        self.assertIsNone(err)
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["summary"], "inserted title")

    def test_delete_sessions_success_and_unlink_failure(self) -> None:
        project_dir = self._project_dir("/tmp/proj")
        sid = "session-delete"
        jsonl = project_dir / f"{sid}.jsonl"
        self._write_jsonl(jsonl, [{"type": "user", "message": {"content": "x"}}])
        self._write_index(project_dir, [{"sessionId": sid, "fullPath": str(jsonl)}])
        session = {
            "session_id": sid,
            "project_dir": project_dir,
            "path": jsonl,
            "file_exists": True,
        }
        deleted, errors = cleaner.delete_sessions([session], self.root)
        self.assertEqual(deleted, 1)
        self.assertEqual(errors, [])
        self.assertFalse(jsonl.exists())
        self.assertEqual(cleaner.read_index(project_dir / cleaner.INDEX_FILE), [])

        sid2 = "session-fail"
        jsonl2 = project_dir / f"{sid2}.jsonl"
        self._write_jsonl(jsonl2, [{"type": "user", "message": {"content": "x"}}])
        self._write_index(project_dir, [{"sessionId": sid2, "fullPath": str(jsonl2)}])
        failing = {
            "session_id": sid2,
            "project_dir": project_dir,
            "path": jsonl2,
            "file_exists": True,
        }
        with mock.patch.object(Path, "unlink", side_effect=OSError("blocked")):
            deleted2, errors2 = cleaner.delete_sessions([failing], self.root)
        self.assertEqual(deleted2, 0)
        self.assertEqual(len(errors2), 1)
        self.assertIn("blocked", errors2[0])

    def test_collect_all_sessions_merges_dedups_and_flags(self) -> None:
        project_dir = self._project_dir("/tmp/proj")
        sid_indexed = "sid-indexed"
        sid_orphan = "sid-orphan"
        sid_unindexed = "sid-unindexed"

        indexed_file = project_dir / f"{sid_indexed}.jsonl"
        self._write_jsonl(
            indexed_file,
            [{"type": "user", "cwd": "/tmp/proj", "message": {"content": "hi"}}],
        )
        unindexed_file = project_dir / f"{sid_unindexed}.jsonl"
        self._write_jsonl(
            unindexed_file,
            [{"type": "user", "cwd": "/tmp/proj", "message": {"content": "new"}}],
        )
        self._write_index(
            project_dir,
            [
                {
                    "sessionId": sid_indexed,
                    "fullPath": str(indexed_file),
                    "summary": "indexed title",
                    "messageCount": 1,
                    "fileMtime": 0,
                    "created": "2026-01-01T00:00:00.000Z",
                },
                {
                    "sessionId": sid_orphan,
                    "fullPath": str(project_dir / f"{sid_orphan}.jsonl"),
                    "summary": "orphan title",
                    "messageCount": 0,
                    "fileMtime": 0,
                    "created": "2026-01-01T00:00:00.000Z",
                },
            ],
        )

        sessions = cleaner.collect_all_sessions(self.root)
        by_id = {s["session_id"]: s for s in sessions}
        self.assertEqual(len(sessions), 3)
        self.assertTrue(by_id[sid_indexed]["in_index"])
        self.assertTrue(by_id[sid_indexed]["file_exists"])
        self.assertFalse(by_id[sid_unindexed]["in_index"])
        self.assertTrue(by_id[sid_unindexed]["file_exists"])
        self.assertTrue(by_id[sid_orphan]["in_index"])
        self.assertFalse(by_id[sid_orphan]["file_exists"])

    def test_main_scope_current_filters_non_tui_modes(self) -> None:
        current_dir = Path("/tmp/current-proj")
        other_dir = Path("/tmp/other-proj")
        now = datetime.now(timezone.utc)
        sessions = [
            {
                "session_id": "current",
                "path": None,
                "project_dir": Path(cleaner.encode_path(current_dir)),
                "project_label": str(current_dir),
                "title": "current",
                "title_from_index": True,
                "mtime": now,
                "msg_count": 1,
                "size_bytes": 10,
                "file_exists": False,
                "in_index": True,
                "selected": False,
            },
            {
                "session_id": "other",
                "path": None,
                "project_dir": Path(cleaner.encode_path(other_dir)),
                "project_label": str(other_dir),
                "title": "other",
                "title_from_index": True,
                "mtime": now,
                "msg_count": 1,
                "size_bytes": 10,
                "file_exists": False,
                "in_index": True,
                "selected": False,
            },
        ]

        captured = {}

        def fake_analyze(filtered_sessions: list[dict]) -> None:
            captured["sessions"] = filtered_sessions

        with (
            mock.patch.object(sys, "argv", ["dpx_claude_Cleaner.py", "analyze", "--root", str(self.root), "--scope", "current"]),
            mock.patch.object(cleaner, "collect_all_sessions", return_value=sessions),
            mock.patch.object(cleaner, "cmd_analyze", side_effect=fake_analyze),
            mock.patch.object(cleaner.Path, "cwd", return_value=current_dir),
        ):
            cleaner.main()

        self.assertEqual([s["session_id"] for s in captured["sessions"]], ["current"])


if __name__ == "__main__":
    unittest.main()
