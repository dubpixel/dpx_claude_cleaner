#!/usr/bin/env python3
# ================================================================================
# PYTHON SCRIPT - Claude Code session manager (TUI + CLI modes)
# ================================================================================
# PROJECT: dpx_claude_cleaner (cc-sessions)
# ================================================================================
#
# File: cc-sessions-v3.py
# Purpose: Browse, rename, move, and delete Claude Code session .jsonl files
#          and their sessions-index.json entries. See CLAUDE.md for the full
#          on-disk schema this tool reads/writes.
# Dependencies: Python 3.10+ stdlib only (curses, argparse, json, pathlib)
#
# ================================================================================
from __future__ import annotations
"""
cc-sessions-v3.py
=================
Multi-purpose Claude Code session manager.

MODES (first positional arg, default: tui)
  tui         Interactive TUI: list, filter, delete, rename, rehome
  analyze     Print a summary report and exit
  fix-orphans Non-interactive: re-home sessions whose project dir is gone
  help        Print this help

USAGE
  python3 cc-sessions-v3.py [mode] [--root ~/.claude]

ENVIRONMENT
  CLAUDE_ROOT   Override path to the .claude directory

KEYS (TUI)
  j/k  ↑↓        navigate
  SPACE           toggle mark (auto-advance)
  a / A           mark all visible / unmark all
  e               toggle "empty only" filter
  o               toggle "orphan only" filter (index entry, no file)
  /               text filter
  ESC             clear active filter
  r               rename current session title
  m               move/rehome current (or all marked) sessions
  d / DEL         delete marked (or current)
  q               quit
  ?               toggle help pane

COLUMN FLAGS
  E   empty session (0 user+assistant messages, or tiny file)
  !   orphan (index entry exists but .jsonl file is missing)
  *   summary from index is blank (title fell back to first message or UUID)
"""

import curses
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SMALL_BYTES = 1024          # files under this w/ 0 messages are "empty"
INDEX_FILE = "sessions-index.json"

try:
    __version__ = (Path(__file__).resolve().parent.parent / "VERSION") \
        .read_text().strip()
except FileNotFoundError:
    __version__ = "0.0.0-unknown"


# ---------------------------------------------------------------------------
# Path encoding / decoding
# ---------------------------------------------------------------------------

def encode_path(p: Path) -> str:
    """Encode an absolute path the way Claude Code does: slashes → hyphens, leading hyphen."""
    return str(p).replace("/", "-")


def decode_encoded(folder: str) -> str:
    """Best-effort decode of an encoded project folder name back to a readable path."""
    s = folder.lstrip("-")
    return "/" + s.replace("-", "/") if s else folder


# ---------------------------------------------------------------------------
# Index I/O
# ---------------------------------------------------------------------------

def read_index(index_path: Path) -> list[dict]:
    """Load a sessions-index.json. Returns list of entry dicts (may be empty)."""
    if not index_path.exists():
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return raw.get("sessions", raw.get("entries", []))
    except (json.JSONDecodeError, OSError):
        pass
    return []


def write_index(index_path: Path, entries: list[dict]) -> None:
    """Write entries back to sessions-index.json, preserving original wrapper if any."""
    try:
        orig = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else None
    except (json.JSONDecodeError, OSError):
        orig = None

    if isinstance(orig, dict) and ("sessions" in orig or "entries" in orig):
        key = "sessions" if "sessions" in orig else "entries"
        orig[key] = entries
        data = orig
    else:
        data = entries

    index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def _extract_message_text(content) -> str | None:
    """
    Pull display text out of a message's `content` field, which Claude Code
    stores either as a plain string or as a list of content blocks
    (`[{"type": "text", "text": "..."}, ...]`, possibly interleaved with
    tool_use/tool_result/image blocks). Returns None if no text is found.
    """
    if isinstance(content, str):
        return content if content.strip() else None
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = " ".join(p for p in parts if p.strip())
        return text if text.strip() else None
    return None


def get_session_title_from_jsonl(jsonl: Path) -> tuple[str, bool]:
    """
    Read a .jsonl for a title. Returns (title, came_from_index_summary).
    Priority: type==summary .summary field → first user message text → UUID stem.
    """
    try:
        with jsonl.open("r", encoding="utf-8", errors="replace") as fh:
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
                        return s, True
                elif t == "user":
                    content = obj.get("message", {}).get("content", "")
                    text = _extract_message_text(content)
                    if text:
                        snippet = text.strip().replace("\n", " ")
                        return snippet[:120] + ("..." if len(snippet) > 120 else ""), False
    except (OSError, PermissionError):
        pass
    return jsonl.stem, False


