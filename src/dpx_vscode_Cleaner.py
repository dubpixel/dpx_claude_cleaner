#!/usr/bin/env python3
# ================================================================================
# PYTHON SCRIPT - VS Code Copilot Chat session manager (TUI + CLI modes)
# ================================================================================
# PROJECT: dpx_claude_cleaner (vazzle)
# ================================================================================
#
# File: dpx_vscode_Cleaner.py
# Purpose: Browse, rename, delete, and export GitHub Copilot Chat sessions
#          stored by VS Code under workspaceStorage/. See
#          VSCODE-CHAT-RECOVERY.md for the full on-disk format this tool
#          reads/writes, and VAZZLE_PLAN.md for the design.
# Dependencies: Python 3.10+ stdlib only (curses, argparse, json, pathlib)
#
# Companion to dpx_claude_Cleaner.py (zazzle) -- same shape, independent
# code. Do not import from or share state with that file.
#
# ================================================================================
"""
dpx_vscode_Cleaner.py
======================
VS Code Copilot Chat session manager ("vazzle").

MODES (first positional arg, default: tui)
  tui         Interactive TUI: list, filter, delete, rename, export
  analyze     Print a summary report and exit
  help        Print this help

USAGE
  python3 src/dpx_vscode_Cleaner.py [mode] [--root "~/Library/Application Support/Code/User"]
  vazzle [mode] [--root ...]     (after scripts/deploy_local_vazzle.sh)

ENVIRONMENT
  VSCODE_USER_ROOT   Override path to VS Code's User directory

KEYS (TUI)
  j/k  ↑↓        navigate
  SPACE           toggle mark (auto-advance)
  a / A           mark all visible / unmark all
  o               toggle "orphan only" filter (workspace folder gone)
  /               text filter
  ESC             clear active filter
  r               rename current session (customTitle)
  x               export marked (or current) sessions to markdown
  d / DEL         delete marked (or current)
  q               quit
  ?               toggle help pane

COLUMN FLAGS
  !   orphan (workspace folder no longer exists on disk)
  J   .jsonl (patch-log) format, vs plain .json
"""
from __future__ import annotations

import curses
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKSPACE_JSON = "workspace.json"
CHAT_SESSIONS_DIR = "chatSessions"
CHAT_EDITING_SESSIONS_DIR = "chatEditingSessions"

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION") \
        .read_text().strip()
except FileNotFoundError:
    __version__ = "0.0.0-unknown"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def default_vscode_root() -> Path:
    """
    macOS-only for now (see VAZZLE_PLAN.md "Not doing" -- revisit if this
    ever needs to run on Linux/Windows, which use different base dirs).
    """
    return Path.home() / "Library" / "Application Support" / "Code" / "User"


def workspace_uri_to_path(uri: str) -> str | None:
    """
    Decode a workspace.json "workspace" field (a file:// URI, percent-encoded)
    into a real filesystem path. Exact -- no lossy hyphen-decoding needed,
    unlike zazzle's decode_encoded().
    """
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return unquote(parsed.path)


