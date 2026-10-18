# vazzle — VS Code Copilot Chat cleaner (plan)

Companion tool to `zazzle` (`dpx_claude_Cleaner.py`), same project, same repo,
**separate script**. Cleans up GitHub Copilot Chat session history in VS
Code the same way `zazzle` cleans up Claude Code sessions: browse, flag
orphans, rename, delete. Grounded in `VSCODE-CHAT-RECOVERY.md` (real,
verified on-disk format — read that first, this plan assumes it).

**Hard constraint: do not modify `src/dpx_claude_Cleaner.py`, `scripts/deploy_local.sh`,
or anything `zazzle` depends on.** New, independent files only, even where
that means duplicating a small amount of code (e.g. the readline/TUI
helpers). Independence > DRY here — `zazzle` works, don't risk it.

---

## 1. What's actually on disk (verified against real data this session)

```
~/Library/Application Support/Code/User/workspaceStorage/<hash>/
  workspace.json              # {"workspace": "file:///real/exact/path"} -- EXACT, no lossy decode needed
  chatSessions/
    <uuid>.json                # older/simple format: one flat JSON object, full state
    <uuid>.jsonl                # newer format: event-sourced patch log (see below)
  chatEditingSessions/
    <uuid>/                    # file-edit history tied to a chat session -- same uuid as chatSessions
  state.vscdb                  # sqlite key-value store -- VS Code's own UI state/cache. UNKNOWN whether
                                # it caches session lists/titles. Treat as read-only / don't touch in v1
                                # (see Open Questions).
```

Both `.json` and `.jsonl` chat session files can exist side by side in the
same `chatSessions/` folder on the same machine — the code must handle both.

### `.json` (flat) format
Single JSON object. Relevant fields: `sessionId`, `customTitle` (nullable),
`creationDate`, `lastMessageDate` (epoch ms), `requests[]`, `isImported`.
Parse directly, no reconstruction needed.

### `.jsonl` (patch log) format — the non-obvious one
Per `VSCODE-CHAT-RECOVERY.md`:
- Line 1 (`"kind": 0`): full snapshot — `{"v": {...same shape as the flat
  format...}}`
- Every later line (`"kind": 1` or `2`): a patch — `{"k": [path segments],
  "v": value}`. Replay by setting `value` at `path` in the live state
  (creating intermediate dicts/lists as needed).
- **The trap:** Copilot Chat periodically compacts, emitting a patch with
  `k == ["requests"]` that **replaces the whole array**, silently dropping
  earlier turns from the live state. A naive "replay everything, read final
  state" implementation recovers only the last 1-2 turns of a
  multi-hundred-turn conversation. Confirmed on real files (5.7MB file →
  1 turn naive vs. 85 turns recovered correctly).
- **The fix:** keep a separate archive dict keyed by `requestId`. Before
  applying any patch where `k == ["requests"]`, snapshot the current live
  `requests` array into the archive first (keep the fullest version — the
  one with the longest `response` array — if a `requestId` already exists
  there, since a response streams in across several patches before the next
  compaction). Snapshot once more at end-of-file for whatever's still live
  and never got compacted. The archive, not final live state, is the real
  data.

