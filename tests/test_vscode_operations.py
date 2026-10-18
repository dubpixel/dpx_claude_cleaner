"""
rename_session(), delete_sessions(), export_sessions_markdown(),
render_markdown().
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import vc


def make_session_dict(session_id="sess-1", path=None, format="json",
                       editing_dir=None, title="a title", project_path="/tmp/proj",
                       project_exists=True):
    return dict(
        session_id=session_id,
        workspace_hash="hash1",
        path=path,
        editing_dir=editing_dir,
        project_path=project_path,
        project_exists=project_exists,
        title=title,
        title_from_index=True,
        creation_date=None,
        last_message_date=None,
        turn_count=1,
        size_bytes=100,
        mtime=None,
        is_orphan=not project_exists,
        format=format,
        selected=False,
    )


class RenameSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_rename_flat_json_rewrites_the_field(self):
        path = Path(self.tmp.name) / "s.json"
        path.write_text(json.dumps({"sessionId": "s", "customTitle": None, "requests": []}),
                         encoding="utf-8")
        s = make_session_dict(path=path, format="json")

        err = vc.rename_session(s, "new title")
        self.assertIsNone(err)
        self.assertEqual(s["title"], "new title")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["customTitle"], "new title")

    def test_rename_jsonl_appends_a_patch_line_without_rewriting_earlier_lines(self):
        path = Path(self.tmp.name) / "s.jsonl"
        original = json.dumps({"kind": 0, "v": {"requests": []}}) + "\n"
        path.write_text(original, encoding="utf-8")
        s = make_session_dict(path=path, format="jsonl")

        err = vc.rename_session(s, "renamed via patch")
        self.assertIsNone(err)

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], original.strip())  # untouched
        patch = json.loads(lines[1])
        self.assertEqual(patch["k"], ["customTitle"])
        self.assertEqual(patch["v"], "renamed via patch")

        # Reconstructing the file should now reflect the new title.
        state = vc.reconstruct_jsonl_session(path)
        self.assertEqual(state["customTitle"], "renamed via patch")

    def test_empty_title_is_rejected(self):
        s = make_session_dict()
        err = vc.rename_session(s, "   ")
        self.assertEqual(err, "Empty title")


class DeleteSessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_deletes_the_session_file(self):
        path = Path(self.tmp.name) / "s.json"
        path.write_text("{}", encoding="utf-8")
        s = make_session_dict(path=path)

        deleted, errors = vc.delete_sessions([s])
        self.assertEqual(deleted, 1)
        self.assertEqual(errors, [])
        self.assertFalse(path.exists())

    def test_deletes_the_matching_editing_dir_too(self):
        path = Path(self.tmp.name) / "s.json"
        path.write_text("{}", encoding="utf-8")
        editing_dir = Path(self.tmp.name) / "chatEditingSessions" / "s"
        editing_dir.mkdir(parents=True)
        (editing_dir / "somefile.txt").write_text("x", encoding="utf-8")
        s = make_session_dict(path=path, editing_dir=editing_dir)

        deleted, errors = vc.delete_sessions([s])
        self.assertEqual(deleted, 1)
        self.assertEqual(errors, [])
        self.assertFalse(editing_dir.exists())

    def test_missing_file_is_reported_as_an_error_not_a_crash(self):
        path = Path(self.tmp.name) / "does-not-exist.json"
        s = make_session_dict(path=path)

        deleted, errors = vc.delete_sessions([s])
        self.assertEqual(deleted, 0)
        self.assertEqual(len(errors), 1)


class RenderMarkdownTests(unittest.TestCase):
    def test_renders_user_and_assistant_turns(self):
        state = {
            "creationDate": None,
            "requests": [
                {"message": {"text": "hello"}, "response": [
                    {"kind": "markdownContent", "content": {"value": "hi there"}},
                ]},
            ],
        }
        md = vc.render_markdown(state, "Test Chat")
        self.assertIn("# Test Chat", md)
        self.assertIn("## USER:", md)
        self.assertIn("hello", md)
        self.assertIn("### ASSISTANT:", md)
        self.assertIn("hi there", md)

    def test_tool_invocation_parts_are_included(self):
        state = {"requests": [
            {"message": {"text": "run the tests"}, "response": [
                {"kind": "toolInvocationSerialized",
                 "pastTenseMessage": {"value": "Ran the test suite"}},
            ]},
        ]}
        md = vc.render_markdown(state, "Tool Chat")
        self.assertIn("Ran the test suite", md)

    def test_empty_response_still_renders_a_placeholder(self):
        state = {"requests": [{"message": {"text": "hi"}, "response": []}]}
        md = vc.render_markdown(state, "Empty Response")
        self.assertIn("_(empty)_", md)


class ExportSessionsMarkdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_writes_one_markdown_file_per_session(self):
        src = Path(self.tmp.name) / "s.json"
        src.write_text(json.dumps({
            "customTitle": "My Export Test",
            "requests": [{"message": {"text": "hi"}, "response": []}],
        }), encoding="utf-8")
        s = make_session_dict(session_id="sess-export", path=src, title="My Export Test")
        dest_dir = Path(self.tmp.name) / "out"

        written, errors = vc.export_sessions_markdown([s], dest_dir)
        self.assertEqual(written, 1)
        self.assertEqual(errors, [])
        files = list(dest_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("My Export Test", files[0].read_text(encoding="utf-8"))

    def test_title_is_sanitized_for_the_filename(self):
        src = Path(self.tmp.name) / "s.json"
        src.write_text(json.dumps({"customTitle": "bad/name?!", "requests": []}), encoding="utf-8")
        s = make_session_dict(session_id="sess-bad", path=src, title="bad/name?!")
        dest_dir = Path(self.tmp.name) / "out2"

        written, errors = vc.export_sessions_markdown([s], dest_dir)
        self.assertEqual(written, 1)
        files = list(dest_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("/", files[0].name.replace(dest_dir.name, ""))


class DefaultExportDirTests(unittest.TestCase):
    def test_live_project_exports_into_a_chat_history_subfolder(self):
        s = make_session_dict(project_path="/some/live/project", project_exists=True)
        self.assertEqual(vc.default_export_dir(s), Path("/some/live/project") / "_chat-history")

    def test_orphaned_project_falls_back_to_home_export_dir(self):
        s = make_session_dict(project_exists=False)
        self.assertEqual(vc.default_export_dir(s), Path.home() / "vazzle-exports")


if __name__ == "__main__":
    unittest.main()