def count_messages(jsonl: Path) -> int:
    """Count user+assistant lines in a .jsonl."""
    n = 0
    try:
        with jsonl.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") in ("user", "assistant"):
                    n += 1
    except (OSError, PermissionError):
        pass
    return n


def collect_all_sessions(claude_root: Path) -> list[dict]:
    """
    Walk ~/.claude/projects/ and build a unified session list.

    Strategy:
      1. For each project dir, read its sessions-index.json.
      2. Also glob for *.jsonl files not in the index (newer sessions, index bugs).
      3. Merge, dedup by session_id.
      4. Mark orphans (in index, no file) and unindexed (file, not in index).
    """
    projects_root = claude_root / "projects"
    if not projects_root.exists():
        return []

    sessions: dict[str, dict] = {}  # session_id → dict

    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        project_label = decode_encoded(project_dir.name)

        # -- Load index entries for this project --
        index_path = project_dir / INDEX_FILE
        index_entries = read_index(index_path)
        index_ids = {e.get("sessionId") for e in index_entries if e.get("sessionId")}

        for entry in index_entries:
            sid = entry.get("sessionId")
            if not sid:
                continue

            # Resolve file path
            fp_raw = entry.get("fullPath", "")
            fp = Path(fp_raw.replace("~", str(Path.home()))) if fp_raw else None
            if fp is None or not fp.exists():
                # Try to find by UUID in this project dir
                candidate = project_dir / f"{sid}.jsonl"
                fp = candidate if candidate.exists() else None

            file_exists = fp is not None and fp.exists()
            size_bytes = fp.stat().st_size if file_exists else 0
            mtime = (datetime.fromtimestamp(fp.stat().st_mtime, tz=timezone.utc)
                     if file_exists else
                     datetime.fromtimestamp(entry.get("fileMtime", 0) / 1000, tz=timezone.utc))

            idx_title = (entry.get("summary") or "").strip()
            title_from_index = bool(idx_title)
            title = idx_title or (get_session_title_from_jsonl(fp)[0] if file_exists else sid)
            msg_count = entry.get("messageCount")

            sessions[sid] = dict(
                session_id=sid,
                path=fp,
                project_dir=project_dir,
                project_label=project_label,
                title=title,
                title_from_index=title_from_index,
                mtime=mtime,
                msg_count=msg_count,
                size_bytes=size_bytes,
                file_exists=file_exists,
                in_index=True,
                selected=False,
            )

        # -- Pick up .jsonl files not in the index --
        for jsonl in project_dir.glob("*.jsonl"):
            name = jsonl.name
            if name.startswith("agent-") or "warmup" in name:
                continue
            sid = jsonl.stem
            if sid in sessions:
                continue  # already have it from index

            stat = jsonl.stat()
            title, title_from_index = get_session_title_from_jsonl(jsonl)
            msg_count = count_messages(jsonl)

            sessions[sid] = dict(
                session_id=sid,
                path=jsonl,
                project_dir=project_dir,
                project_label=project_label,
                title=title,
                title_from_index=title_from_index,
                mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                msg_count=msg_count,
                size_bytes=stat.st_size,
                file_exists=True,
                in_index=False,
                selected=False,
            )

    result = list(sessions.values())
    result.sort(key=lambda s: s["mtime"], reverse=True)
    return result


def is_empty(s: dict) -> bool:
    if s["msg_count"] is not None:
        return s["msg_count"] == 0
    return s["size_bytes"] < SMALL_BYTES


def is_orphan(s: dict) -> bool:
    return not s["file_exists"]


# ---------------------------------------------------------------------------
# Analyze mode
# ---------------------------------------------------------------------------

def cmd_analyze(sessions: list[dict]) -> None:
    total = len(sessions)
    empty = sum(1 for s in sessions if is_empty(s))
    orphan = sum(1 for s in sessions if is_orphan(s))
    no_index = sum(1 for s in sessions if not s["in_index"])
    total_bytes = sum(s["size_bytes"] for s in sessions)

    # Per-project breakdown
    by_project: dict[str, list] = {}
    for s in sessions:
        by_project.setdefault(s["project_label"], []).append(s)

    print(f"\n{'='*60}")
    print(f"  Claude Code Session Analysis")
    print(f"{'='*60}")
    print(f"  Total sessions : {total}")
    print(f"  Empty          : {empty}")
    print(f"  Orphan (no file): {orphan}")
    print(f"  Not in index   : {no_index}")
    print(f"  Total size     : {total_bytes/1024/1024:.1f} MB")
    print(f"\n{'─'*60}")
    print(f"  By project ({len(by_project)} projects):")
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

