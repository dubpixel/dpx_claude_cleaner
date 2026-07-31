#!/usr/bin/env python3
"""
cc-sessions-v1.py -- Interactive Claude Code session manager
Lists all sessions under ~/.claude/projects/, shows titles/summaries,
lets you browse and delete sessions that are empty or no longer needed.

Keys:
  UP/DOWN or j/k   Navigate
  SPACE            Toggle selection
  a                Select all
  d / DELETE       Delete selected (or current if none selected)
  /                Filter by text
  ESC              Clear filter / quit
  q                Quit
  ?                Toggle help
"""

import curses
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def decode_project_path(folder_name: str) -> str:
    """Convert encoded folder name back to a readable project path."""
    # Claude encodes slashes as hyphens and prefixes with a hyphen
    # e.g. /Users/me/code/myapp -> -Users-me-code-myapp
    # We just strip a leading hyphen and swap remaining hyphens to slashes
    # but only the ones that were originally slashes. Since both hyphens
    # in real paths and slash-separators both become hyphens, we can't
    # perfectly reverse it, but a best-effort decode is readable enough.
    decoded = folder_name.lstrip("-").replace("-", "/")
    return "/" + decoded if decoded else folder_name


def get_session_title(jsonl_path: Path) -> str:
    """
    Extract a human-readable title from a session file.
    Priority:
      1. type==summary .summary field
      2. First type==user message content (first 120 chars)
      3. Filename stem
    """
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type", "")
                if t == "summary":
                    s = obj.get("summary", "").strip()
                    if s:
                        return s
                elif t == "user":
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, str):
                        snippet = content.strip().replace("\n", " ")
                        return snippet[:120] + ("..." if len(snippet) > 120 else "")
                    elif isinstance(content, list):
                        # Tool result list; try to grab text from first block
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                t2 = block.get("text", "").strip().replace("\n", " ")
                                return t2[:120] + ("..." if len(t2) > 120 else "")
    except (OSError, PermissionError):
        pass
    return jsonl_path.stem  # fallback: UUID


def count_messages(jsonl_path: Path) -> int:
    """Count user+assistant message lines (skips summary and snapshots)."""
    count = 0
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") in ("user", "assistant"):
                    count += 1
    except (OSError, PermissionError):
        pass
    return count


def get_mtime(path: Path) -> datetime:
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc)


def collect_sessions(root: Path) -> list[dict]:
    """
    Walk ~/.claude/projects/ and return a list of session dicts, sorted
    newest-first by mtime.
    """
    sessions = []
    if not root.exists():
        return sessions

    for project_dir in sorted(root.iterdir()):
        if not project_dir.is_dir():
            continue
        project_label = decode_project_path(project_dir.name)

        for jsonl in project_dir.rglob("*.jsonl"):
            # Skip agent and warmup files (internal Claude Code ephemera)
            name = jsonl.name
            if name.startswith("agent-") or "warmup" in name:
                continue

            mtime = get_mtime(jsonl)
            msg_count = count_messages(jsonl)
            title = get_session_title(jsonl)
            size_bytes = jsonl.stat().st_size if jsonl.exists() else 0

            sessions.append({
                "path": jsonl,
                "project_label": project_label,
                "project_dir": project_dir,
                "title": title,
                "mtime": mtime,
                "msg_count": msg_count,
                "size_bytes": size_bytes,
                "selected": False,
            })

    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


# ---------------------------------------------------------------------------
# TUI helpers
# ---------------------------------------------------------------------------

def fmt_mtime(dt: datetime) -> str:
    if dt == datetime.min.replace(tzinfo=timezone.utc):
        return "unknown"
    # Show as local time
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def fmt_size(b: int) -> str:
    if b < 1024:
        return f"{b}B"
    elif b < 1024 * 1024:
        return f"{b/1024:.1f}K"
    else:
        return f"{b/1024/1024:.1f}M"


# ---------------------------------------------------------------------------
# Main TUI
# ---------------------------------------------------------------------------

def draw_header(win, width: int, total: int, shown: int, selected: int,
                filter_str: str, help_visible: bool):
    win.erase()
    title = " Claude Code Session Manager "
    win.addstr(0, 0, title, curses.A_BOLD | curses.A_REVERSE)
    info = f" {shown}/{total} sessions"
    if selected:
        info += f"  [{selected} selected]"
    if filter_str:
        info += f"  filter: {filter_str!r}"
    win.addstr(0, len(title), info)

    hint = " ? help" if not help_visible else " ? close help"
    try:
        win.addstr(0, width - len(hint) - 1, hint)
    except curses.error:
        pass
    win.noutrefresh()


def draw_help(win, width: int):
    win.erase()
    lines = [
        "  UP/k DOWN/j   navigate",
        "  SPACE          toggle select",
        "  a              select all visible",
        "  A              deselect all",
        "  /              start filter",
        "  ESC            clear filter",
        "  d / DEL        delete selected (or current)",
        "  q              quit",
        "  ?              toggle this help",
    ]
    win.addstr(0, 0, " KEYS ".center(width, "─"), curses.A_DIM)
    for i, line in enumerate(lines, 1):
        try:
            win.addstr(i, 0, line, curses.A_DIM)
        except curses.error:
            pass
    win.noutrefresh()


