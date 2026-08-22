"""
Workspace path resolution: workspace_uri_to_path(), get_workspace_path().

Unlike zazzle's decode_encoded(), this is exact -- workspace.json stores
the real file:// URI, no lossy hyphen-decoding involved.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import vc


class WorkspaceUriToPathTests(unittest.TestCase):
    def test_plain_file_uri_decodes_to_the_path(self):
        uri = "file:///Users/josh/code/myapp"
        self.assertEqual(vc.workspace_uri_to_path(uri), "/Users/josh/code/myapp")

    def test_percent_encoded_characters_are_decoded(self):
        # Real example from this session: spaces (%20) and @ (%40) in a
        # Google Drive path.
        uri = "file:///Users/you/Library/CloudStorage/GoogleDrive-i%40dubpixel.tv/My%20Drive/project"
        self.assertEqual(
            vc.workspace_uri_to_path(uri),
            "/Users/you/Library/CloudStorage/GoogleDrive-i@dubpixel.tv/My Drive/project",
        )

    def test_non_file_scheme_returns_none(self):
        self.assertIsNone(vc.workspace_uri_to_path("vscode-remote://ssh-remote/foo"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(vc.workspace_uri_to_path(""))


class GetWorkspacePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws_dir = Path(self.tmp.name)

    def test_reads_the_workspace_field_from_workspace_json(self):
        (self.ws_dir / "workspace.json").write_text(
            json.dumps({"workspace": "file:///Users/x/project"}), encoding="utf-8"
        )
        self.assertEqual(vc.get_workspace_path(self.ws_dir), "/Users/x/project")

    def test_missing_workspace_json_returns_none(self):
        self.assertIsNone(vc.get_workspace_path(self.ws_dir))

    def test_malformed_workspace_json_returns_none(self):
        (self.ws_dir / "workspace.json").write_text("not json", encoding="utf-8")
        self.assertIsNone(vc.get_workspace_path(self.ws_dir))


if __name__ == "__main__":
    unittest.main()