def rehome_sessions(sessions_to_move: list[dict], dest_project_dir: Path,
                    claude_root: Path) -> tuple[int, list[str]]:
    """
    Move .jsonl files to dest_project_dir, update both source and dest
    sessions-index.json entries.
    Returns (moved_count, error_list).
    """
    dest_project_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    errors = []

    # Load dest index
    dest_index_path = dest_project_dir / INDEX_FILE
    dest_entries = read_index(dest_index_path)
    dest_ids = {e.get("sessionId") for e in dest_entries}

    for s in sessions_to_move:
        if not s["file_exists"] or s["path"] is None:
            errors.append(f"{s['session_id']}: no file to move (orphan)")
            continue

        src = s["path"]
        dst = dest_project_dir / src.name

        if dst == src:
            errors.append(f"{s['session_id']}: already in destination")
            continue

        try:
            shutil.move(str(src), str(dst))
        except OSError as ex:
            errors.append(f"{src.name}: {ex}")
            continue

        moved += 1

        # Update source index: remove entry
        src_index_path = s["project_dir"] / INDEX_FILE
        src_entries = read_index(src_index_path)
        src_entries = [e for e in src_entries if e.get("sessionId") != s["session_id"]]
        if src_index_path.exists():
            write_index(src_index_path, src_entries)
        # Clean up empty project dir
        try:
            remaining = [x for x in s["project_dir"].iterdir()
                         if x.name != INDEX_FILE]
            if not remaining:
                s["project_dir"].rmdir()
        except OSError:
            pass

        # Add/update dest index entry
        new_full_path = str(dst).replace(str(Path.home()), "~")
        if s["session_id"] not in dest_ids:
            dest_entries.append({
                "sessionId": s["session_id"],
                "fullPath": new_full_path,
                "summary": s["title"] if s["title_from_index"] else "",
                "messageCount": s["msg_count"],
                "fileMtime": int(dst.stat().st_mtime * 1000),
                "created": s["mtime"].isoformat(),
            })
        else:
            for e in dest_entries:
                if e.get("sessionId") == s["session_id"]:
                    e["fullPath"] = new_full_path
                    break

        # Update in-memory session record
        s["path"] = dst
        s["project_dir"] = dest_project_dir
        s["project_label"] = decode_encoded(dest_project_dir.name)

    write_index(dest_index_path, dest_entries)
    return moved, errors


def rename_session(s: dict, new_title: str, claude_root: Path) -> str | None:
    """
    Update a session's title in:
      1. The project's sessions-index.json
      2. The .jsonl file (prepend/replace the type==summary line)
    Returns error string or None on success.
    """
    new_title = new_title.strip()
    if not new_title:
        return "Empty title"

    # Update index
    index_path = s["project_dir"] / INDEX_FILE
    entries = read_index(index_path)
    updated = False
    for e in entries:
        if e.get("sessionId") == s["session_id"]:
            e["summary"] = new_title
            updated = True
            break
    if not updated and s["in_index"]:
        pass  # index entry may have been written by stat-based loader -- add it
    if s["in_index"] or entries:
        write_index(index_path, entries)

    # Update .jsonl summary line
    if s["file_exists"] and s["path"]:
        try:
            lines = s["path"].read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            new_summary_line = json.dumps({
                "type": "summary",
                "summary": new_title,
                "leafUuid": s["session_id"],
            }) + "\n"

            if lines and lines[0].strip():
                try:
                    first = json.loads(lines[0])
                    if first.get("type") == "summary":
                        lines[0] = new_summary_line
                    else:
                        lines.insert(0, new_summary_line)
                except json.JSONDecodeError:
                    lines.insert(0, new_summary_line)
            else:
                lines.insert(0, new_summary_line)

            s["path"].write_text("".join(lines), encoding="utf-8")
        except OSError as ex:
            return str(ex)

    s["title"] = new_title
    s["title_from_index"] = True
    return None


