# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