### Extracting readable text (either format, from the reconstructed state)
- User prompt: `request.message.text`
- Assistant output: walk `request.response[]`, per part:
  - `kind == "markdownContent"` → prose, in `.content.value` (or `.content`
    if it's a plain string)
  - `kind == "toolInvocationSerialized"` → tool calls, in
    `.pastTenseMessage.value` or `.invocationMessage.value`
  - `kind == "thinking"` → `.value`

---

## 2. Data model (per session, mirroring zazzle's session dict shape)

```python
{
  "session_id":        str,
  "workspace_hash":    str,          # parent workspaceStorage/<hash> dir name
  "path":              Path,         # the .json or .jsonl file itself
  "project_path":      str,          # decoded from workspace.json -- exact, no lossy decode
  "project_exists":    bool,         # does that folder still exist on disk?
  "title":             str,          # customTitle, else first user message snippet, else session_id
  "title_from_index":  bool,         # customTitle present?
  "creation_date":     datetime,
  "last_message_date": datetime,
  "turn_count":         int,          # len(archived requests) -- the CORRECTED count, not len(final requests)
  "size_bytes":        int,
  "is_orphan":         bool,         # == not project_exists (the vazzle equivalent of zazzle's is_orphan)
  "format":            "json" | "jsonl",
  "selected":          bool,
}
```

`project_exists` / `is_orphan` is actually a *cleaner* signal than zazzle's
orphan concept: it's a direct filesystem check on the real path from
`workspace.json`, not "is there an index entry with no matching file." No
`sessions-index.json`-style staleness problem exists here at all — nice.

---

## 3. Feature scope — v1 (core), matches zazzle's proven shape

- **Browse/list**, scoped to current project by default (same `g` toggle
  UX as zazzle — mirrors it, doesn't share code with it)
- **Flag orphans**: workspace folder no longer exists (`!` column, same
  meaning as zazzle's orphan flag conceptually, different mechanism)
- **Delete**: remove the `chatSessions/<uuid>.json`/`.jsonl` file **and**
  the matching `chatEditingSessions/<uuid>/` directory if present (that's
  the file-edit history tied to the same chat — leaving it behind is the
  same kind of orphaned-data problem this whole tool exists to clean up)
- **Rename**: set/patch `customTitle`.
  - `.json`: rewrite the field in place (simple, same risk profile as
    zazzle's summary-line injection).
  - `.jsonl`: **append** a new patch line `{"kind": 1, "k": ["customTitle"],
    "v": "new title"}` rather than rewriting the whole file — consistent
    with the format being an append-only patch log, same spirit as zazzle
    never rewriting `.jsonl` bodies.
- **Bulk export / "dump" instead of AI-summarize** (per your call — skip
  the summarization step, just recover and dump): for a session or a whole
  project's worth of sessions, run the reconstruction algorithm from §1 and
  write a plain markdown transcript. Where to write it is worth a UI
  choice, not a hardcoded default — offer both:
  - into the *live* project folder itself, e.g.
    `<project>/_chat-history/<title-or-id>.md` (this repo already
    established that exact convention once, per `VSCODE-CHAT-RECOVERY.md` —
    reuse it), so a later Claude Code session in that project can just read
    it, or
  - to a fixed export location (e.g. `~/vazzle-exports/`) when the project
    folder is gone (orphan) or you don't want to write into it
- **CLI modes**, mirroring zazzle: `analyze` (stats), `help`. Skip
  `fix-orphans` — there's no index to reconcile here, orphan-ness is just a
  filesystem check, nothing to "fix."

## Deferred (not v1, but a real design question you asked about)

**"Move" a session to a different VS Code workspace** — is it possible?
**Yes, conditionally, with real risk:**

- VS Code identifies a workspace storage folder by a hash of the workspace
  URI. The hash algorithm is internal/undocumented — we have not verified
  it. That means:
  - Moving a session **into an already-known workspace** (one whose
    `workspaceStorage/<hash>/workspace.json` already exists because you've
    opened that folder in VS Code before) is *plausible*: copy the
    `chatSessions/<uuid>.*` file and matching `chatEditingSessions/<uuid>/`
    into that existing hash folder. Real risk: `state.vscdb` may cache a
    session list VS Code reads instead of re-scanning the folder on
    startup, so the moved session might not appear in VS Code's own UI even
    though the file is in the "right" place, until we understand what's in
    that sqlite file.
  - Moving to a workspace VS Code has **never opened** would require either
    (a) reverse-engineering the hash function well enough to create a
    correctly-named folder ourselves, or (b) opening that folder in VS Code
    once first (out of band) so VS Code creates the folder itself, then
    dropping the files in. Option (a) is real reverse-engineering of
    undocumented internals — not something to build on a guess.
- **Recommendation**: present this as an explicit, clearly-labeled
  experimental option later (v2+), not in v1, and only for the
  already-known-workspace case. Verify against real `state.vscdb` behavior
  (does VS Code notice a file dropped in while it's closed? does it care at
  all, or does it just glob `chatSessions/*` fresh on open?) before trusting
  it with anyone's actual data.

---

## 4. Testing

Same pattern as zazzle's `tests/`: synthetic fixtures in temp dirs, stdlib
`unittest`, added to the *existing* `tests/` directory as new files (picked
up automatically by `python -m unittest discover -v` and the existing CI
workflow — zero changes needed to `.github/workflows/tests.yml`).

Non-negotiable test case, given §1's whole point: a synthetic `.jsonl` fixture
that includes a compaction event (a `k == ["requests"]` patch that shrinks
the array) and asserts the archive-based reconstruction recovers **all**
turns, not just the post-compaction ones. This is the single most important
correctness property of the whole tool — the recovery doc exists because a
naive implementation silently loses data.

Other cases: `.json` flat parsing, `workspace.json` → real path resolution,
orphan detection, rename (both formats), delete (session file +
matching chatEditingSessions dir), markdown export formatting.

---

## 5. File layout / deploy (fully independent of zazzle)

- `src/dpx_vscode_Cleaner.py` — new, standalone script. Can structurally
  mirror `dpx_claude_Cleaner.py`'s shape (discovery → operations → TUI →
  CLI) since that shape is proven, but no shared imports between the two
  files.
- `scripts/deploy_local_vazzle.sh` — new, separate deploy script. Same
  zsh/bash-detection logic as `deploy_local.sh` (copy, don't extract into a
  shared helper — see hard constraint above), deploys to `~/scr/vazzle`,
  wires up a `vazzle` alias.
- `tests/test_vscode_*.py` — new files in the existing `tests/` dir.
- Docs: new `## vazzle` section in `README.md`/`CLAUDE.md` once it exists,
  same pattern as the existing zazzle docs — don't touch the existing
  zazzle sections beyond adding a sibling.

---

## Open questions to resolve during build, not before

1. What's actually in `state.vscdb`? (sqlite — needs a real read with
   `sqlite3` to know if it caches session titles/lists that could go stale
   after a direct file delete/rename, same category of problem as Claude
   Code's `sessions-index.json`.) Directly relevant to whether delete/rename
   need to touch anything beyond the filesystem.
2. Exact "most complete response" comparison heuristic when archiving
   before a compaction patch — the recovery doc says "keep whichever is
   more complete"; need to nail this down against a couple of real
   multi-compaction session files (longest `response` array is the
   working assumption, verify it holds).
3. Whether `chatEditingSessions/<uuid>/` always exists 1:1 with a chat
   session that has file edits, or can be more/less than 1:1 — affects the
   delete logic's cleanup step.

---

## Not doing (explicitly out of scope for now)

- AI-generated summaries of chat history (your call — bulk markdown dump
  covers the actual need)
- Cross-machine sync / Windows or Linux paths (this machine is macOS;
  revisit if it matters later — the `~/Library/Application Support/Code/User/`
  path is macOS-specific, Linux/Windows use different base dirs)
- The "move to a never-before-seen workspace" case from §3 (real
  reverse-engineering risk, not worth it for v1)
