"""
main() CLI entry point: --scope current filtering.

Runs the real main()/collect_all_sessions() path end to end against
on-disk fixtures (not mocked), with stdout captured so a passing test
run doesn't dump scan banners into the CI log.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import cc, write_jsonl


class ScopeCurrentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.claude_root = Path(self.tmp.name) / ".claude"
        (self.claude_root / "projects").mkdir(parents=True)
        self.cwd = Path(self.tmp.name) / "current-proj"

        current_dir = self.claude_root / "projects" / cc.encode_path(self.cwd)
        current_dir.mkdir()
        write_jsonl(current_dir / "current.jsonl", [
            {"type": "user", "cwd": str(self.cwd), "message": {"role": "user", "content": "hi"}},
        ])

        other_dir = self.claude_root / "projects" / "-tmp-other-proj"
        other_dir.mkdir()
        write_jsonl(other_dir / "other.jsonl", [
            {"type": "user", "cwd": "/tmp/other-proj", "message": {"role": "user", "content": "hi"}},
        ])

    def _run_main(self, extra_args):
        captured = {}

        def fake_cmd_analyze(sessions):
            captured["sessions"] = sessions

        argv = ["dpx_claude_Cleaner.py", "analyze", "--root", str(self.claude_root)] + extra_args
        with contextlib.redirect_stdout(io.StringIO()), \
             mock.patch.object(cc.sys, "argv", argv), \
             mock.patch.object(cc, "cmd_analyze", side_effect=fake_cmd_analyze), \
             mock.patch.object(cc.Path, "cwd", return_value=self.cwd):
            cc.main()
        return captured["sessions"]

    def test_scope_current_only_includes_the_cwd_project(self):
        sessions = self._run_main(["--scope", "current"])
        self.assertEqual([s["session_id"] for s in sessions], ["current"])

    def test_scope_all_includes_every_project(self):
        sessions = self._run_main(["--scope", "all"])
        self.assertEqual(
            {s["session_id"] for s in sessions},
            {"current", "other"},
        )

    def test_scope_current_is_the_default(self):
        sessions = self._run_main([])
        self.assertEqual([s["session_id"] for s in sessions], ["current"])


if __name__ == "__main__":
    unittest.main()
