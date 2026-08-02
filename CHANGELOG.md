# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

---

## [0.4.0] - 2026-08-02

### Added
- Deterministic stdlib `unittest` regression harness under `tests/` for core
  non-TUI session logic: title/cwd resolution, content extraction, path
  encode/decode behavior, rename/delete operations, session
  collect/dedup/orphan-unindexed reconciliation, and `--scope current` CLI
  filtering behavior.
- GitHub Actions workflow at `.github/workflows/tests.yml` that runs the
  regression suite on `push` and `pull_request` across Python 3.10 and 3.12
  with `contents: read` permissions.

---

## [0.3.3] - 2026-08-02

### Fixed
- `scripts/deploy_local.sh` hardcoded `~/.zshrc` as the alias target,
  regardless of the invoking user's actual login shell. Now detects zsh vs.
  bash via `$SHELL` (bash prefers `~/.bashrc`, falls back to
  `~/.bash_profile`); an unrecognized shell prints the alias line to add
  manually instead of guessing wrong.

---

## [0.3.2] - 2026-08-01

### Fixed
- Title fallback still showed raw `<local-command-stdout>...` wrapper text
  (e.g. `That session is still running as a background agent...`) for
  sessions with no `custom-title`/`summary`, same class of bug as
  `<local-command-caveat>` fixed in 0.2.1 but a different tag that wasn't
  covered. Now skipped alongside it, falling through to the next real
  message or, if there genuinely isn't one, the UUID.

---

## [0.3.1] - 2026-07-31

### Changed
- Renamed the `scripts/deploy_local.sh` shell alias from `dpx_ccleaner` to
  `zazzle`. Updated everywhere it's referenced (README, CLAUDE.md,
  AGENTS.md, RELEASE_NOTES.md, the script itself, the tool's own usage
  docstring). Removed the stale `dpx_ccleaner` alias line and binary
  locally.

---

## [0.3.0] - 2026-07-31

