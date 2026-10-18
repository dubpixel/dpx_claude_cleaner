"""
.jsonl patch-log reconstruction: reconstruct_jsonl_session(), _set_path(),
_archive_requests().

This is the single most important correctness property of vazzle -- see
VSCODE-CHAT-RECOVERY.md section 3-4. A naive "replay everything, read
final state" implementation silently drops all but the last 1-2 turns of
a compacted session (confirmed against real files: 5.7MB / 85 real turns
read as 1 turn naively).
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import vc


def write_patch_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


class ReconstructJsonlSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "session.jsonl"

    def test_snapshot_only_recovers_the_initial_state(self):
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {
                "customTitle": "hello",
                "requests": [
                    {"requestId": "r1", "message": {"text": "hi"}, "response": [], "timestamp": 1},
                ],
            }},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        self.assertEqual(state["customTitle"], "hello")
        self.assertEqual(len(state["requests"]), 1)
        self.assertEqual(state["requests"][0]["requestId"], "r1")

    def test_simple_patches_apply_in_order(self):
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {"requests": []}},
            {"kind": 1, "k": ["customTitle"], "v": "first"},
            {"kind": 1, "k": ["customTitle"], "v": "second"},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        self.assertEqual(state["customTitle"], "second")

    def test_compaction_patch_does_not_lose_earlier_turns(self):
        """
        The core regression this whole tool exists to prevent: a patch
        replacing the live `requests` array (a compaction event) must not
        silently drop turns that were live before it -- they belong in the
        archive.
        """
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {"requests": [
                {"requestId": "r1", "message": {"text": "turn one"}, "response": [{"kind": "markdownContent", "content": "a1"}], "timestamp": 1},
                {"requestId": "r2", "message": {"text": "turn two"}, "response": [{"kind": "markdownContent", "content": "a2"}], "timestamp": 2},
            ]}},
            # Compaction: server replaces the whole array with just the
            # latest turn, as real Copilot Chat does after /compact.
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r3", "message": {"text": "turn three"}, "response": [{"kind": "markdownContent", "content": "a3"}], "timestamp": 3},
            ]},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        recovered_ids = {r["requestId"] for r in state["requests"]}
        self.assertEqual(recovered_ids, {"r1", "r2", "r3"})

    def test_multiple_compactions_recover_all_turns(self):
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {"requests": [
                {"requestId": "r1", "message": {"text": "t1"}, "response": [], "timestamp": 1},
            ]}},
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r2", "message": {"text": "t2"}, "response": [], "timestamp": 2},
            ]},
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r3", "message": {"text": "t3"}, "response": [], "timestamp": 3},
            ]},
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r4", "message": {"text": "t4"}, "response": [], "timestamp": 4},
            ]},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        recovered_ids = {r["requestId"] for r in state["requests"]}
        self.assertEqual(recovered_ids, {"r1", "r2", "r3", "r4"})

    def test_final_live_state_is_snapshotted_even_without_a_trailing_compaction(self):
        # Whatever's live at end-of-file and never got compacted must still
        # be archived -- the end-of-file snapshot step.
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {"requests": []}},
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r1", "message": {"text": "t1"}, "response": [], "timestamp": 1},
            ]},
            {"kind": 1, "k": ["requests", 0, "response"], "v": [{"kind": "markdownContent", "content": "streamed in"}]},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        self.assertEqual(len(state["requests"]), 1)
        self.assertEqual(state["requests"][0]["response"][0]["content"], "streamed in")

    def test_fuller_response_wins_when_a_requestid_reappears(self):
        """
        A response streams in across several patches before the next
        compaction -- if the same requestId is archived twice (once with a
        partial response, once fuller), keep the fuller one.
        """
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {"requests": [
                {"requestId": "r1", "message": {"text": "t1"},
                 "response": [{"kind": "markdownContent", "content": "partial"}], "timestamp": 1},
            ]}},
            # First compaction archives r1 with 1 response part, then live
            # state moves on.
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r1", "message": {"text": "t1"},
                 "response": [{"kind": "markdownContent", "content": "partial"},
                              {"kind": "markdownContent", "content": "fuller"}],
                 "timestamp": 1},
            ]},
            # Second compaction archives the fuller r1 again -- must not
            # regress back to the partial version.
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "r2", "message": {"text": "t2"}, "response": [], "timestamp": 2},
            ]},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        by_id = {r["requestId"]: r for r in state["requests"]}
        self.assertEqual(len(by_id["r1"]["response"]), 2)

    def test_requests_are_sorted_by_timestamp_in_final_output(self):
        write_patch_jsonl(self.path, [
            {"kind": 0, "v": {"requests": [
                {"requestId": "later", "message": {"text": "later"}, "response": [], "timestamp": 100},
            ]}},
            {"kind": 2, "k": ["requests"], "v": [
                {"requestId": "earlier", "message": {"text": "earlier"}, "response": [], "timestamp": 1},
            ]},
        ])
        state = vc.reconstruct_jsonl_session(self.path)
        ids_in_order = [r["requestId"] for r in state["requests"]]
        self.assertEqual(ids_in_order, ["earlier", "later"])

    def test_malformed_lines_are_skipped(self):
        self.path.write_text(
            json.dumps({"kind": 0, "v": {"requests": []}}) + "\n"
            "not valid json\n"
            + json.dumps({"kind": 1, "k": ["customTitle"], "v": "ok"}) + "\n",
            encoding="utf-8",
        )
        state = vc.reconstruct_jsonl_session(self.path)
        self.assertEqual(state["customTitle"], "ok")


class SetPathTests(unittest.TestCase):
    def test_sets_a_top_level_key(self):
        state = {}
        vc._set_path(state, ["customTitle"], "hi")
        self.assertEqual(state, {"customTitle": "hi"})

    def test_creates_intermediate_dicts(self):
        state = {}
        vc._set_path(state, ["a", "b", "c"], 1)
        self.assertEqual(state, {"a": {"b": {"c": 1}}})

    def test_sets_a_list_index_extending_as_needed(self):
        state = {"requests": []}
        vc._set_path(state, ["requests", 2], "x")
        self.assertEqual(state["requests"], [None, None, "x"])

    def test_replaces_a_whole_list_at_a_key(self):
        state = {"requests": [1, 2, 3]}
        vc._set_path(state, ["requests"], [9])
        self.assertEqual(state["requests"], [9])


if __name__ == "__main__":
    unittest.main()
