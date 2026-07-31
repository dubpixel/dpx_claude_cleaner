#!/usr/bin/env python3
from __future__ import annotations
"""
cc-sessions-v2.py -- Interactive Claude Code session manager
Reads titles/summaries from ~/.claude/sessions-index.json (same source
as the /resume picker), so names match exactly what you see in Claude Code.

Keys:
  UP/DOWN or j/k   Navigate
  SPACE            Toggle selection (auto-advances)
  a                Select all visible
  A                Deselect all
  e                Show only empty/stub sessions (0 messages or tiny files)
  /                Filter by title or path text
  ESC              Clear filter
  d / DELETE       Delete selected (or current if none selected)
  q                Quit
  ?                Toggle help
"""

import curses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

SMALL_FILE_BYTES = 2048  # files under this with 0 messages are "empty"


def load_sessions_index(claude_root: Path) -> list[dict]:
    """
    Load ~/.claude/sessions-index.json.
    Returns list of raw index entries, newest-first by fileMtime.
    Falls back to scanning projects/ if index doesn't exist.
    """
    index_path = claude_root / "sessions-index.json"
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            # Could be a list or {"sessions": [...]}
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("sessions", [])
            else:
                entries = []
            # Sort newest-first by fileMtime (ms epoch) or created
            entries.sort(key=lambda e: e.get("fileMtime", 0), reverse=True)
            return entries
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: scan projects/ directory
    return scan_projects(claude_root / "projects")


def scan_projects(projects_root: Path) -> list[dict]:
    """Fallback scanner when sessions-index.json doesn't exist."""
    entries = []
    if not projects_root.exists():
        return entries
    for project_dir in projects_root.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl in project_dir.glob("*.jsonl"):
            name = jsonl.name
            if name.startswith("agent-") or "warmup" in name:
                continue
            stat = jsonl.stat()
            entries.append({
                "sessionId": jsonl.stem,
                "fullPath": str(jsonl),
                "summary": "(no index -- scan fallback)",
                "messageCount": None,
                "fileMtime": stat.st_mtime * 1000,
                "created": None,
            })
    entries.sort(key=lambda e: e.get("fileMtime", 0), reverse=True)
    return entries


def resolve_path(entry: dict, claude_root: Path) -> Path | None:
    """Resolve the actual .jsonl path from an index entry."""
    raw = entry.get("fullPath", "")
    if not raw:
        return None
    # Index stores paths with ~ unexpanded sometimes
    p = Path(raw.replace("~", str(Path.home())))
    if p.exists():
        return p
    # Try relative to claude_root
    name = p.name
    for jsonl in claude_root.rglob(name):
        if jsonl.suffix == ".jsonl":
            return jsonl
    return None  # orphan -- index entry with no file


def build_session_list(claude_root: Path) -> list[dict]:
    """
    Returns a list of session dicts ready for the TUI, newest-first.
    """
    raw_entries = load_sessions_index(claude_root)
    sessions = []

    for e in raw_entries:
        path = resolve_path(e, claude_root)
        file_exists = path is not None and path.exists()

        size_bytes = 0
        mtime = datetime.min.replace(tzinfo=timezone.utc)
        if file_exists:
            try:
                stat = path.stat()
                size_bytes = stat.st_size
                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            except OSError:
                pass
        elif e.get("fileMtime"):
            mtime = datetime.fromtimestamp(e["fileMtime"] / 1000, tz=timezone.utc)

        msg_count = e.get("messageCount")  # may be None if from fallback
        title = (e.get("summary") or "").strip() or (path.stem if path else e.get("sessionId", "?"))

        # Decode project path from fullPath for display
        fp = e.get("fullPath", "")
        project_hint = ""
        if fp:
            parts = Path(fp.replace("~", str(Path.home()))).parts
            # Find the projects dir segment and take the encoded folder after it
            try:
                pi = next(i for i, p in enumerate(parts) if p == "projects")
                encoded = parts[pi + 1] if pi + 1 < len(parts) else ""
                # Decode: leading hyphen + hyphens-as-slashes
                project_hint = "/" + encoded.lstrip("-").replace("-", "/")
            except StopIteration:
                project_hint = fp

        sessions.append({
            "path": path,
            "file_exists": file_exists,
            "title": title,
            "project_hint": project_hint,
            "mtime": mtime,
            "msg_count": msg_count,  # None = unknown
            "size_bytes": size_bytes,
            "selected": False,
            "session_id": e.get("sessionId", ""),
            "_raw": e,  # keep raw entry for index cleanup
        })

    return sessions


