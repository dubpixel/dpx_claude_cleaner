"""
Mutating operations: delete_sessions(), rename_session().
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import cc, write_jsonl


class DeleteSessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.claude_root = Path(self.tmp.name) / ".claude"
        self.project_dir = self.claude_root / "projects" / "-tmp-proj"
        self.project_dir.mkdir(parents=True)
        self.session_path = self.project_dir / "abc.jsonl"
        write_jsonl(self.session_path, [{"type": "user", "message": {"role": "user", "content": "hi"}}])

    def _session(self, in_index=False):
        return dict(
            session_id="abc", path=self.session_path, project_dir=self.project_dir,
            project_label="/tmp/proj", title="hi", title_from_index=False,
            mtime=None, msg_count=1, size_bytes=10, file_exists=True,
            in_index=in_index, selected=False,
        )

    def test_deletes_the_file_from_disk(self):
        deleted, errors = cc.delete_sessions([self._session()], self.claude_root)
        self.assertEqual(deleted, 1)
        self.assertEqual(errors, [])
        self.assertFalse(self.session_path.exists())

    def test_removes_the_matching_index_entry_and_keeps_others(self):
        index_path = self.project_dir / cc.INDEX_FILE
        index_path.write_text(json.dumps([
            {"sessionId": "abc", "summary": "hi"},
            {"sessionId": "other", "summary": "keep me"},
        ]))
        cc.delete_sessions([self._session(in_index=True)], self.claude_root)
        remaining = cc.read_index(index_path)
        self.assertEqual([e["sessionId"] for e in remaining], ["other"])

    def test_a_session_with_no_file_still_counts_as_deleted(self):
        s = self._session()
        s["file_exists"] = False
        deleted, errors = cc.delete_sessions([s], self.claude_root)
        self.assertEqual(deleted, 1)
        self.assertEqual(errors, [])

    def test_unlink_failure_is_reported_as_an_error_not_a_deletion(self):
        with mock.patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            deleted, errors = cc.delete_sessions([self._session()], self.claude_root)
        self.assertEqual(deleted, 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("permission denied", errors[0])

    def test_project_dir_is_removed_once_its_last_session_is_deleted(self):
        cc.delete_sessions([self._session()], self.claude_root)
        self.assertFalse(self.project_dir.exists())


class RenameSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.claude_root = Path(self.tmp.name) / ".claude"
        self.project_dir = self.claude_root / "projects" / "-tmp-proj"
        self.project_dir.mkdir(parents=True)
        self.session_path = self.project_dir / "abc.jsonl"
        write_jsonl(self.session_path, [{"type": "user", "message": {"role": "user", "content": "hi"}}])
        self.s = dict(
            session_id="abc", path=self.session_path, project_dir=self.project_dir,
            project_label="/tmp/proj", title="hi", title_from_index=False,
            mtime=None, msg_count=1, size_bytes=10, file_exists=True,
            in_index=False, selected=False,
        )

    def test_injects_a_summary_line_at_the_top_of_the_file(self):
        err = cc.rename_session(self.s, "new title", self.claude_root)
        self.assertIsNone(err)
        first_line = json.loads(self.session_path.read_text().splitlines()[0])
        self.assertEqual(first_line["type"], "summary")
        self.assertEqual(first_line["summary"], "new title")
        self.assertEqual(self.s["title"], "new title")
        self.assertTrue(self.s["title_from_index"])

    def test_replaces_an_existing_summary_line_instead_of_duplicating_it(self):
        cc.rename_session(self.s, "first title", self.claude_root)
        cc.rename_session(self.s, "second title", self.claude_root)
        lines = self.session_path.read_text().splitlines()
        summary_lines = [l for l in lines if json.loads(l).get("type") == "summary"]
        self.assertEqual(len(summary_lines), 1)
        self.assertEqual(json.loads(summary_lines[0])["summary"], "second title")

    def test_empty_title_is_rejected_and_nothing_changes(self):
        err = cc.rename_session(self.s, "   ", self.claude_root)
        self.assertEqual(err, "Empty title")
        self.assertEqual(self.s["title"], "hi")
        # file untouched
        first_line = json.loads(self.session_path.read_text().splitlines()[0])
        self.assertEqual(first_line["type"], "user")

    def test_updates_a_matching_index_entry(self):
        index_path = self.project_dir / cc.INDEX_FILE
        index_path.write_text(json.dumps([{"sessionId": "abc", "summary": "hi"}]))
        self.s["in_index"] = True
        cc.rename_session(self.s, "renamed", self.claude_root)
        entries = cc.read_index(index_path)
        self.assertEqual(entries[0]["summary"], "renamed")


if __name__ == "__main__":
    unittest.main()
