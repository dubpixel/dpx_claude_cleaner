# cc-sessions

@AGENTS.md

Single-file Python TUI for managing Claude Code sessions.
No dependencies beyond the stdlib. Python 3.10+ (uses `X | Y` union types).

---

## Workflow (from AGENTS.md — dubpixel org standard)

Full rules live in `AGENTS.md`. The load-bearing ones for day-to-day work here:

- **Before any code change:** branch off `main`/default first — never commit directly
  to it. Name branches `feature/...`, `fix/...`, `docs/...`, `refactor/...`.
- **Before the first code change:** bump the version (semver) and commit that bump
  standalone, before the feature/fix commit. This project has no version file yet —
  create one (`VERSION` or `__version__` in the script) the first time this applies.
- **Never ask permission** to create a branch or open a PR — just do it. PR body
  format and title convention (`[Component] Brief description`) are in AGENTS.md §1.
- **Commit messages:** short, lowercase, plain English (`add mqtt decoder`, not
  `Added MQTT Decoder support`).
- **Mid-session issues:** default is log a GitHub issue and move on, don't fix
  inline — unless the user explicitly says "fix this" / "fix it now".
- **No drive-by refactors:** don't "improve" working code while doing something else;
  mention it, don't do it, unless asked.
- **Checkpoint progress** (✅ Completed / ⬜ Remaining / → Next Action) on tasks
  spanning >3 files or >30 min.
- Keep `CHANGELOG.md` and this file updated as things change; confirm README.md
  wording changes with the user before committing.

Note: this project directory is not itself a git repo (the enclosing home
directory is) — confirm/set up real repo state before assuming `main` exists
locally as a branch to work off of.

---

## What this is

Claude Code stores every conversation as a `.jsonl` file under:

```
~/.claude/projects/<encoded-project-path>/<session-uuid>.jsonl
```

Each project directory also has a `sessions-index.json` that powers the
`/resume` picker. This tool reads that index to display the same titles
you see in Claude Code, then lets you delete, rename, and move sessions
without touching Claude Code itself.

---

## File layout (Claude Code internals)

```
~/.claude/
  projects/
    <encoded-path>/              # one dir per working directory
      sessions-index.json        # index for this project's sessions
      <uuid>.jsonl               # one file per session (append-only)
      <uuid>.jsonl
      ...
  history.jsonl                  # global prompt history (don't touch)
  settings.json                  # global settings (don't touch)
  CLAUDE.md                      # global memory (don't touch)
```

### Path encoding

Claude Code encodes the working directory path into the project folder name
by replacing all `/` characters with `-` and prepending a `-`. So:

```
/Users/josh/code/myapp  →  -Users-josh-code-myapp
```

This is lossy -- hyphens in real path components are indistinguishable from
slash separators after encoding. Decoding is best-effort and display-only.

### sessions-index.json schema

Each entry in the array:

```json
{
  "sessionId":    "<uuid>",
  "fullPath":     "~/.claude/projects/<encoded>/<uuid>.jsonl",
  "summary":      "Human title set by /rename or auto-generated",
  "messageCount": 42,
  "fileMtime":    1720000000000,
  "created":      "2026-07-01T00:00:00.000Z"
}
```

**Known quirks:**
- As of Claude Code ~v2.1.30, the index is no longer reliably updated for
  new sessions. This tool scans the filesystem as a fallback and flags
  sessions missing from the index with a `*` column.
- `summary` is often blank for newer sessions even when the session has content.
  This tool falls back to the first user message, then the UUID.
- Index may have entries where the `.jsonl` file no longer exists (orphans, `!` flag).

### .jsonl session file schema (relevant lines only)

```jsonl
{"type":"summary","summary":"Session title","leafUuid":"<uuid>"}
{"type":"user","sessionId":"...","timestamp":"...","message":{"role":"user","content":"..."}}
{"type":"assistant","sessionId":"...","message":{"role":"assistant","content":[...]}}
{"type":"file-history-snapshot",...}   ← skip these
```

