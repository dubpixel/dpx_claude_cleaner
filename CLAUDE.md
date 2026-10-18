# dpx_claude_cleaner (formerly cc-sessions)

@AGENTS.md

Single-file Python TUI for managing Claude Code sessions.
No dependencies beyond the stdlib. Python 3.10+ (uses `X | Y` union types).

---

## Workflow (from AGENTS.md — dubpixel org standard)

Full rules live in `AGENTS.md`. The load-bearing ones for day-to-day work here:

- **Before any code change:** branch off `main`/default first — never commit directly
  to it. Name branches `feature/...`, `fix/...`, `docs/...`, `refactor/...`.
- **Before the first code change:** bump `VERSION` (semver) and commit that bump
  standalone, before the feature/fix commit.
- **Never ask permission** to create a branch or open a PR — just do it. PR body
  format and title convention (`[Component] Brief description`) are in AGENTS.md §1.
- **Commit messages:** short, lowercase, plain English (`add mqtt decoder`, not
  `Added MQTT Decoder support`).
- **Version tags:** tag version bumps on merge to `main` (`git tag vX.Y.Z && git push
  --tags`), starting from v0.2.2 onward — earlier bumps weren't tagged, not backfilled.
- **Release notes:** for MAJOR/MINOR bumps, add an entry to `RELEASE_NOTES.md` using
  `dpx_release_note_template.md`'s structure (patch bumps: `CHANGELOG.md` only).
- **Mid-session issues:** default is log a GitHub issue and move on, don't fix
  inline — unless the user explicitly says "fix this" / "fix it now".
- **No drive-by refactors:** don't "improve" working code while doing something else;
  mention it, don't do it, unless asked.
- **Checkpoint progress** (✅ Completed / ⬜ Remaining / → Next Action) on tasks
  spanning >3 files or >30 min.
- Keep `CHANGELOG.md` and this file updated as things change; confirm README.md
  wording changes with the user before committing.
