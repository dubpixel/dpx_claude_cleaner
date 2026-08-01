# Release Notes

Filled in from `dpx_release_note_template.md` for MAJOR/MINOR releases only
(patch releases are tracked in `CHANGELOG.md`).

---
## [0.3.0](https://github.com/dubpixel/dpx_claude_cleaner/compare/v0.2.2...v0.3.0) (2026-07-31)

> Adds a dedicated way to gather sessions you've marked for cleanup, on top
> of the title-accuracy and browsing fixes shipped in 0.2.x.

### Upgrade Steps
* None — pull latest and re-run `scripts/deploy_local.sh` if you're using
  the `zazzle` shell alias.

### Breaking Changes
* None.

### New Features
* `s` key in the TUI: sorts sessions with "delete" (case-insensitive) in
  the title to the top of the list, still shown alongside everything else
  — pairs with the existing habit of renaming sessions you're done with to
  "delete this" before bulk-cleaning them up.

### Bug Fixes
* None in this release (see 0.2.x below, and `CHANGELOG.md` for the
  patch-level fixes that landed alongside this).

### Performance Improvements
* None.

### Other Changes
* None.

---
## [0.2.0](https://github.com/dubpixel/dpx_claude_cleaner/compare/v0.1.3...v0.2.0) (2026-07-31)

> First release with a real filesystem browser for the move/rehome flow,
> replacing blind path typing.

### Upgrade Steps
* None.

### Breaking Changes
* None.

### New Features
* Real filesystem browser (`browse_filesystem()`) for picking a move
  destination: navigate actual directories with `j`/`k`/`ENTER`, seeded
  with shortcuts to `~`, `~/Code`, and `~/Circuits`, instead of typing an
  absolute path blind. Replaces the old `n` = "type a path" flow in the
  move project picker.

### Bug Fixes
* None in this release (title/scope fixes landed in the following 0.1.3
  and 0.2.1 patch releases — see `CHANGELOG.md`).

### Performance Improvements
* None.

### Other Changes
* None.
