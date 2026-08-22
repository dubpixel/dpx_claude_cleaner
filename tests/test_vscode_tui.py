"""
build_display_rows() -- groups the flat visible-session list into project
header rows + session rows for the TUI. Pure data transform, no curses
needed to test it.
"""
import unittest

from tests.helpers import vc


def make_session(idx, project_path):
    return {"session_id": f"s{idx}", "project_path": project_path}


class BuildDisplayRowsTests(unittest.TestCase):
    def test_a_single_project_gets_one_header(self):
        sessions = [make_session(0, "/proj/a"), make_session(1, "/proj/a")]
        rows, row_of_pos = vc.build_display_rows(sessions, [0, 1])
        self.assertEqual(rows[0][0], "header")
        self.assertEqual(rows[0][1], "/proj/a")
        self.assertEqual(rows[0][2], 2)
        self.assertEqual([r[0] for r in rows], ["header", "session", "session"])

    def test_a_new_header_is_inserted_whenever_the_project_changes(self):
        sessions = [
            make_session(0, "/proj/a"),
            make_session(1, "/proj/a"),
            make_session(2, "/proj/b"),
        ]
        rows, row_of_pos = vc.build_display_rows(sessions, [0, 1, 2])
        kinds = [(r[0], r[1] if r[0] == "header" else None) for r in rows]
        self.assertEqual(kinds, [
            ("header", "/proj/a"), ("session", None), ("session", None),
            ("header", "/proj/b"), ("session", None),
        ])

    def test_row_of_pos_maps_visible_position_to_its_row_index(self):
        sessions = [
            make_session(0, "/proj/a"),
            make_session(1, "/proj/b"),
        ]
        rows, row_of_pos = vc.build_display_rows(sessions, [0, 1])
        # position 0 (session idx 0) sits right after its header -> row 1
        self.assertEqual(row_of_pos[0], 1)
        # position 1 (session idx 1) is in a new group -> its own header
        # bumps it to row 3 (header, session, header, session)
        self.assertEqual(row_of_pos[1], 3)

    def test_returning_to_the_same_project_after_a_gap_still_gets_a_new_header(self):
        # get_visible() groups contiguously, so this shouldn't happen in
        # practice, but build_display_rows() itself is dumb/local: it only
        # looks at whether the project differs from the *previous* row.
        sessions = [
            make_session(0, "/proj/a"),
            make_session(1, "/proj/b"),
            make_session(2, "/proj/a"),
        ]
        rows, row_of_pos = vc.build_display_rows(sessions, [0, 1, 2])
        headers = [r for r in rows if r[0] == "header"]
        self.assertEqual(len(headers), 3)

    def test_empty_visible_list_produces_no_rows(self):
        rows, row_of_pos = vc.build_display_rows([], [])
        self.assertEqual(rows, [])
        self.assertEqual(row_of_pos, {})


if __name__ == "__main__":
    unittest.main()