- **Deploy from the feature branch to test, before merging:** after a fix/feature
  is committed (and pushed/PR'd), run `scripts/deploy_local.sh` right away so
  `zazzle` reflects the branch under test — don't wait for the PR to merge
  first. It copies whatever's currently checked out, so this naturally means
  re-running it after switching branches or merging, too.

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
{"type":"custom-title","customTitle":"Session title","sessionId":"..."}
{"type":"summary","summary":"Session title","leafUuid":"<uuid>"}
{"type":"user","sessionId":"...","timestamp":"...","cwd":"/real/path","message":{"role":"user","content":"..."}}
{"type":"assistant","sessionId":"...","message":{"role":"assistant","content":[...]}}
{"type":"file-history-snapshot",...}   ← skip these
```

Only `user` and `assistant` entries count as messages for the `msgs` column.

Title resolution priority (see `get_session_title_from_jsonl()`): latest
`type=="custom-title"` (`customTitle` field) → latest `type=="summary"`
(`.summary` field) → first user message text → UUID stem. Both
`custom-title` and `summary` lines can appear **more than once** per file
(the title gets renamed mid-conversation) — always take the *last*
occurrence, not the first; that's what `/resume` displays. The `custom-title`
line is written by Claude Code itself (this is the actual field `/resume`
reads — don't confuse it with `summary`, which this tool also writes on
rename). Also don't decode the project's display path from the
hyphen-encoded directory name (`decode_encoded()`) if avoidable — it's lossy
for any real path containing a hyphen. Prefer the `cwd` field recorded
inside the session file itself (`get_project_cwd_from_jsonl()`), which is
exact.

---

## Modes

```
python3 src/dpx_claude_Cleaner.py [mode] [--root ~/.claude] [--scope current|all]
zazzle [mode] [--root ~/.claude]     # after scripts/deploy_local.sh
```

`--scope` defaults to `current` (only the project matching the shell's
`cwd`, same as `/resume`) for `analyze`/`fix-orphans`. In `tui` mode it
starts scoped to the current project too, but is a live toggle instead
(`g` key) rather than a flag — see Keys below.

| Mode | Description |
|---|---|
| `tui` | Interactive TUI (default) |
| `analyze` | Print stats by project and exit |
| `fix-orphans` | Interactive CLI to clean orphan index entries and add unindexed sessions |
| `export` | Zip one session (+ sidecar dir) for another machine: `--id`/`--name`/`--latest`, `--out`, `--include-memory` |
| `import` | `import BUNDLE [--project PATH] [--on-conflict ask\|overwrite\|abort]`: verify sha256, file under the target's encoded project dir |
| `duplicates` | List session IDs present in more than one project dir |
| `help` | Print docstring and exit |

---

## Cross-machine transfer (export / import)

Bundle = zip with `manifest.json` (`bundle_format` 1, sha256, source OS/path,
git state), `HANDOFF.md`, `<id>.jsonl`, the `<id>/` sidecar dir if present
(verified on a real install: `subagents/`, `tool-results/`, `workflows/`,
`custom-title.json`), and `memory/` only with `--include-memory`.

Rules (all enforced by `tests/test_transfer.py`):

- **Copy-only, binary.** Transcripts are never edited or re-encoded; the
  manifest sha256 must match on import. No `--rewrite-paths`.
- **One copy per session ID.** `claude --resume <id>` fails if two projects
  hold the same ID, so import overwrites an existing differing copy in place
  (after `--on-conflict` approval) instead of adding a second one.
- **Folder name = `encode_path(cwd)`**, or `CLAUDE_CODE_PROJECT_DIR_NAME`.
  Past 200 chars Claude adds an undocumented hash; we reuse a folder Claude
  already made for that cwd, else refuse. Resume-by-ID doesn't need the name.
- Zip members are filtered (`_safe_member`) so a hostile bundle can't write
  outside the project dir.

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
| `g` | Toggle scope: this project (default, like `/resume`) vs global (all projects) |
| `s` | Sort sessions with "delete" (case-insensitive) in the title to the top -- still shown, unlike `/` filtering |
| `/` | Text filter on title or project path |
| `ESC` | Clear active filter |
| `r` | Rename current session (updates index + injects summary line in .jsonl) |
| `m` | Move/rehome marked sessions (or current) to a different project dir |
| `d` / `DEL` | Delete marked sessions (or current if none marked) |
| `q` | Quit |
| `?` | Toggle help pane |

Delete requires typing `YES` at the confirmation prompt.

### Move/rehome flow

`m` opens a full-screen project picker listing already-known Claude project
dirs. Navigate with `j/k`, confirm with `ENTER`. Press `n` to open a real
filesystem browser instead (`browse_filesystem()`) — seeded with shortcuts
to `~`, `~/Code`, and `~/Circuits` (skipped if they don't exist) — to pick
any directory on disk, including ones that have never been used with Claude
Code. In the browser: `j/k` to move the highlighted row, `ENTER` to open a
directory or jump a shortcut, `[ USE THIS DIRECTORY ]` (always the first
row) to select the currently-shown directory, backspace to go up, `ESC` to
cancel. The tool will then:

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

## Testing

```bash
python3 -m unittest discover -v
```

`tests/` (stdlib `unittest`, no dependencies), organized by behavior area:

| File | Covers |
|---|---|
| `test_titles.py` | `get_session_title_from_jsonl()`, `_extract_message_text()`, `_clean_synthetic_user_text()` |
| `test_paths.py` | `encode_path()`, `decode_encoded()`, `get_project_cwd_from_jsonl()` |
| `test_discovery.py` | `collect_all_sessions()`, `is_empty()`, `is_orphan()` |
| `test_operations.py` | `rename_session()`, `delete_sessions()` |
| `test_cli.py` | `main()`'s `--scope current` filtering |
| `test_transfer.py` | `export_session()`, `import_bundle()`, `find_duplicate_sessions()`, `project_dir_name_for()`, `pick_session()` |
All fixtures are synthetic, built in temp directories via `tests/helpers.py`
-- tests never touch real `~/.claude` data (that's for manual verification
only, see Development Philosophy below). `tests.helpers` loads
`src/dpx_claude_Cleaner.py` via `importlib` since its mixed-case filename
isn't a conventional importable module name.

When fixing a bug found against real data, add the regression case here
too, not just a one-off verification script -- `_clean_synthetic_user_text`
needed a second, near-identical fix (`<local-command-caveat>` in 0.2.1,
`<local-command-stdout>` in 0.3.2) partly because its first fix only ever
existed as a throwaway script, not a committed test. Runs automatically via
`.github/workflows/tests.yml` on every push/PR (Python 3.10 and 3.12,
`contents: read` only).

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

---

## vazzle (VS Code Copilot Chat companion)

`src/dpx_vscode_Cleaner.py` is a separate tool, same repo, same shape
(browse/rename/delete TUI + CLI modes), for cleaning up GitHub Copilot
Chat session history in VS Code. **Fully independent of everything above**
-- separate script, separate deploy (`scripts/deploy_local_vazzle.sh`),
separate tests (`tests/test_vscode_*.py`), zero shared code or imports
with `dpx_claude_Cleaner.py` by design (see `VAZZLE_PLAN.md`'s hard
constraint). Deploys to the `vazzle` alias.

Reads `~/Library/Application Support/Code/User/workspaceStorage/<hash>/`:
`workspace.json` for the real project path (exact `file://` URI, no lossy
decode needed, unlike `decode_encoded()` above), `chatSessions/*.json`
(flat) or `*.jsonl` (event-sourced patch log) for the chat itself, and
`chatEditingSessions/<uuid>/` for associated file-edit history.

The `.jsonl` format has a real data-loss trap: Copilot Chat periodically
*compacts*, replacing the entire live `requests` array and silently
dropping earlier turns if you naively replay-and-read-final-state. Full
detail and the fix (snapshot into a `requestId`-keyed archive before every
such replace) is in `VSCODE-CHAT-RECOVERY.md` -- read that before touching
`reconstruct_jsonl_session()` in `dpx_vscode_Cleaner.py`.

The TUI groups sessions by project (header row per workspace, most
recently active first, via `build_display_rows()`), hides empty (0-turn)
sessions by default (`e` to show them -- these are a normal VS Code
artifact, one file per opened chat tab even if nothing was said, not
useful data), and never falls back to a raw `session_id` as a title
(`session_title()` falls back to `(empty chat)` or `(untitled, N turns)`
instead). All three came from live-testing against 500+ real sessions
across 50+ workspaces -- the flat, ungrouped, unfiltered list was
unreadable.

Tests: `tests/test_vscode_reconstruction.py` (the compaction-recovery
algorithm -- non-negotiable, this is the whole reason the tool exists),
`test_vscode_paths.py` (`workspace.json` resolution), `test_vscode_discovery.py`
(`collect_all_sessions()`, title fallbacks), `test_vscode_operations.py`
(rename/delete/export), `test_vscode_tui.py` (`build_display_rows()`
grouping). Same synthetic-fixtures-only policy as zazzle's tests.

macOS-only for now (the `Application Support` path is macOS-specific).
Full design, v1 scope, and open questions (`state.vscdb` contents, the
"most complete response" heuristic, whether `chatEditingSessions` is
always 1:1 with a chat session) are in `VAZZLE_PLAN.md`.