def draw_list(win, sessions: list[dict], visible: list[int],
              cursor: int, scroll: int, height: int, width: int):
    win.erase()

    col_w_sel = 2       # checkbox
    col_w_flag = 2      # E=empty indicator
    col_w_count = 5     # msg count
    col_w_size = 6      # file size
    col_w_date = 17     # date
    fixed = col_w_sel + col_w_flag + col_w_count + col_w_size + col_w_date + 4  # separators
    col_w_title = max(10, width - fixed - 1)

    # Column header
    hdr = (f"{'':2} {'':2} {'#':>4} {'size':>5} {'last modified':17} "
           f"{'title / first message':<{col_w_title}}")
    try:
        win.addstr(0, 0, hdr[:width], curses.A_DIM | curses.A_UNDERLINE)
    except curses.error:
        pass

    for row, idx in enumerate(visible[scroll: scroll + height - 1], 1):
        s = sessions[idx]
        is_cursor = (idx == visible[cursor] if cursor < len(visible) else False)
        is_selected = s["selected"]
        is_empty = s["msg_count"] == 0

        sel_mark = "[x]" if is_selected else "[ ]"
        flag = "E" if is_empty else " "
        count_str = str(s["msg_count"]) if not is_empty else "-"
        size_str = fmt_size(s["size_bytes"])
        date_str = fmt_mtime(s["mtime"])
        title_trunc = s["title"][:col_w_title]

        line = (f"{sel_mark[:2]} {flag} {count_str:>4} {size_str:>5} {date_str:17} "
                f"{title_trunc:<{col_w_title}}")
        line = line[:width]

        attr = curses.A_NORMAL
        if is_cursor:
            attr |= curses.A_REVERSE
        if is_empty:
            attr |= curses.A_DIM
        if is_selected:
            try:
                attr |= curses.color_pair(1)
            except Exception:
                pass

        try:
            win.addstr(row, 0, line, attr)
        except curses.error:
            pass

    win.noutrefresh()


def draw_statusbar(win, width: int, message: str = ""):
    win.erase()
    default = (" SPC=toggle  d=delete  /=filter  q=quit  ?=help  "
               "a=sel-all  A=desel-all")
    text = message if message else default
    try:
        win.addstr(0, 0, text[:width], curses.A_REVERSE)
    except curses.error:
        pass
    win.noutrefresh()


def confirm_delete(stdscr, items: list[dict]) -> bool:
    """Full-screen confirmation prompt before deleting."""
    height, width = stdscr.getmaxyx()
    msg_lines = [
        "",
        f"  About to permanently delete {len(items)} session file(s):",
        "",
    ]
    for s in items[:10]:
        msg_lines.append(f"    {s['path'].name}  ({s['title'][:50]})")
    if len(items) > 10:
        msg_lines.append(f"    ... and {len(items)-10} more")
    msg_lines += ["", "  Type YES to confirm, anything else to cancel: "]

    stdscr.clear()
    for i, line in enumerate(msg_lines):
        try:
            stdscr.addstr(i, 0, line[:width])
        except curses.error:
            pass
    stdscr.refresh()

    curses.echo()
    curses.curs_set(1)
    try:
        ans = stdscr.getstr(len(msg_lines) - 1, len(msg_lines[-1]), 10)
    except Exception:
        ans = b""
    curses.noecho()
    curses.curs_set(0)
    return ans.strip() == b"YES"


def delete_sessions(items: list[dict]) -> tuple[int, list[str]]:
    """Delete session files. Returns (deleted_count, error_list)."""
    deleted = 0
    errors = []
    for s in items:
        try:
            s["path"].unlink()
            deleted += 1
            # Clean up empty project dir
            try:
                pdir = s["path"].parent
                remaining = list(pdir.iterdir())
                if not remaining:
                    pdir.rmdir()
            except OSError:
                pass
        except OSError as e:
            errors.append(f"{s['path'].name}: {e}")
    return deleted, errors


def get_filter_input(stdscr, status_win, width: int, current: str) -> str:
    """Read a filter string from the status bar."""
    curses.echo()
    curses.curs_set(1)
    prompt = " Filter: "
    status_win.erase()
    try:
        status_win.addstr(0, 0, (prompt + current)[:width], curses.A_REVERSE)
    except curses.error:
        pass
    status_win.refresh()
    # Let user edit in place; we just collect chars until Enter or ESC
    result = current
    while True:
        ch = status_win.getch()
        if ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            break
        elif ch == 27:  # ESC clears
            result = ""
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            result = result[:-1]
        elif 32 <= ch < 256:
            result += chr(ch)
        prompt_line = (prompt + result)[:width]
        status_win.erase()
        try:
            status_win.addstr(0, 0, prompt_line, curses.A_REVERSE)
        except curses.error:
            pass
        status_win.refresh()
    curses.noecho()
    curses.curs_set(0)
    return result


