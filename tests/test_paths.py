"""
Path encoding/decoding and cwd extraction: encode_path(), decode_encoded(),
get_project_cwd_from_jsonl().
"""
import tempfile
import unittest
from pathlib import Path

from tests.helpers import cc, write_jsonl


class EncodePathTests(unittest.TestCase):
    def test_simple_path_replaces_slashes_with_hyphens(self):
        self.assertEqual(cc.encode_path("/a/b/c"), "-a-b-c")

    def test_every_non_alphanumeric_character_becomes_a_hyphen(self):
        # Regression: 0.1.3 -- encode_path() used to only replace "/",
        # silently breaking --scope current for any real path with a
        # space, ".", "@", or "_" in it. Verified against 30 real project
        # directories' recorded cwd values.
        p = ("/Users/josh/Library/CloudStorage/GoogleDrive-i@dubpixel.tv/"
             "My Drive/_.DUBPIXEL/_...CODE/dpx_claude_cleaner")
        expected = ("-Users-josh-Library-CloudStorage-GoogleDrive-i-dubpixel-tv-"
                    "My-Drive---DUBPIXEL-----CODE-dpx-claude-cleaner")
        self.assertEqual(cc.encode_path(p), expected)

    def test_spaces_are_encoded(self):
        self.assertEqual(cc.encode_path("/My Drive/proj"), "-My-Drive-proj")

    def test_at_sign_is_encoded(self):
        self.assertEqual(cc.encode_path("/Users/i@dubpixel.tv"), "-Users-i-dubpixel-tv")

    def test_accepts_a_path_object_not_just_a_string(self):
        self.assertEqual(cc.encode_path(Path("/a/b")), "-a-b")


class DecodeEncodedTests(unittest.TestCase):
    def test_round_trips_a_path_with_no_hyphens_in_it(self):
        encoded = cc.encode_path("/a/b/c")
        self.assertEqual(cc.decode_encoded(encoded), "/a/b/c")

    def test_is_lossy_for_paths_that_contain_real_hyphens(self):
        # Known, documented limitation: encode_path() can't be perfectly
        # inverted since a real hyphen and an encoded separator both
        # become "-". decode_encoded() is a best-effort fallback only.
        encoded = cc.encode_path("/Users/foo-bar/baz")
        self.assertNotEqual(cc.decode_encoded(encoded), "/Users/foo-bar/baz")


class GetProjectCwdFromJsonlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "session.jsonl"

    def test_returns_cwd_when_present(self):
        write_jsonl(self.path, [{"type": "user", "cwd": "/tmp/project"}])
        self.assertEqual(cc.get_project_cwd_from_jsonl(self.path), "/tmp/project")

    def test_returns_none_when_no_line_has_a_cwd_field(self):
        write_jsonl(self.path, [{"type": "assistant", "message": {"content": "x"}}])
        self.assertIsNone(cc.get_project_cwd_from_jsonl(self.path))

    def test_returns_none_for_a_blank_cwd_value(self):
        write_jsonl(self.path, [{"type": "user", "cwd": "   "}])
        self.assertIsNone(cc.get_project_cwd_from_jsonl(self.path))

    def test_stops_scanning_after_the_first_twenty_lines(self):
        rows = [{"type": "mode"}] * 25
        rows.append({"type": "user", "cwd": "/too/late"})
        write_jsonl(self.path, rows)
        self.assertIsNone(cc.get_project_cwd_from_jsonl(self.path))


if __name__ == "__main__":
    unittest.main()