def is_empty_session(s: dict) -> bool:
    """Heuristic: session has no real content."""
    if s["msg_count"] is not None:
        return s["msg_count"] == 0
    # Fallback: tiny file probably means only a summary line
    return s["size_bytes"] < SMALL_FILE_BYTES


# ---------------------------------------------------------------------------
# TUI helpers
# ---------------------------------------------------------------------------

def fmt_mtime(dt: datetime) -> str:
    if dt == datetime.min.replace(tzinfo=timezone.utc):
        return "unknown         "
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def fmt_size(b: int) -> str:
    if b == 0:
        return "    - "
    elif b < 1024:
        return f"{b:5}B"
    elif b < 1024 * 1024:
        return f"{b/1024:4.1f}K"
    else:
        return f"{b/1024/1024:4.1f}M"


def fmt_count(n) -> str:
    if n is None:
        return "  ? "
    return f"{n:4d}"


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------

def draw_header(win, width, total, shown, selected, filter_str, empty_only, help_vis):
    win.erase()
    title = " Claude Code Sessions "
    win.addstr(0, 0, title, curses.A_BOLD | curses.A_REVERSE)
    info = f" {shown}/{total}"
    if selected:
        info += f"  [{selected} marked]"
    if empty_only:
        info += "  [empty only]"
    if filter_str:
        info += f"  [{filter_str!r}]"
    try:
        win.addstr(0, len(title), info)
        hint = " ?=help "
        win.addstr(0, width - len(hint) - 1, hint)
    except curses.error:
        pass
    win.noutrefresh()


def draw_help(win, width):
    win.erase()
    lines = [
        "  j/k ↑↓      navigate",
        "  SPACE        toggle select (auto-advance)",
        "  a / A        select all / deselect all",
        "  e            toggle empty-sessions filter",
        "  /            text filter (title or path)",
        "  ESC          clear filter",
        "  d / DEL      delete selected (or current)",
        "  q            quit",
        "  ?            close help",
    ]
    win.addstr(0, 0, " KEYS ".center(width, "─"), curses.A_DIM)
    for i, line in enumerate(lines, 1):
        try:
            win.addstr(i, 0, line, curses.A_DIM)
        except curses.error:
            pass
    win.noutrefresh()


def draw_list(win, sessions, visible, cursor, scroll, height, width):
    win.erase()

    # Fixed column widths
    cw_sel = 3     # [x]
    cw_flag = 2    # E or orphan !
    cw_cnt = 5     # msg count
    cw_sz = 7      # file size
    cw_dt = 17     # date
    fixed = cw_sel + cw_flag + cw_cnt + cw_sz + cw_dt + 4
    cw_title = max(8, width - fixed)

    hdr = (f"{'':3} {'':2} {'msgs':>4} {'size':>6} {'modified':17} "
           f"{'title (from /resume)':<{cw_title}}")
    try:
        win.addstr(0, 0, hdr[:width], curses.A_DIM | curses.A_UNDERLINE)
    except curses.error:
        pass

    view_rows = height - 1
    for row, idx in enumerate(visible[scroll: scroll + view_rows], 1):
        s = sessions[idx]
        is_cur = (idx == visible[cursor]) if cursor < len(visible) else False
        is_sel = s["selected"]
        is_empty = is_empty_session(s)
        is_orphan = not s["file_exists"]

        sel_mark = "[x]" if is_sel else "[ ]"
        flag = "!" if is_orphan else ("E" if is_empty else " ")
        cnt_str = fmt_count(s["msg_count"])
        sz_str = fmt_size(s["size_bytes"])
        dt_str = fmt_mtime(s["mtime"])
        title_t = s["title"][:cw_title]

        line = f"{sel_mark} {flag} {cnt_str} {sz_str} {dt_str} {title_t:<{cw_title}}"
        line = line[:width]

        attr = curses.A_NORMAL
        if is_cur:
            attr |= curses.A_REVERSE
        if is_empty or is_orphan:
            attr |= curses.A_DIM
        if is_sel:
            try:
                attr |= curses.color_pair(1)
            except Exception:
                pass

        try:
            win.addstr(row, 0, line, attr)
        except curses.error:
            pass

    win.noutrefresh()


