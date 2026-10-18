"""
Cross-machine transfer: export_session(), import_bundle(), duplicates,
project_dir_name_for(), pick_session().

Fake ~/.claude trees live in temp dirs; `claude` and `git` are never run.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.helpers import cc

SID = "11111111-2222-3333-4444-555555555555"
NO_GIT = {"is_repo": False, "remote_url": None, "branch": None,
          "head_commit": None, "dirty": None, "unpushed_commits": None}


def make_session(root: Path, project_name: str, sid: str = SID, body: bytes | None = None,
                 sidecar: bool = True, memory: bool = False, cwd: str = "/Users/josh/dev/foo"):
    """Build a project dir with one session; return the session dict."""
    pd = root / "projects" / project_name
    pd.mkdir(parents=True, exist_ok=True)
    # CRLF on purpose: a text-mode copy would silently change these bytes.
    body = body if body is not None else (
        json.dumps({"type": "user", "cwd": cwd, "sessionId": sid,
                    "message": {"role": "user", "content": "hello"}}).encode() + b"\r\n")
    path = pd / f"{sid}.jsonl"
    path.write_bytes(body)
    if sidecar:
        (pd / sid / "subagents").mkdir(parents=True)
        (pd / sid / "subagents" / "agent-a.jsonl").write_bytes(b"{}\n")
    if memory:
        (pd / "memory").mkdir()
        (pd / "memory" / "MEMORY.md").write_text("- note\n")
    return dict(session_id=sid, path=path, project_dir=pd, project_label=cwd,
                title="my session", title_from_index=True,
                mtime=datetime.now(timezone.utc), msg_count=1,
                size_bytes=len(body), file_exists=True, in_index=False, selected=False)


class TransferBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src_root = self.base / "src" / ".claude"
        self.dst_root = self.base / "dst" / ".claude"
        (self.dst_root / "projects").mkdir(parents=True)
        for name in ("claude_version", "git_state"):
            p = mock.patch.object(cc, name, return_value=None if name == "claude_version" else dict(NO_GIT))
            p.start()
            self.addCleanup(p.stop)

    def export(self, **kw):
        s = make_session(self.src_root, "-Users-josh-dev-foo", **kw)
        # "now" far from the file's mtime so the recent-write warning stays quiet
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        bundle, warnings, err = cc.export_session(s, self.base / "out", now=later,
                                                  include_memory=kw.get("memory", False))
        self.assertIsNone(err)
        return s, bundle, warnings


class ExportTests(TransferBase):
    def test_bundle_has_manifest_handoff_transcript_and_sidecar(self):
        _, bundle, _ = self.export()
        names = zipfile.ZipFile(bundle).namelist()
        for want in ("manifest.json", "HANDOFF.md", f"{SID}.jsonl", f"{SID}/subagents/agent-a.jsonl"):
            self.assertIn(want, names)
        self.assertIn("-v1.zip", bundle.name)
        self.assertNotIn("memory/MEMORY.md", names)

    def test_manifest_hash_matches_source_bytes(self):
        s, bundle, _ = self.export()
        m = json.loads(zipfile.ZipFile(bundle).read("manifest.json"))
        self.assertEqual(m["transcript_sha256"], hashlib.sha256(s["path"].read_bytes()).hexdigest())
        self.assertEqual(m["source_project_path"], "/Users/josh/dev/foo")
        self.assertEqual(m["bundle_format"], 1)

    def test_memory_only_when_opted_in(self):
        _, bundle, _ = self.export(memory=True)
        self.assertIn("memory/MEMORY.md", zipfile.ZipFile(bundle).namelist())

    def test_source_is_never_modified(self):
        s = make_session(self.src_root, "-Users-josh-dev-foo")
        before = s["path"].read_bytes()
        cc.export_session(s, self.base / "out")
        self.assertEqual(s["path"].read_bytes(), before)

    def test_empty_session_is_blocked(self):
        s = make_session(self.src_root, "-Users-josh-dev-foo", body=b"")
        bundle, _, err = cc.export_session(s, self.base / "out")
        self.assertIsNone(bundle)
        self.assertIn("empty", err)

    def test_recent_write_and_dirty_git_warn(self):
        s = make_session(self.src_root, "-Users-josh-dev-foo")
        dirty = dict(NO_GIT, is_repo=True, dirty=True)
        with mock.patch.object(cc, "git_state", return_value=dirty):
            _, warnings, err = cc.export_session(s, self.base / "out")
        self.assertIsNone(err)
        self.assertEqual(len(warnings), 2)

    def test_handoff_has_no_em_dashes(self):
        _, bundle, _ = self.export()
        self.assertNotIn("\u2014", zipfile.ZipFile(bundle).read("HANDOFF.md").decode())


class ImportTests(TransferBase):
    def test_lands_byte_identical_in_encoded_project_dir(self):
        s, bundle, _ = self.export()
        target = Path("/Users/me/code/bar baz")
        res = cc.import_bundle(bundle, self.dst_root, target)
        self.assertEqual(res["status"], "imported")
        dest = self.dst_root / "projects" / cc.encode_path(target) / f"{SID}.jsonl"
        self.assertEqual(res["path"], dest)
        self.assertEqual(dest.read_bytes(), s["path"].read_bytes())  # CRLF intact
        self.assertTrue((dest.parent / SID / "subagents" / "agent-a.jsonl").exists())

    def test_reimport_same_content_is_a_noop(self):
        _, bundle, _ = self.export()
        cc.import_bundle(bundle, self.dst_root, Path("/a"))
        res = cc.import_bundle(bundle, self.dst_root, Path("/b"))
        self.assertEqual(res["status"], "already-imported")
        self.assertEqual(len(cc.find_session_copies(self.dst_root, SID)), 1)

    def test_different_content_aborts_by_default_and_keeps_existing(self):
        _, bundle, _ = self.export()
        make_session(self.dst_root, "-elsewhere", body=b'{"type":"user"}\n', sidecar=False)
        res = cc.import_bundle(bundle, self.dst_root, Path("/a"))
        self.assertEqual(res["status"], "aborted")
        self.assertEqual(len(cc.find_session_copies(self.dst_root, SID)), 1)

    def test_overwrite_replaces_in_place_never_a_second_copy(self):
        s, bundle, _ = self.export()
        make_session(self.dst_root, "-elsewhere", body=b'{"type":"user"}\n', sidecar=False)
        res = cc.import_bundle(bundle, self.dst_root, Path("/a"), on_conflict=lambda p: "overwrite")
        self.assertEqual(res["status"], "imported")
        copies = cc.find_session_copies(self.dst_root, SID)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].parent.name, "-elsewhere")
        self.assertEqual(copies[0].read_bytes(), s["path"].read_bytes())

    def test_tampered_transcript_is_rejected(self):
        _, bundle, _ = self.export()
        bad = self.base / "bad.zip"
        with zipfile.ZipFile(bundle) as zi, zipfile.ZipFile(bad, "w") as zo:
            for n in zi.namelist():
                d = zi.read(n)
                zo.writestr(n, d + b"x" if n == f"{SID}.jsonl" else d)
        res = cc.import_bundle(bad, self.dst_root, Path("/a"))
        self.assertEqual(res["status"], "error")
        self.assertIn("sha256", res["message"])
        self.assertEqual(cc.find_session_copies(self.dst_root, SID), [])

    def test_unsupported_bundle_format_is_rejected(self):
        _, bundle, _ = self.export()
        bad = self.base / "v9.zip"
        with zipfile.ZipFile(bundle) as zi, zipfile.ZipFile(bad, "w") as zo:
            for n in zi.namelist():
                d = zi.read(n)
                if n == "manifest.json":
                    d = json.dumps({**json.loads(d), "bundle_format": 9}).encode()
                zo.writestr(n, d)
        self.assertEqual(cc.import_bundle(bad, self.dst_root, Path("/a"))["status"], "error")

    def test_zip_slip_members_are_ignored(self):
        _, bundle, _ = self.export()
        evil = self.base / "evil.zip"
        with zipfile.ZipFile(bundle) as zi, zipfile.ZipFile(evil, "w") as zo:
            for n in zi.namelist():
                zo.writestr(n, zi.read(n))
            zo.writestr(f"{SID}/../../escaped.txt", b"nope")
        cc.import_bundle(evil, self.dst_root, Path("/a"))
        self.assertFalse((self.dst_root / "escaped.txt").exists())
        self.assertFalse((self.dst_root / "projects" / "escaped.txt").exists())

    def test_memory_is_opt_in_and_never_clobbers(self):
        _, bundle, _ = self.export(memory=True)
        res = cc.import_bundle(bundle, self.dst_root, Path("/a"))
        self.assertFalse((res["path"].parent / "memory").exists())
        # a fresh machine with opt-in gets it ...
        fresh = self.base / "fresh" / ".claude"
        (fresh / "projects").mkdir(parents=True)
        res = cc.import_bundle(bundle, fresh, Path("/c"), include_memory=True)
        mem = res["path"].parent / "memory" / "MEMORY.md"
        self.assertTrue(mem.exists())
        # ... but a pre-existing memory/ is never clobbered, and we warn
        other = self.base / "other" / ".claude"
        pd = other / "projects" / cc.encode_path(Path("/d"))
        (pd / "memory").mkdir(parents=True)
        (pd / "memory" / "MEMORY.md").write_text("mine\n")
        res = cc.import_bundle(bundle, other, Path("/d"), include_memory=True)
        self.assertEqual((pd / "memory" / "MEMORY.md").read_text(), "mine\n")
        self.assertEqual(len(res["warnings"]), 1)

    def test_version_mismatch_warns(self):
        _, bundle, _ = self.export()
        with mock.patch.object(cc, "claude_version", return_value="9.9.9"):
            # bundle was exported with claude_version() -> None, so no warning
            self.assertEqual(cc.import_bundle(bundle, self.dst_root, Path("/a"))["warnings"], [])
        with mock.patch.object(cc, "claude_version", return_value="1.0.0"):
            s = make_session(self.src_root, "-Users-josh-dev-foo", sid="aaaaaaaa-0000-0000-0000-000000000000")
            with mock.patch.object(cc, "claude_version", return_value="2.0.0"):
                b2, _, _ = cc.export_session(s, self.base / "out2",
                                             now=datetime.now(timezone.utc) + timedelta(hours=1))
            res = cc.import_bundle(b2, self.dst_root, Path("/z"))
        self.assertEqual(len(res["warnings"]), 1)


class ProjectDirNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "projects").mkdir()

    def test_encodes_mac_windows_and_linux_paths(self):
        self.assertEqual(cc.project_dir_name_for(Path("/Users/josh/dev/foo"), self.root),
                         "-Users-josh-dev-foo")
        self.assertEqual(cc.project_dir_name_for(Path("C:\\dev\\foo"), self.root), "C--dev-foo")
        self.assertEqual(cc.project_dir_name_for(Path("/home/j/my app.v2"), self.root),
                         "-home-j-my-app-v2")

    def test_env_override_wins(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_PROJECT_DIR_NAME": "custom"}):
            self.assertEqual(cc.project_dir_name_for(Path("/x"), self.root), "custom")

    def test_overlong_path_is_none_unless_claude_already_made_the_folder(self):
        long = Path("/" + "a" * 250)
        self.assertIsNone(cc.project_dir_name_for(long, self.root))
        make_session(self.root, "claude-made-this-with-a-hash", cwd=str(long), sidecar=False)
        self.assertEqual(cc.project_dir_name_for(long, self.root), "claude-made-this-with-a-hash")


class DuplicateAndPickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_finds_ids_in_more_than_one_project(self):
        make_session(self.root, "-a", sidecar=False)
        make_session(self.root, "-b", sidecar=False)
        make_session(self.root, "-a", sid="solo", sidecar=False)
        dupes = cc.find_duplicate_sessions(self.root)
        self.assertEqual(list(dupes), [SID])
        self.assertEqual(len(dupes[SID]), 2)

    def test_pick_session_selectors(self):
        a = make_session(self.root, "-a", sid="abc12345", sidecar=False)
        b = make_session(self.root, "-b", sid="abd99999", sidecar=False)
        b["title"] = "Other thing"
        sessions = [a, b]
        self.assertEqual(cc.pick_session(sessions, session_id="abc")[0], a)
        self.assertIn("ambiguous", cc.pick_session(sessions, session_id="ab")[1])
        self.assertEqual(cc.pick_session(sessions, name="other")[0], b)
        self.assertEqual(cc.pick_session(sessions, latest=True, current_project="-b")[0], b)
        self.assertIsNotNone(cc.pick_session(sessions, session_id="zzz")[1])


if __name__ == "__main__":
    unittest.main()