def get_workspace_path(workspace_dir: Path) -> str | None:
    """Read workspace.json in a workspaceStorage/<hash>/ dir, return the real path."""
    wj = workspace_dir / WORKSPACE_JSON
    if not wj.exists():
        return None
    try:
        data = json.loads(wj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return workspace_uri_to_path(data.get("workspace", ""))


# ---------------------------------------------------------------------------
# Chat session reconstruction
# ---------------------------------------------------------------------------

def _set_path(state: dict, path: list, value) -> None:
    """Set `value` at `path` (list of str/int segments) inside `state`,
    creating intermediate dicts/lists as needed."""
    node = state
    for seg in path[:-1]:
        if isinstance(seg, int):
            while len(node) <= seg:
                node.append({})
            nxt = node[seg]
        else:
            nxt = node.setdefault(seg, {})
        node = nxt
    last = path[-1]
    if isinstance(last, int):
        while len(node) <= last:
            node.append(None)
        node[last] = value
    else:
        node[last] = value


def _request_id(req: dict) -> str | None:
    return req.get("requestId") if isinstance(req, dict) else None


def _response_len(req: dict) -> int:
    resp = req.get("response") if isinstance(req, dict) else None
    return len(resp) if isinstance(resp, list) else 0


def _archive_requests(archive: dict, requests) -> None:
    """
    Snapshot a live `requests` array into `archive` (keyed by requestId),
    keeping whichever version of a given request has the fuller `response`
    array -- a response streams in over several patches before the next
    compaction wipes the live array. See VSCODE-CHAT-RECOVERY.md.
    """
    if not isinstance(requests, list):
        return
    for req in requests:
        rid = _request_id(req)
        if rid is None:
            continue
        existing = archive.get(rid)
        if existing is None or _response_len(req) >= _response_len(existing):
            archive[rid] = req


def reconstruct_jsonl_session(path: Path) -> dict:
    """
    Replay a .jsonl patch-log chat session file, correctly recovering full
    history across compaction events (see VSCODE-CHAT-RECOVERY.md section
    3-4). Returns a dict shaped like the flat .json format, with
    `requests` replaced by the merged archive sorted by timestamp.
    """
    state: dict = {}
    archive: dict = {}

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = obj.get("kind")
            if kind == 0:
                v = obj.get("v", {})
                if isinstance(v, dict):
                    state = v
                continue

            k = obj.get("k")
            v = obj.get("v")
            if not isinstance(k, list) or not k:
                continue

            if k == ["requests"]:
                _archive_requests(archive, state.get("requests"))

            _set_path(state, k, v)

    # Final snapshot for whatever's still live and never got compacted.
    _archive_requests(archive, state.get("requests"))

    merged = sorted(
        archive.values(),
        key=lambda r: (r.get("timestamp") or 0),
    )
    state["requests"] = merged
    return state


def load_chat_session(path: Path) -> dict:
    """Load a chat session file, either format, into the flat dict shape."""
    if path.suffix == ".jsonl":
        return reconstruct_jsonl_session(path)
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Text extraction (markdown export)
# ---------------------------------------------------------------------------

def _extract_response_text(response) -> str:
    if not isinstance(response, list):
        return ""
    parts = []
    for part in response:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind")
        if kind == "markdownContent":
            content = part.get("content")
            if isinstance(content, dict):
                parts.append(content.get("value", ""))
            elif isinstance(content, str):
                parts.append(content)
        elif kind == "toolInvocationSerialized":
            msg = part.get("pastTenseMessage") or part.get("invocationMessage")
            if isinstance(msg, dict):
                val = msg.get("value", "")
                if val:
                    parts.append(f"_[tool] {val}_")
        elif kind == "thinking":
            val = part.get("value", "")
            if val:
                parts.append(f"_[thinking] {val}_")
    return "\n\n".join(p for p in parts if p)


def session_title(state: dict, fallback: str) -> tuple[str, bool]:
    ct = (state.get("customTitle") or "").strip()
    if ct:
        return ct, True
    requests = state.get("requests") or []
    for req in requests:
        msg = req.get("message") if isinstance(req, dict) else None
        text = (msg or {}).get("text", "") if isinstance(msg, dict) else ""
        text = text.strip()
        if text:
            snippet = text.replace("\n", " ")
            return snippet[:120] + ("..." if len(snippet) > 120 else ""), False
    return fallback, False


def render_markdown(state: dict, title: str) -> str:
    lines = [f"# {title}", ""]
    created = state.get("creationDate")
    if created:
        lines.append(f"_Created: {fmt_epoch_ms(created)}_")
        lines.append("")
    for req in state.get("requests") or []:
        msg = req.get("message") if isinstance(req, dict) else None
        user_text = (msg or {}).get("text", "") if isinstance(msg, dict) else ""
        lines.append("## USER:")
        lines.append(user_text or "_(empty)_")
        lines.append("")
        resp_text = _extract_response_text(req.get("response"))
        lines.append("### ASSISTANT:")
        lines.append(resp_text or "_(empty)_")
        lines.append("")
    return "\n".join(lines)


def fmt_epoch_ms(ms) -> str:
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) \
            .astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "unknown"


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def collect_all_sessions(vscode_root: Path) -> list[dict]:
    """
    Walk workspaceStorage/<hash>/chatSessions/*.json[l] and build a unified
    session list. No index file exists here (unlike zazzle's
    sessions-index.json) -- workspace.json + a direct filesystem existence
    check is the whole story, and it's exact.
    """
    storage_root = vscode_root / "workspaceStorage"
    if not storage_root.exists():
        return []

    sessions: list[dict] = []

    for ws_dir in sorted(storage_root.iterdir()):
        if not ws_dir.is_dir():
            continue
        chat_dir = ws_dir / CHAT_SESSIONS_DIR
        if not chat_dir.is_dir():
            continue

        project_path = get_workspace_path(ws_dir)
        project_exists = bool(project_path) and Path(project_path).exists()

        for f in sorted(chat_dir.iterdir()):
            if f.suffix not in (".json", ".jsonl"):
                continue
            session_id = f.stem
            fmt = "jsonl" if f.suffix == ".jsonl" else "json"

            try:
                state = load_chat_session(f)
            except (OSError, PermissionError):
                state = {}

            title, title_authoritative = session_title(state, fallback=session_id)
            requests = state.get("requests") or []
            turn_count = len(requests)

            stat = f.stat()
            editing_dir = ws_dir / CHAT_EDITING_SESSIONS_DIR / session_id

            sessions.append(dict(
                session_id=session_id,
                workspace_hash=ws_dir.name,
                path=f,
                editing_dir=editing_dir if editing_dir.is_dir() else None,
                project_path=project_path or "(unknown workspace)",
                project_exists=project_exists,
                title=title,
                title_from_index=title_authoritative,
                creation_date=epoch_ms_to_dt(state.get("creationDate")),
                last_message_date=epoch_ms_to_dt(state.get("lastMessageDate")),
                turn_count=turn_count,
                size_bytes=stat.st_size,
                mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                is_orphan=not project_exists,
                format=fmt,
                selected=False,
            ))

    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def epoch_ms_to_dt(ms) -> datetime:
    if not ms:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.min.replace(tzinfo=timezone.utc)