Only `user` and `assistant` entries count as messages for the `msgs` column.
The `summary` line is written by Claude Code (or by this tool's rename op)
and is what the `/resume` picker shows when the index summary is blank.

---

## Modes

```
python3 cc-sessions-v3.py [mode] [--root ~/.claude]
```

| Mode | Description |
|---|---|
| `tui` | Interactive TUI (default) |
| `analyze` | Print stats by project and exit |
| `fix-orphans` | Interactive CLI to clean orphan index entries and add unindexed sessions |
| `help` | Print docstring and exit |

---

## TUI reference

### Column flags

| Flag | Meaning |
|---|---|
| `E` | Empty: 0 user+assistant messages, or file < 1 KB |
| `!` | Orphan: index entry exists but `.jsonl` file is missing |
| `*` | Unindexed: `.jsonl` exists but not in any `sessions-index.json` |

### Keys

| Key | Action |
|---|---|
| `j` / `k` / `↑↓` | Navigate |
| `SPACE` | Toggle mark, auto-advance cursor |
| `a` / `A` | Mark all visible / unmark all |
| `e` | Toggle "empty sessions only" filter |
| `o` | Toggle "orphan sessions only" filter |
| `/` | Text filter on title or project path |
| `ESC` | Clear active filter |
| `r` | Rename current session (updates index + injects summary line in .jsonl) |
| `m` | Move/rehome marked sessions (or current) to a different project dir |
| `d` / `DEL` | Delete marked sessions (or current if none marked) |
| `q` | Quit |
| `?` | Toggle help pane |

Delete requires typing `YES` at the confirmation prompt.

### Move/rehome flow

`m` opens a full-screen project picker. Navigate with `j/k`, confirm with
`ENTER`. Press `n` to create a new project directory by typing an absolute
path. The tool will:

1. Move the `.jsonl` file to the destination project dir.
2. Remove the entry from the source `sessions-index.json`.
3. Add the entry to the destination `sessions-index.json`.
4. Remove the source project dir if it's now empty.

### Rename flow

`r` opens an inline editor in the status bar pre-filled with the current
title. The tool will:

1. Update `summary` field in the project's `sessions-index.json`.
2. Inject or replace the `{"type":"summary",...}` first line in the `.jsonl`.

---

## Extending this tool

### Adding a new command-line mode

Add a branch in `main()` and a `cmd_<name>(sessions, claude_root)` function.
`sessions` is a list of dicts with these guaranteed keys:

```python
{
  "session_id":      str,        # UUID
  "path":            Path|None,  # None if orphan
  "project_dir":     Path,       # ~/.claude/projects/<encoded>/
  "project_label":   str,        # decoded, display-only
  "title":           str,
  "title_from_index": bool,      # False = fell back to message/UUID
  "mtime":           datetime,
  "msg_count":       int|None,   # None if not scanned
  "size_bytes":      int,
  "file_exists":     bool,
  "in_index":        bool,
  "selected":        bool,       # TUI state, ignore in CLI modes
}
```

### Adding a new TUI action

Add a key handler in `run_tui()`. Use `readline_inline(status_win, ...)` for
single-line input. Use `pick_project(stdscr, ...)` for a destination picker.
Always call `stdscr.clear()` after any full-screen overlay before returning
to the main loop.

### Modifying index I/O

All index reads go through `read_index(path)` and all writes through
`write_index(path, entries)`. Both handle the two known wrapper formats
(`list` and `{"sessions": [...]}`) transparently. Add any new format
variations there, not inline.

---

## Things not to break

- **Never rewrite `.jsonl` files** except for the summary line injection in
  `rename_session()`. The rest of the file is append-only and Claude Code
  owns it. Injecting/replacing the first line is safe because it's just
  metadata -- Claude Code writes it, so re-writing it is fine.

- **Always update both the source and destination index** when moving a
  session. A session missing from its project's index won't show in `/resume`.

- **Don't delete `sessions-index.json` itself**, even when all entries are
  removed. Write an empty list `[]` instead so Claude Code can append to it.

- **Don't touch** `~/.claude/history.jsonl`, `settings.json`, or `CLAUDE.md`.
  Those are Claude Code's own config, not session data.

- **Index entry `fileMtime`** is in milliseconds (Unix epoch × 1000).
  Python's `Path.stat().st_mtime` is in seconds -- multiply by 1000.

---

## Known issues / TODO

- `decode_encoded()` is lossy for paths with hyphens in directory names.
  Display-only; doesn't affect any file operations.
- `msg_count` for unindexed sessions requires a full file scan. For very large
  sessions (8+ MB) this takes a moment. Could be made lazy.
- The project picker (`m` key) shows all existing project dirs including ones
  that only have dead index entries. Could filter to dirs with live `.jsonl` files.
- No undo. Deleted files are gone. The index is updated atomically but there's
  no rollback if a move partially fails across multiple sessions.
- `fix-orphans` is non-interactive in the sense that it prompts at the
  project-batch level, not per-session. Could be made per-session.
