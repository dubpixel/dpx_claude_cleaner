"""
Session discovery: collect_all_sessions(), is_empty(), is_orphan().
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import cc, write_jsonl


class CollectAllSessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.claude_root = Path(self.tmp.name) / ".claude"
        self.project_dir = self.claude_root / "projects" / "-tmp-proj"
        self.project_dir.mkdir(parents=True)

    def test_no_projects_directory_returns_an_empty_list(self):
        empty_root = Path(self.tmp.name) / "no-claude-here"
        self.assertEqual(cc.collect_all_sessions(empty_root), [])

    def test_finds_a_session_not_in_any_index(self):
        write_jsonl(self.project_dir / "abc.jsonl", [
            {"type": "user", "cwd": "/tmp/proj", "message": {"role": "user", "content": "hi"}},
        ])
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual(len(sessions), 1)
        self.assertFalse(sessions[0]["in_index"])
        self.assertEqual(sessions[0]["project_label"], "/tmp/proj")

    def test_project_label_prefers_real_cwd_over_decoded_folder_name(self):
        # Regression: 0.1.2 -- decode_encoded() is lossy for any real path
        # containing a hyphen; get_project_cwd_from_jsonl() is exact.
        hyphenated = self.claude_root / "projects" / "-Users-foo-bar-baz"
        hyphenated.mkdir(parents=True)
        write_jsonl(hyphenated / "abc.jsonl", [
            {"type": "user", "cwd": "/Users/foo-bar/baz", "message": {"role": "user", "content": "hi"}},
        ])
        sessions = cc.collect_all_sessions(self.claude_root)
        matching = [s for s in sessions if s["project_dir"] == hyphenated]
        self.assertEqual(matching[0]["project_label"], "/Users/foo-bar/baz")

    def test_agent_name_prefixed_files_are_excluded(self):
        write_jsonl(self.project_dir / "abc.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
        ])
        write_jsonl(self.project_dir / "agent-xyz.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "should not appear"}},
        ])
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["session_id"], "abc")

    def test_warmup_files_are_excluded(self):
        write_jsonl(self.project_dir / "abc.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
        ])
        write_jsonl(self.project_dir / "warmup-1.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "should not appear"}},
        ])
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual(len(sessions), 1)

    def test_index_entry_merges_with_its_matching_file(self):
        write_jsonl(self.project_dir / "abc.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
        ])
        index_path = self.project_dir / cc.INDEX_FILE
        index_path.write_text(json.dumps([
            {"sessionId": "abc", "fullPath": str(self.project_dir / "abc.jsonl"),
             "summary": "indexed title", "messageCount": 1, "fileMtime": 0, "created": ""},
        ]))
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual(len(sessions), 1)
        s = sessions[0]
        self.assertTrue(s["in_index"])
        self.assertTrue(s["file_exists"])
        self.assertEqual(s["title"], "indexed title")

    def test_index_entry_with_no_matching_file_is_an_orphan(self):
        index_path = self.project_dir / cc.INDEX_FILE
        index_path.write_text(json.dumps([
            {"sessionId": "missing", "fullPath": str(self.project_dir / "missing.jsonl"),
             "summary": "gone", "messageCount": 0, "fileMtime": 0, "created": ""},
        ]))
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(cc.is_orphan(sessions[0]))

    def test_same_session_id_from_index_and_disk_is_not_duplicated(self):
        write_jsonl(self.project_dir / "abc.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
        ])
        index_path = self.project_dir / cc.INDEX_FILE
        index_path.write_text(json.dumps([
            {"sessionId": "abc", "fullPath": str(self.project_dir / "abc.jsonl"),
             "summary": "indexed title", "messageCount": 1, "fileMtime": 0, "created": ""},
        ]))
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual(len(sessions), 1)

    def test_results_are_sorted_by_mtime_descending(self):
        import os
        import time

        older = self.project_dir / "older.jsonl"
        newer = self.project_dir / "newer.jsonl"
        write_jsonl(older, [{"type": "user", "message": {"role": "user", "content": "old"}}])
        time.sleep(0.01)
        write_jsonl(newer, [{"type": "user", "message": {"role": "user", "content": "new"}}])
        sessions = cc.collect_all_sessions(self.claude_root)
        self.assertEqual([s["session_id"] for s in sessions], ["newer", "older"])


class IsEmptyIsOrphanTests(unittest.TestCase):
    def test_is_empty_uses_msg_count_when_available(self):
        self.assertTrue(cc.is_empty({"msg_count": 0, "size_bytes": 999999}))
        self.assertFalse(cc.is_empty({"msg_count": 5, "size_bytes": 0}))

    def test_is_empty_falls_back_to_size_when_msg_count_is_none(self):
        self.assertTrue(cc.is_empty({"msg_count": None, "size_bytes": 10}))
        self.assertFalse(cc.is_empty({"msg_count": None, "size_bytes": cc.SMALL_BYTES + 1}))

    def test_is_orphan_reflects_file_exists(self):
        self.assertTrue(cc.is_orphan({"file_exists": False}))
        self.assertFalse(cc.is_orphan({"file_exists": True}))


if __name__ == "__main__":
    unittest.main()