def delete_sessions(targets: list[dict], claude_root: Path) -> tuple[int, list[str]]:
    """Delete .jsonl files and remove from sessions-index.json entries."""
    deleted = 0
    errors = []

    # Group by project dir for index updates
    by_project: dict[Path, list] = {}
    for s in targets:
        by_project.setdefault(s["project_dir"], []).append(s)

    for project_dir, ss in by_project.items():
        # Remove files
        gone_ids = set()
        for s in ss:
            if s["file_exists"] and s["path"]:
                try:
                    s["path"].unlink()
                    gone_ids.add(s["session_id"])
                    deleted += 1
                except OSError as ex:
                    errors.append(f"{s['path'].name}: {ex}")
            else:
                gone_ids.add(s["session_id"])
                deleted += 1

        # Update index
        index_path = project_dir / INDEX_FILE
        if index_path.exists() and gone_ids:
            entries = read_index(index_path)
            entries = [e for e in entries if e.get("sessionId") not in gone_ids]
            write_index(index_path, entries)

        # Clean empty project dir
        try:
            remaining = [x for x in project_dir.iterdir() if x.name != INDEX_FILE]
            if not remaining:
                project_dir.rmdir()
        except OSError:
            pass

    return deleted, errors


# ---------------------------------------------------------------------------
# Fix-orphans mode (non-interactive)
# ---------------------------------------------------------------------------

def cmd_fix_orphans(sessions: list[dict], claude_root: Path) -> None:
    """
    Find sessions whose project dir doesn't correspond to an existing path
    on disk, and offer to move them to a new project or just clean the index.
    """
    orphans = [s for s in sessions if is_orphan(s)]
    unindexed = [s for s in sessions if not s["in_index"]]

    print(f"\n{len(orphans)} orphan index entries (file missing)")
    print(f"{len(unindexed)} unindexed sessions (file exists, not in any index)\n")

    if not orphans and not unindexed:
        print("Nothing to do.")
        return

    # Orphan handling: remove index entry or try to find file
    if orphans:
        print("─── Orphan index entries ───")
        for s in orphans:
            print(f"  [{s['session_id'][:8]}] {s['title'][:60]}")
            print(f"           project: {s['project_label']}")
        ans = input("\nRemove these orphan entries from the index? [y/N] ").strip().lower()
        if ans == "y":
            deleted, errors = delete_sessions(orphans, claude_root)
            print(f"Removed {deleted} entries.")
            if errors:
                print("Errors:", errors)

    # Unindexed: add to their project's index
    if unindexed:
        print("\n─── Unindexed sessions ───")
        for s in unindexed:
            print(f"  [{s['session_id'][:8]}] {s['title'][:60]}")
            print(f"           project: {s['project_label']}")
        ans = input("\nAdd these sessions to their project index? [y/N] ").strip().lower()
        if ans == "y":
            by_project: dict[Path, list] = {}
            for s in unindexed:
                by_project.setdefault(s["project_dir"], []).append(s)
            count = 0
            for project_dir, ss in by_project.items():
                index_path = project_dir / INDEX_FILE
                entries = read_index(index_path)
                existing_ids = {e.get("sessionId") for e in entries}
                for s in ss:
                    if s["session_id"] not in existing_ids:
                        entries.append({
                            "sessionId": s["session_id"],
                            "fullPath": str(s["path"]).replace(str(Path.home()), "~"),
                            "summary": s["title"] if s["title_from_index"] else "",
                            "messageCount": s["msg_count"],
                            "fileMtime": int(s["path"].stat().st_mtime * 1000),
                            "created": s["mtime"].isoformat(),
                        })
                        count += 1
                write_index(index_path, entries)
            print(f"Added {count} sessions to their indexes.")


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