def is_empty(s: dict) -> bool:
    return s["turn_count"] == 0


def is_orphan(s: dict) -> bool:
    return s["is_orphan"]


# ---------------------------------------------------------------------------
# Analyze mode
# ---------------------------------------------------------------------------

def cmd_analyze(sessions: list[dict]) -> None:
    total = len(sessions)
    empty = sum(1 for s in sessions if is_empty(s))
    orphan = sum(1 for s in sessions if is_orphan(s))
    total_bytes = sum(s["size_bytes"] for s in sessions)

    by_project: dict[str, list] = {}
    for s in sessions:
        by_project.setdefault(s["project_path"], []).append(s)

    print(f"\n{'='*60}")
    print(f"  VS Code Copilot Chat Session Analysis")
    print(f"{'='*60}")
    print(f"  Total sessions : {total}")
    print(f"  Empty          : {empty}")
    print(f"  Orphan (workspace gone): {orphan}")
    print(f"  Total size     : {total_bytes/1024/1024:.1f} MB")
    print(f"\n{'─'*60}")
    print(f"  By project ({len(by_project)} workspaces):")
    print(f"{'─'*60}")

    for label, ss in sorted(by_project.items(), key=lambda x: -len(x[1])):
        sz = sum(s["size_bytes"] for s in ss)
        n_empty = sum(1 for s in ss if is_empty(s))
        n_orphan = sum(1 for s in ss if is_orphan(s))
        flags = []
        if n_empty:
            flags.append(f"{n_empty}E")
        if n_orphan:
            flags.append(f"{n_orphan}!")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"  {len(ss):3d} sessions  {sz/1024:.0f}K  {label}{flag_str}")

    print()


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def rename_session(s: dict, new_title: str) -> str | None:
    """
    Set customTitle.
      .json : rewrite the field in place (whole-file rewrite, same risk
              profile as zazzle's summary-line injection).
      .jsonl: append a new patch line rather than rewriting the file --
              consistent with the format being an append-only patch log,
              same spirit as zazzle never rewriting .jsonl bodies.
    """
    new_title = new_title.strip()
    if not new_title:
        return "Empty title"

    try:
        if s["format"] == "json":
            data = json.loads(s["path"].read_text(encoding="utf-8"))
            data["customTitle"] = new_title
            s["path"].write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            patch_line = json.dumps({
                "kind": 1,
                "k": ["customTitle"],
                "v": new_title,
            }) + "\n"
            with s["path"].open("a", encoding="utf-8") as fh:
                fh.write(patch_line)
    except (OSError, json.JSONDecodeError) as ex:
        return str(ex)

    s["title"] = new_title
    s["title_from_index"] = True
    return None