def draw_detail(win, width, s):
    """One-line detail bar showing project path of current session."""
    win.erase()
    if s:
        hint = f"  {s['project_hint']}"
        try:
            win.addstr(0, 0, hint[:width], curses.A_DIM)
        except curses.error:
            pass
    win.noutrefresh()


def draw_status(win, width, msg=""):
    win.erase()
    text = msg if msg else " SPC=mark  d=delete  /=filter  e=empty  a=all  q=quit  ?=help"
    try:
        win.addstr(0, 0, text[:width], curses.A_REVERSE)
    except curses.error:
        pass
    win.noutrefresh()


def get_filter_input(stdscr, status_win, width, current):
    curses.echo()
    curses.curs_set(1)
    prompt = " Filter: "
    result = current
    while True:
        status_win.erase()
        try:
            status_win.addstr(0, 0, (prompt + result)[:width], curses.A_REVERSE)
        except curses.error:
            pass
        status_win.refresh()
        ch = status_win.getch()
        if ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            break
        elif ch == 27:
            result = ""
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            result = result[:-1]
        elif 32 <= ch < 256:
            result += chr(ch)
    curses.noecho()
    curses.curs_set(0)
    return result


def confirm_delete(stdscr, items):
    height, width = stdscr.getmaxyx()
    lines = [
        "",
        f"  Delete {len(items)} session(s) permanently:",
        "",
    ]
    for s in items[:12]:
        marker = "[ORPHAN] " if not s["file_exists"] else ""
        lines.append(f"    {marker}{s['title'][:60]}")
    if len(items) > 12:
        lines.append(f"    ... and {len(items) - 12} more")
    lines += ["", "  Type YES to confirm: "]
    stdscr.clear()
    for i, line in enumerate(lines):
        try:
            stdscr.addstr(i, 0, line[:width])
        except curses.error:
            pass
    stdscr.refresh()
    curses.echo()
    curses.curs_set(1)
    try:
        ans = stdscr.getstr(len(lines) - 1, len(lines[-1]), 10)
    except Exception:
        ans = b""
    curses.noecho()
    curses.curs_set(0)
    return ans.strip() == b"YES"


def delete_sessions(items, claude_root):
    deleted = 0
    errors = []
    for s in items:
        # Delete the .jsonl file if it exists
        if s["file_exists"] and s["path"]:
            try:
                s["path"].unlink()
                deleted += 1
                # Clean empty project dir
                try:
                    pdir = s["path"].parent
                    if not any(pdir.iterdir()):
                        pdir.rmdir()
                except OSError:
                    pass
            except OSError as ex:
                errors.append(f"{s['path'].name}: {ex}")
                continue
        else:
            deleted += 1  # orphan -- just remove from index

    # Prune sessions-index.json of deleted entries
    index_path = claude_root / "sessions-index.json"
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            deleted_ids = {s["session_id"] for s in items}
            if isinstance(data, list):
                data = [e for e in data if e.get("sessionId") not in deleted_ids]
            elif isinstance(data, dict) and "sessions" in data:
                data["sessions"] = [e for e in data["sessions"]
                                    if e.get("sessionId") not in deleted_ids]
            index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass

    return deleted, errors