def draw_header(w, width, total, shown, marked, filter_str, empty_only, orphan_only, help_vis):
    w.erase()
    title = " cc-sessions "
    w.addstr(0, 0, title, curses.A_BOLD | curses.A_REVERSE)
    info = f" {shown}/{total} sessions"
    if marked:
        info += f"  [{marked} marked]"
    if empty_only:
        info += "  [empty]"
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
        "  SPACE       mark/unmark (advance) m    move/rehome marked or current",
        "  a / A       mark all / unmark all d    delete marked or current",
        "  e           empty sessions only   o    orphan sessions only",
        "  /           text filter           ESC  clear filter",
        "  q           quit                  ?    close help",
        "  FLAGS:  E=empty  !=orphan  *=no index title",
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
    cw_flag = 4   # E!* flags
    cw_cnt = 5
    cw_sz = 7
    cw_dt = 17
    fixed = cw_sel + cw_flag + cw_cnt + cw_sz + cw_dt + 5
    cw_title = max(8, width - fixed)

    hdr = (f"{'':3} {'flg':4} {'msgs':>4} {'size':>6} {'modified':17} "
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
                ("*" if not s["in_index"] else " ") + \
                (" ")
        cnt = fmt_ct(s["msg_count"])
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
        txt = f"  {s['project_label']}"
        if s["path"]:
            txt += f"  [{s['session_id'][:8]}]"
        try:
            w.addstr(0, 0, txt[:width], curses.A_DIM)
        except curses.error:
            pass
    w.noutrefresh()


def draw_status(w, width, msg=""):
    w.erase()
    default = " SPC=mark  d=del  r=rename  m=move  /=filter  e=empty  o=orphan  q=quit"
    try:
        w.addstr(0, 0, (msg or default)[:width], curses.A_REVERSE)
    except curses.error:
        pass
    w.noutrefresh()


# ---------------------------------------------------------------------------
# TUI inline input helpers
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


def pick_project(stdscr, projects: list[Path], prompt: str) -> Path | None:
    """
    Full-screen picker for selecting a destination project directory.
    Shows decoded project labels. Returns chosen Path or None.
    """
    items = [(decode_encoded(p.name), p) for p in projects]
    items.sort(key=lambda x: x[0])

    cursor = 0
    scroll = 0

    while True:
        height, width = stdscr.getmaxyx()
        stdscr.erase()

        try:
            stdscr.addstr(0, 0, f" {prompt} ".center(width, "─")[:width], curses.A_REVERSE)
            stdscr.addstr(1, 0, " j/k=navigate  ENTER=select  ESC=cancel  n=new", curses.A_DIM)
        except curses.error:
            pass

        view_rows = height - 4
        cursor = max(0, min(cursor, len(items) - 1))
        if cursor < scroll:
            scroll = cursor
        elif cursor >= scroll + view_rows:
            scroll = cursor - view_rows + 1

        for row, (label, path) in enumerate(items[scroll: scroll + view_rows], 3):
            real_idx = scroll + row - 3
            attr = curses.A_REVERSE if real_idx == cursor else curses.A_NORMAL
            try:
                stdscr.addstr(row, 0, f"  {label}"[:width], attr)
            except curses.error:
                pass

        stdscr.refresh()
        ch = stdscr.getch()

        if ch in (ord("q"), 27):
            return None
        elif ch in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(items) - 1, cursor + 1)
        elif ch in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            return items[cursor][1] if items else None
        elif ch == ord("n"):
            # Create a new project dir based on a path the user types
            stdscr.addstr(height - 1, 0,
                          " New project path (absolute): "[:width], curses.A_REVERSE)
            stdscr.refresh()
            curses.echo()
            curses.curs_set(1)
            try:
                raw = stdscr.getstr(height - 1, 30, width - 31).decode("utf-8").strip()
            except Exception:
                raw = ""
            curses.noecho()
            curses.curs_set(0)
            if raw:
                encoded = encode_path(Path(raw))
                new_dir = projects[0].parent / encoded  # sibling of existing project dirs
                new_dir.mkdir(parents=True, exist_ok=True)
                return new_dir


def confirm_delete_tui(stdscr, items: list[dict]) -> bool:
    height, width = stdscr.getmaxyx()
    lines = ["", f"  Delete {len(items)} session(s) permanently:", ""]
    for s in items[:14]:
        marker = "[ORPHAN] " if is_orphan(s) else ""
        lines.append(f"    {marker}{s['title'][:58]}")
    if len(items) > 14:
        lines.append(f"    ... and {len(items) - 14} more")
    lines += ["", "  Type YES to confirm, anything else cancels: "]

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


# ---------------------------------------------------------------------------
# Main TUI loop
# ---------------------------------------------------------------------------