def run_tui(stdscr, sessions: list[dict]):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_YELLOW, -1)
    except Exception:
        pass

    filter_str = ""
    cursor = 0      # index into visible[]
    scroll = 0      # top of viewport into visible[]
    status_msg = ""
    help_visible = False

    def get_visible():
        if not filter_str:
            return list(range(len(sessions)))
        lo = filter_str.lower()
        return [
            i for i, s in enumerate(sessions)
            if lo in s["title"].lower() or lo in s["project_label"].lower()
        ]

    while True:
        height, width = stdscr.getmaxyx()

        # Layout heights
        header_h = 1
        help_h = 11 if help_visible else 0
        status_h = 1
        list_h = max(3, height - header_h - help_h - status_h)

        # Sub-windows
        header_win = stdscr.subwin(header_h, width, 0, 0)
        list_win = stdscr.subwin(list_h, width, header_h, 0)
        if help_visible:
            help_win = stdscr.subwin(help_h, width, header_h + list_h, 0)
        status_win = stdscr.subwin(status_h, width, height - status_h, 0)

        visible = get_visible()

        # Clamp cursor
        if visible:
            cursor = max(0, min(cursor, len(visible) - 1))
            # Scroll to keep cursor in view (list_h - 1 usable rows after header)
            view_rows = list_h - 1
            if cursor < scroll:
                scroll = cursor
            elif cursor >= scroll + view_rows:
                scroll = cursor - view_rows + 1
        else:
            cursor = 0
            scroll = 0

        n_selected = sum(1 for s in sessions if s["selected"])

        draw_header(header_win, width, len(sessions), len(visible),
                    n_selected, filter_str, help_visible)
        draw_list(list_win, sessions, visible, cursor, scroll, list_h, width)
        if help_visible:
            draw_help(help_win, width)
        draw_statusbar(status_win, width, status_msg)
        status_msg = ""  # clear after one frame

        curses.doupdate()

        ch = stdscr.getch()

        if ch in (ord("q"), ord("Q")):
            break

        elif ch in (ord("?"),):
            help_visible = not help_visible

        elif ch in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)

        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(visible) - 1, cursor + 1) if visible else 0

        elif ch == curses.KEY_PPAGE:  # Page Up
            cursor = max(0, cursor - (list_h - 2))

        elif ch == curses.KEY_NPAGE:  # Page Down
            cursor = min(len(visible) - 1, cursor + (list_h - 2)) if visible else 0

        elif ch == curses.KEY_HOME:
            cursor = 0

        elif ch == curses.KEY_END:
            cursor = max(0, len(visible) - 1)

        elif ch == ord(" "):
            if visible:
                s = sessions[visible[cursor]]
                s["selected"] = not s["selected"]
                cursor = min(len(visible) - 1, cursor + 1)  # auto-advance

        elif ch == ord("a"):
            for idx in visible:
                sessions[idx]["selected"] = True

        elif ch == ord("A"):
            for s in sessions:
                s["selected"] = False

        elif ch == ord("/"):
            filter_str = get_filter_input(stdscr, status_win, width, filter_str)
            cursor = 0
            scroll = 0

        elif ch == 27:  # ESC
            if filter_str:
                filter_str = ""
                cursor = 0
                scroll = 0

        elif ch in (ord("d"), curses.KEY_DC, curses.KEY_BACKSPACE):
            # Collect targets: selected, or just cursor if nothing selected
            targets = [sessions[i] for i in range(len(sessions)) if sessions[i]["selected"]]
            if not targets and visible:
                targets = [sessions[visible[cursor]]]

            if not targets:
                status_msg = " Nothing to delete."
                continue

            if confirm_delete(stdscr, targets):
                deleted, errors = delete_sessions(targets)
                # Remove deleted from sessions list in-place
                deleted_paths = {s["path"] for s in targets if not errors or
                                 not any(s["path"].name in e for e in errors)}
                sessions[:] = [s for s in sessions if s["path"] not in deleted_paths]
                cursor = min(cursor, max(0, len(get_visible()) - 1))
                if errors:
                    status_msg = f" Deleted {deleted}, errors: {'; '.join(errors[:2])}"
                else:
                    status_msg = f" Deleted {deleted} session(s)."
            else:
                status_msg = " Cancelled."

        # resize: just redraw
        elif ch == curses.KEY_RESIZE:
            stdscr.clear()


def main():
    root = Path.home() / ".claude" / "projects"

    # Allow override via argument or env var
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    elif env_root := os.environ.get("CLAUDE_ROOT"):
        root = Path(env_root) / "projects"

    if not root.exists():
        print(f"No Claude Code sessions found at {root}")
        print("Is Claude Code installed? Expected path: ~/.claude/projects/")
        sys.exit(1)

    print(f"Scanning {root} ...")
    sessions = collect_sessions(root)

    if not sessions:
        print("No session files found.")
        sys.exit(0)

    print(f"Found {len(sessions)} sessions. Launching UI...")

    try:
        curses.wrapper(run_tui, sessions)
    except KeyboardInterrupt:
        pass

    print("Done.")


if __name__ == "__main__":
    main()