def run_tui(stdscr, sessions, claude_root):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_YELLOW, -1)
    except Exception:
        pass

    filter_str = ""
    empty_only = False
    cursor = 0
    scroll = 0
    status_msg = ""
    help_visible = False

    def get_visible():
        idxs = range(len(sessions))
        if empty_only:
            idxs = [i for i in idxs if is_empty_session(sessions[i])]
        if filter_str:
            lo = filter_str.lower()
            idxs = [i for i in idxs
                    if lo in sessions[i]["title"].lower()
                    or lo in sessions[i]["project_hint"].lower()]
        return list(idxs)

    while True:
        height, width = stdscr.getmaxyx()

        header_h = 1
        detail_h = 1
        help_h = 11 if help_visible else 0
        status_h = 1
        list_h = max(3, height - header_h - detail_h - help_h - status_h)

        header_win = stdscr.subwin(header_h, width, 0, 0)
        list_win = stdscr.subwin(list_h, width, header_h, 0)
        detail_win = stdscr.subwin(detail_h, width, header_h + list_h, 0)
        if help_visible:
            help_win = stdscr.subwin(help_h, width, header_h + list_h + detail_h, 0)
        status_win = stdscr.subwin(status_h, width, height - status_h, 0)

        visible = get_visible()

        if visible:
            cursor = max(0, min(cursor, len(visible) - 1))
            view_rows = list_h - 1
            if cursor < scroll:
                scroll = cursor
            elif cursor >= scroll + view_rows:
                scroll = cursor - view_rows + 1
        else:
            cursor = scroll = 0

        n_sel = sum(1 for s in sessions if s["selected"])
        cur_session = sessions[visible[cursor]] if visible and cursor < len(visible) else None

        draw_header(header_win, width, len(sessions), len(visible),
                    n_sel, filter_str, empty_only, help_visible)
        draw_list(list_win, sessions, visible, cursor, scroll, list_h, width)
        draw_detail(detail_win, width, cur_session)
        if help_visible:
            draw_help(help_win, width)
        draw_status(status_win, width, status_msg)
        status_msg = ""

        curses.doupdate()
        ch = stdscr.getch()

        if ch in (ord("q"), ord("Q")):
            break
        elif ch == ord("?"):
            help_visible = not help_visible
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(visible) - 1, cursor + 1) if visible else 0
        elif ch == curses.KEY_PPAGE:
            cursor = max(0, cursor - (list_h - 2))
        elif ch == curses.KEY_NPAGE:
            cursor = min(len(visible) - 1, cursor + (list_h - 2)) if visible else 0
        elif ch == curses.KEY_HOME:
            cursor = 0
        elif ch == curses.KEY_END:
            cursor = max(0, len(visible) - 1)
        elif ch == ord(" "):
            if visible:
                sessions[visible[cursor]]["selected"] = not sessions[visible[cursor]]["selected"]
                cursor = min(len(visible) - 1, cursor + 1)
        elif ch == ord("a"):
            for i in visible:
                sessions[i]["selected"] = True
        elif ch == ord("A"):
            for s in sessions:
                s["selected"] = False
        elif ch == ord("e"):
            empty_only = not empty_only
            cursor = scroll = 0
        elif ch == ord("/"):
            filter_str = get_filter_input(stdscr, status_win, width, filter_str)
            cursor = scroll = 0
        elif ch == 27:
            if filter_str:
                filter_str = ""
                cursor = scroll = 0
            elif empty_only:
                empty_only = False
        elif ch in (ord("d"), curses.KEY_DC):
            targets = [sessions[i] for i in range(len(sessions)) if sessions[i]["selected"]]
            if not targets and visible:
                targets = [sessions[visible[cursor]]]
            if not targets:
                status_msg = " Nothing to delete."
                continue
            if confirm_delete(stdscr, targets):
                deleted, errors = delete_sessions(targets, claude_root)
                gone = {id(s) for s in targets}
                sessions[:] = [s for s in sessions if id(s) not in gone]
                cursor = min(cursor, max(0, len(get_visible()) - 1))
                if errors:
                    status_msg = f" Deleted {deleted}, errors: {'; '.join(errors[:2])}"
                else:
                    status_msg = f" Deleted {deleted} session(s)."
            else:
                status_msg = " Cancelled."
        elif ch == curses.KEY_RESIZE:
            stdscr.clear()


def main():
    claude_root = Path.home() / ".claude"
    if len(sys.argv) > 1:
        claude_root = Path(sys.argv[1])
    elif env := os.environ.get("CLAUDE_ROOT"):
        claude_root = Path(env)

    if not claude_root.exists():
        print(f"Claude root not found: {claude_root}")
        sys.exit(1)

    print(f"Loading sessions from {claude_root} ...")
    sessions = build_session_list(claude_root)

    if not sessions:
        print("No sessions found.")
        sys.exit(0)

    n_empty = sum(1 for s in sessions if is_empty_session(s))
    n_orphan = sum(1 for s in sessions if not s["file_exists"])
    print(f"Found {len(sessions)} sessions  ({n_empty} empty, {n_orphan} orphan index entries)")
    print("Launching UI...")

    try:
        curses.wrapper(run_tui, sessions, claude_root)
    except KeyboardInterrupt:
        pass

    print("Done.")


if __name__ == "__main__":
    main()