def delete_sessions(targets: list[dict]) -> tuple[int, list[str]]:
    """
    Delete chat session files and their matching chatEditingSessions/<uuid>/
    directory (the file-edit history tied to the same chat -- leaving it
    behind is the same kind of orphaned-data problem this tool exists to
    clean up).
    """
    deleted = 0
    errors = []
    for s in targets:
        try:
            s["path"].unlink()
            deleted += 1
        except OSError as ex:
            errors.append(f"{s['path'].name}: {ex}")
            continue
        if s.get("editing_dir"):
            try:
                shutil.rmtree(s["editing_dir"])
            except OSError as ex:
                errors.append(f"{s['editing_dir'].name}: {ex}")
    return deleted, errors


def export_sessions_markdown(targets: list[dict], dest_dir: Path) -> tuple[int, list[str]]:
    """
    Bulk-dump reconstructed sessions to markdown files under dest_dir.
    No AI summarization in v1 -- plain recovered transcript per session.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    errors = []
    for s in targets:
        try:
            state = load_chat_session(s["path"])
            md = render_markdown(state, s["title"])
            safe_name = "".join(c if c.isalnum() or c in " -_" else "_"
                                 for c in s["title"])[:80].strip() or s["session_id"]
            out = dest_dir / f"{safe_name}-{s['session_id'][:8]}.md"
            out.write_text(md, encoding="utf-8")
            written += 1
        except OSError as ex:
            errors.append(f"{s['session_id']}: {ex}")
    return written, errors


def default_export_dir(s: dict) -> Path:
    """
    Prefer writing into the live project folder itself
    (<project>/_chat-history/), so a later Claude Code session there can
    just read it -- this repo already established that exact convention
    (see VSCODE-CHAT-RECOVERY.md). Falls back to a fixed location when the
    project folder is gone (orphan).
    """
    if s["project_exists"]:
        return Path(s["project_path"]) / "_chat-history"
    return Path.home() / "vazzle-exports"


# ---------------------------------------------------------------------------
# TUI formatting helpers
# ---------------------------------------------------------------------------

def fmt_dt(dt: datetime) -> str:
    if dt == datetime.min.replace(tzinfo=timezone.utc) or dt.timestamp() < 1:
        return "unknown         "
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def fmt_sz(b: int) -> str:
    if b == 0:
        return "     -"
    if b < 1024:
        return f"{b:5}B"
    if b < 1024 * 1024:
        return f"{b/1024:4.1f}K"
    return f"{b/1024/1024:4.1f}M"


def fmt_ct(n) -> str:
    return f"{n:4d}" if n is not None else "   ?"


# ---------------------------------------------------------------------------
# TUI widgets
# ---------------------------------------------------------------------------

def draw_header(w, width, total, shown, marked, filter_str, orphan_only, help_vis):
    w.erase()
    title = f" vazzle v{__version__} "
    w.addstr(0, 0, title, curses.A_BOLD | curses.A_REVERSE)
    info = f" {shown}/{total} sessions"
    if marked:
        info += f"  [{marked} marked]"
    if orphan_only:
        info += "  [orphans]"
    if filter_str:
        info += f"  /{filter_str}"
    try:
        w.addstr(0, len(title), info)
        hint = " ?=help "
        w.addstr(0, width - len(hint) - 1, hint)
    except curses.error:
        pass
    w.noutrefresh()


def draw_help(w, width):
    w.erase()
    lines = [
        "  j/k ↑↓     navigate              r    rename current",
        "  SPACE       mark/unmark (advance) x    export marked/current to markdown",
        "  a / A       mark all / unmark all d    delete marked or current",
        "  o           orphan sessions only",
        "  /           text filter",
        "  q           quit                  ?    close help",
        "  FLAGS:  E=empty  !=orphan (workspace gone)  J=.jsonl format",
    ]
    w.addstr(0, 0, " KEYS ".center(width, "─"), curses.A_DIM)
    for i, line in enumerate(lines, 1):
        try:
            w.addstr(i, 0, line[:width], curses.A_DIM)
        except curses.error:
            pass
    w.noutrefresh()


def draw_list(w, sessions, visible, cursor, scroll, height, width):
    w.erase()
    cw_sel = 3
    cw_flag = 4
    cw_cnt = 5
    cw_sz = 7
    cw_dt = 17
    fixed = cw_sel + cw_flag + cw_cnt + cw_sz + cw_dt + 5
    cw_title = max(8, width - fixed)

    hdr = (f"{'':3} {'flg':4} {'turn':>4} {'size':>6} {'modified':17} "
           f"{'title':<{cw_title}}")
    try:
        w.addstr(0, 0, hdr[:width], curses.A_DIM | curses.A_UNDERLINE)
    except curses.error:
        pass

    view_rows = height - 1
    for row, idx in enumerate(visible[scroll: scroll + view_rows], 1):
        s = sessions[idx]
        is_cur = (visible[cursor] == idx) if cursor < len(visible) else False
        sel_mark = "[x]" if s["selected"] else "[ ]"
        flags = ("E" if is_empty(s) else " ") + \
                ("!" if is_orphan(s) else " ") + \
                ("J" if s["format"] == "jsonl" else " ") + \
                (" ")
        cnt = fmt_ct(s["turn_count"])
        sz = fmt_sz(s["size_bytes"])
        dt = fmt_dt(s["mtime"])
        tit = s["title"][:cw_title]

        line = f"{sel_mark} {flags} {cnt} {sz} {dt} {tit:<{cw_title}}"
        line = line[:width]

        attr = curses.A_NORMAL
        if is_cur:
            attr |= curses.A_REVERSE
        if is_empty(s) or is_orphan(s):
            attr |= curses.A_DIM
        if s["selected"]:
            try:
                attr |= curses.color_pair(1)
            except Exception:
                pass
        try:
            w.addstr(row, 0, line, attr)
        except curses.error:
            pass
    w.noutrefresh()


def draw_detail(w, width, s):
    w.erase()
    if s:
        txt = f"  {s['project_path']}"
        txt += f"  [{s['session_id'][:8]}]"
        try:
            w.addstr(0, 0, txt[:width], curses.A_DIM)
        except curses.error:
            pass
    w.noutrefresh()


def draw_status(w, width, msg=""):
    w.erase()
    default = " SPC=mark  d=del  r=rename  x=export  /=filter  o=orphan  q=quit"
    try:
        w.addstr(0, 0, (msg or default)[:width], curses.A_REVERSE)
    except curses.error:
        pass
    w.noutrefresh()


# ---------------------------------------------------------------------------
# TUI inline input helper (independent copy of zazzle's -- see AGENTS.md
# hard constraint: no shared code between the two tools)
# ---------------------------------------------------------------------------

def readline_inline(w, width, prompt: str, default: str = "") -> str:
    """Read a line from the status bar. Returns empty string on ESC."""
    curses.echo()
    curses.curs_set(1)
    result = default
    while True:
        w.erase()
        display = (prompt + result)[:width - 1]
        try:
            w.addstr(0, 0, display, curses.A_REVERSE)
        except curses.error:
            pass
        w.refresh()
        ch = w.getch()
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


def confirm_delete_tui(stdscr, items: list[dict]) -> bool:
    height, width = stdscr.getmaxyx()
    lines = ["", f"  Delete {len(items)} session(s) permanently:", ""]
    for s in items[:14]:
        marker = "[ORPHAN] " if is_orphan(s) else ""
        lines.append(f"    {marker}{s['title'][:58]}")
    if len(items) > 14:
        lines.append(f"    ... and {len(items) - 14} more")
    lines.append("")

    stdscr.clear()
    for i, line in enumerate(lines):
        try:
            stdscr.addstr(i, 0, line[:width])
        except curses.error:
            pass
    stdscr.refresh()

    prompt_row = min(len(lines), height - 1)
    input_win = stdscr.subwin(1, width, prompt_row, 0)
    ans = readline_inline(input_win, width, "Type YES to confirm, anything else cancels: ")
    return ans.strip() == "YES"


# ---------------------------------------------------------------------------
# Main TUI loop
# ---------------------------------------------------------------------------

def run_tui(stdscr, sessions: list[dict]):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_YELLOW, -1)
    except Exception:
        pass

    filter_str = ""
    orphan_only = False
    cursor = 0
    scroll = 0
    status_msg = ""
    help_visible = False

    def get_visible() -> list[int]:
        idxs = range(len(sessions))
        if orphan_only:
            idxs = [i for i in idxs if is_orphan(sessions[i])]
        else:
            idxs = list(idxs)
        if filter_str:
            lo = filter_str.lower()
            idxs = [i for i in idxs
                    if lo in sessions[i]["title"].lower()
                    or lo in sessions[i]["project_path"].lower()]
        return list(idxs)

    while True:
        height, width = stdscr.getmaxyx()
        header_h = 1
        detail_h = 1
        help_h = 8 if help_visible else 0
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

        n_marked = sum(1 for s in sessions if s["selected"])
        cur_s = sessions[visible[cursor]] if visible and cursor < len(visible) else None

        draw_header(header_win, width, len(sessions), len(visible),
                    n_marked, filter_str, orphan_only, help_visible)
        draw_list(list_win, sessions, visible, cursor, scroll, list_h, width)
        draw_detail(detail_win, width, cur_s)
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

        elif ch == ord("o"):
            orphan_only = not orphan_only
            cursor = scroll = 0

        elif ch == ord("/"):
            filter_str = readline_inline(status_win, width, " Filter: ", filter_str)
            cursor = scroll = 0

        elif ch == 27:
            if filter_str:
                filter_str = ""
            elif orphan_only:
                orphan_only = False
            cursor = scroll = 0

        elif ch == ord("r"):
            if not cur_s:
                continue
            new_title = readline_inline(status_win, width,
                                        " New title: ", cur_s["title"])
            if new_title and new_title != cur_s["title"]:
                err = rename_session(cur_s, new_title)
                status_msg = f" Renamed." if not err else f" Error: {err}"

        elif ch == ord("x"):
            targets = [sessions[i] for i in range(len(sessions)) if sessions[i]["selected"]]
            if not targets and cur_s:
                targets = [cur_s]
            if not targets:
                status_msg = " Nothing to export."
                continue
            # Group by destination since orphans and live projects export
            # to different places.
            written_total = 0
            err_total = []
            by_dest: dict[Path, list] = {}
            for s in targets:
                by_dest.setdefault(default_export_dir(s), []).append(s)
            for dest, ss in by_dest.items():
                w, errs = export_sessions_markdown(ss, dest)
                written_total += w
                err_total.extend(errs)
            for s in targets:
                s["selected"] = False
            status_msg = (f" Exported {written_total} session(s)."
                          if not err_total else
                          f" Exported {written_total}, errors: {'; '.join(err_total[:2])}")

        elif ch in (ord("d"), curses.KEY_DC):
            targets = [sessions[i] for i in range(len(sessions)) if sessions[i]["selected"]]
            if not targets and cur_s:
                targets = [cur_s]
            if not targets:
                status_msg = " Nothing to delete."
                continue
            if confirm_delete_tui(stdscr, targets):
                deleted, errors = delete_sessions(targets)
                gone = {id(s) for s in targets}
                sessions[:] = [s for s in sessions if id(s) not in gone]
                cursor = min(cursor, max(0, len(get_visible()) - 1))
                status_msg = (f" Deleted {deleted}." if not errors
                              else f" Deleted {deleted}, errors: {'; '.join(errors[:2])}")
            else:
                status_msg = " Cancelled."
            stdscr.clear()

        elif ch == curses.KEY_RESIZE:
            stdscr.clear()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="dpx_vscode_Cleaner.py",
        description="VS Code Copilot Chat session manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("mode", nargs="?", default="tui",
                        choices=["tui", "analyze", "help"],
                        help="Operation mode (default: tui)")
    parser.add_argument("--root", default=None,
                        help='Path to VS Code User directory '
                             '(default: ~/Library/Application Support/Code/User)')
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    if args.mode == "help":
        print(__doc__)
        return

    vscode_root = Path(args.root) if args.root else \
                  Path(os.environ.get("VSCODE_USER_ROOT", default_vscode_root()))

    if not vscode_root.exists():
        print(f"VS Code User directory not found: {vscode_root}", file=sys.stderr)
        sys.exit(1)

    print(f"vazzle v{__version__}")
    print(f"Scanning {vscode_root} ...")
    sessions = collect_all_sessions(vscode_root)

    if not sessions:
        print("No chat sessions found.")
        return

    n_e = sum(1 for s in sessions if is_empty(s))
    n_o = sum(1 for s in sessions if is_orphan(s))
    print(f"Found {len(sessions)} sessions  ({n_e} empty  {n_o} orphan)")

    if args.mode == "analyze":
        cmd_analyze(sessions)
    else:
        print("Launching TUI...")
        try:
            curses.wrapper(run_tui, sessions)
        except KeyboardInterrupt:
            pass
        print("Done.")


if __name__ == "__main__":
    main()