def run_tui(stdscr, sessions: list[dict], claude_root: Path):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_YELLOW, -1)
    except Exception:
        pass

    filter_str = ""
    empty_only = False
    orphan_only = False
    cursor = 0
    scroll = 0
    status_msg = ""
    help_visible = False

    def get_visible() -> list[int]:
        idxs = range(len(sessions))
        if empty_only:
            idxs = [i for i in idxs if is_empty(sessions[i])]
        elif orphan_only:
            idxs = [i for i in idxs if is_orphan(sessions[i])]
        else:
            idxs = list(idxs)
        if filter_str:
            lo = filter_str.lower()
            idxs = [i for i in idxs
                    if lo in sessions[i]["title"].lower()
                    or lo in sessions[i]["project_label"].lower()]
        return list(idxs)

    while True:
        height, width = stdscr.getmaxyx()
        header_h = 1
        detail_h = 1
        help_h = 9 if help_visible else 0
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
                    n_marked, filter_str, empty_only, orphan_only, help_visible)
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

        elif ch == ord("e"):
            empty_only = not empty_only
            orphan_only = False
            cursor = scroll = 0

        elif ch == ord("o"):
            orphan_only = not orphan_only
            empty_only = False
            cursor = scroll = 0

        elif ch == ord("/"):
            filter_str = readline_inline(status_win, width, " Filter: ", filter_str)
            cursor = scroll = 0

        elif ch == 27:
            if filter_str:
                filter_str = ""
            elif empty_only:
                empty_only = False
            elif orphan_only:
                orphan_only = False
            cursor = scroll = 0

        elif ch == ord("r"):
            # Rename current session
            if not cur_s:
                continue
            new_title = readline_inline(status_win, width,
                                        " New title: ", cur_s["title"])
            if new_title and new_title != cur_s["title"]:
                err = rename_session(cur_s, new_title, claude_root)
                status_msg = f" Renamed." if not err else f" Error: {err}"

        elif ch == ord("m"):
            # Move/rehome marked sessions (or current)
            targets = [sessions[i] for i in range(len(sessions)) if sessions[i]["selected"]]
            if not targets and cur_s:
                targets = [cur_s]
            if not targets:
                status_msg = " Nothing to move."
                continue

            # Build list of available project dirs
            projects_root = claude_root / "projects"
            project_dirs = sorted(
                [d for d in projects_root.iterdir() if d.is_dir()],
                key=lambda d: d.name
            )

            dest = pick_project(stdscr, project_dirs,
                                 f"Move {len(targets)} session(s) to project:")
            stdscr.clear()
            if dest is None:
                status_msg = " Cancelled."
            else:
                moved, errors = rehome_sessions(targets, dest, claude_root)
                for s in targets:
                    s["selected"] = False
                if errors:
                    status_msg = f" Moved {moved}, errors: {'; '.join(errors[:2])}"
                else:
                    status_msg = f" Moved {moved} session(s) to {decode_encoded(dest.name)}"

        elif ch in (ord("d"), curses.KEY_DC):
            targets = [sessions[i] for i in range(len(sessions)) if sessions[i]["selected"]]
            if not targets and cur_s:
                targets = [cur_s]
            if not targets:
                status_msg = " Nothing to delete."
                continue
            if confirm_delete_tui(stdscr, targets):
                deleted, errors = delete_sessions(targets, claude_root)
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
        prog="cc-sessions-v3.py",
        description="Claude Code session manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("mode", nargs="?", default="tui",
                        choices=["tui", "analyze", "fix-orphans", "help"],
                        help="Operation mode (default: tui)")
    parser.add_argument("--root", default=None,
                        help="Path to .claude directory (default: ~/.claude)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    if args.mode == "help":
        print(__doc__)
        return

    claude_root = Path(args.root) if args.root else \
                  Path(os.environ.get("CLAUDE_ROOT", Path.home() / ".claude"))

    if not claude_root.exists():
        print(f"Claude root not found: {claude_root}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {claude_root} ...")
    sessions = collect_all_sessions(claude_root)

    if not sessions:
        print("No sessions found.")
        return

    n_e = sum(1 for s in sessions if is_empty(s))
    n_o = sum(1 for s in sessions if is_orphan(s))
    n_u = sum(1 for s in sessions if not s["in_index"])
    print(f"Found {len(sessions)} sessions  "
          f"({n_e} empty  {n_o} orphan  {n_u} unindexed)")

    if args.mode == "analyze":
        cmd_analyze(sessions)
    elif args.mode == "fix-orphans":
        cmd_fix_orphans(sessions, claude_root)
    else:
        print("Launching TUI...")
        try:
            curses.wrapper(run_tui, sessions, claude_root)
        except KeyboardInterrupt:
            pass
        print("Done.")


if __name__ == "__main__":
    main()