### Added
- `s` key in the TUI: sorts sessions with "delete" (case-insensitive) in
  the title to the top of the list, still shown alongside everything else
  (unlike `/` filtering, which hides non-matches). Matches for a common
  cleanup workflow: rename sessions you've decided to get rid of to
  something containing "delete", then use `s` to gather them for bulk
  deletion. ([#10](https://github.com/dubpixel/dpx_claude_cleaner/issues/10))

---

## [0.2.2] - 2026-07-31

### Fixed
- `help` mode and `--help` printed the literal string `None` instead of
  the usage docstring. Root cause: `from __future__ import annotations`
  sat *before* the module docstring — only comments may precede a
  docstring for Python to recognize it as `__doc__`; a statement there
  demotes the string literal to a no-op expression. Moved the `__future__`
  import below the docstring instead. ([#2](https://github.com/dubpixel/dpx_claude_cleaner/issues/2))

---

## [0.2.1] - 2026-07-31

### Fixed
- Title fallback (for sessions with no `custom-title`/`summary`) no longer
  shows raw harness-injected wrapper text as the title. Two patterns
  detected: `<local-command-caveat>...` (pure framing, now skipped in favor
  of the next real user message) and `<command-message>/<command-name>/
  <command-args>` slash-command invocations (now shows just the command
  name + args, e.g. `/loop: migrate dpx_yolo_reader - test GUI live...`,
  instead of the raw XML). ([#8](https://github.com/dubpixel/dpx_claude_cleaner/issues/8))

---

## [0.2.0] - 2026-07-31

### Added
- Real filesystem browser (`browse_filesystem()`) for the move/rehome flow
  (`m` then `n` in the TUI), replacing the old raw-text "type an absolute
  path" prompt. Navigate actual directories with `j`/`k`/`ENTER`, seeded
  with shortcuts to `~`, `~/Code`, and `~/Circuits`, so you can pick a
  destination that's never been used with Claude Code before without
  typing a path blind.

---

## [0.1.3] - 2026-07-31

### Added
- `--scope {current,all}` flag for `analyze`/`fix-orphans` (default
  `current`, matching `/resume`'s per-project scoping); `tui` mode starts
  scoped to the current project too, with a new `g` key to toggle to global
  live instead of a flag.
- Version is now shown inside the running tool itself (TUI title bar, CLI
  scan banner), not just via `--version`.

### Fixed
- Titles now read `type: "custom-title"` lines (`customTitle` field) —
  the actual field Claude Code's `/resume` picker displays — which this
  tool never checked at all before. Also fixed both `custom-title` and
  `summary` lookups to take the *last* occurrence in the file instead of
  the first, since titles get renamed mid-conversation and the old code
  would show a stale title. Verified directly against a real `/resume`
  listing pasted by the user: 7/8 titles now match exactly, in the same
  order. ([#4](https://github.com/dubpixel/dpx_claude_cleaner/issues/4))
- `encode_path()` only replaced `/` with `-`, but Claude Code's real
  encoding replaces *every* non-alphanumeric character (spaces, `.`, `@`,
  `_`, ...). This silently broke the new `--scope current` / `g` toggle
  (it could never match the real project directory for any path containing
  a space or other punctuation) — found while testing the scope feature
  above. Verified against 30 real project directories' recorded `cwd`
  values; all now match exactly.

---

## [0.1.2] - 2026-07-31

### Changed
- Renamed the working script from `src/cc-sessions-v3.py` to
  `src/dpx_claude_Cleaner.py` (also retiring the old `-v1`/`-v2` iterations
  to `src/archive/`). Updated every internal reference (`argparse` prog
  name, TUI title, docstring, file header) and all docs/scripts that pointed
  at the old filename.

### Fixed
- Project labels (in `analyze` output and the TUI) now read the real `cwd`
  Claude Code records inside each session file, instead of decoding it from
  the hyphen-encoded project directory name. That decode was lossy for any
  real path containing a hyphen (e.g. `GoogleDrive-i@dubpixel.tv` used to
  render as `GoogleDrive/i/dubpixel/tv`). ([#1](https://github.com/dubpixel/dpx_claude_cleaner/issues/1))
- Delete confirmation (`d` in the TUI) no longer silently reads back as
  "cancelled": it used a hand-computed `stdscr.getstr(y, x, ...)` call whose
  `x` coordinate could throw `curses.error` on narrower terminals, which was
  swallowed and treated as an empty (non-"YES") answer. Now reuses the same
  `readline_inline` input helper already used for rename/filter.
  ([#1](https://github.com/dubpixel/dpx_claude_cleaner/issues/1))

---

## [0.1.1] - 2026-07-31

### Fixed
- Session titles no longer fall back to the raw UUID when a message's
  `content` is a list of content blocks (`[{"type": "text", "text": "..."}]`)
  instead of a plain string — about 15% of real-world session files use this
  shape. ([#1](https://github.com/dubpixel/dpx_claude_cleaner/issues/1))

---

## [0.1.0] - 2026-07-31

### Added
- Initial public release of `cc-sessions` (`src/cc-sessions-v3.py`): interactive
  TUI for browsing, filtering, renaming, moving, and deleting Claude Code
  session `.jsonl` files across all projects
- CLI modes: `analyze` (stats by project), `fix-orphans` (clean orphan index
  entries), `help`
- Empty/orphan/unindexed session detection with `E` / `!` / `*` column flags
- `--version` flag reading from project-root `VERSION` file
- Earlier iterations (`cc-sessions-v1.py`, `cc-sessions-v2.py`) kept in `src/`
  for reference
- MIT license

---

## Version Guidelines

### Semantic Versioning (MAJOR.MINOR.PATCH)

- **MAJOR**: Breaking changes, incompatible API modifications
- **MINOR**: New features, backwards-compatible additions
- **PATCH**: Bug fixes, documentation updates, typos

### Change Categories

- **Added**: New features or capabilities
- **Changed**: Changes to existing functionality
- **Deprecated**: Features marked for future removal (still working)
- **Removed**: Removed features or functionality
- **Fixed**: Bug fixes
- **Security**: Security patches or vulnerability fixes

### Example Entry Format

```markdown
## [1.2.0] - 2026-03-15

### Added
- New authentication system with JWT tokens
- Export functionality for CSV and JSON formats
- Dark mode toggle in user preferences

### Changed
- Improved database query performance by 40%
- Updated UI library from v2.1 to v3.0

### Fixed
- Fixed memory leak in background worker process
- Corrected timezone handling in date picker component

### Security
- Patched XSS vulnerability in user input validation
```

### Version Comparison Links

Add these at the bottom of the file (replace with your repo owner/name):

```markdown
[Unreleased]: https://github.com/owner/repo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/owner/repo/releases/tag/v0.1.0
```

---

## Tips for Maintaining This Changelog

1. **Update as you work**: Add entries when making changes, not at release time
2. **Keep it scannable**: Use clear, concise descriptions
3. **Link to issues/PRs**: Include `(#123)` references when relevant
4. **Date format**: Use ISO 8601 (YYYY-MM-DD)
5. **Group by type**: Keep all Added items together, all Fixed items together, etc.
6. **User perspective**: Write what changed for users, not implementation details
7. **Unreleased section**: Keep active changes here, move to version section on release
