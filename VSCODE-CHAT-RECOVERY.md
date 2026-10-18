# Recovering VS Code Copilot Chat History

How to locate and reconstruct GitHub Copilot Chat session history for a VS Code
workspace, straight from disk — no VS Code UI needed. Useful when a project's
real chat history lives in Copilot Chat rather than (or in addition to) Claude
Code's own session storage.

## 1. Find the right workspace storage folder

VS Code keeps one folder per workspace under:

```
~/Library/Application Support/Code/User/workspaceStorage/<hash>/
```

Each folder's identity is confirmed by a `workspace.json` inside it, e.g.:

```json
{"workspace": "file:///Users/you/path/to/project/project.code-workspace"}
```

To find the right one for a given project, grep all of them for the project
name or path:

```bash
grep -ril "<project-name>" ~/Library/Application\ Support/Code/User/workspaceStorage/*/workspace.json
```

Inside the matching folder, chat history lives in `chatSessions/*.jsonl`
(one file per chat session/tab). There's also a `GitHub.copilot-chat/`
subfolder with transcripts/memory-tool data if you need to go deeper.

## 2. Understand the file format (this is the non-obvious part)

Each `.jsonl` file is **not** a plain transcript. It's an event-sourced patch
log:

- **Line 1** (`"kind": 0`) — a full snapshot of the session's initial state:
  `{"v": {"requests": [...], "customTitle": "...", "creationDate": <epoch ms>, ...}}`
- **Every subsequent line** (`"kind": 1` or `"kind": 2`) — an incremental
  patch: `{"kind": 1, "k": [<path segments>], "v": <value>}`. `k` is a path
  into the state object (strings for object keys, integers for array
  indices); `v` is the value to set at that path. In practice, kind 1 vs 2
  didn't functionally differ — both are "set value at path."

To reconstruct state, replay every patch in order, applying each `v` at the
path `k` (creating intermediate objects/arrays as needed).

## 3. The gotcha: compaction silently drops history

GitHub Copilot Chat periodically **compacts** the live `requests` array
(there's a literal `/compact` slash command in the tool metadata baked into
the log). This shows up as a patch like:

```json
{"kind": 2, "k": ["requests"], "v": [ /* just 1-2 request objects */ ]}
```

This **replaces the entire requests array**, discarding earlier turns from
the live state. If you naively replay all patches and only look at the final
state, you will only recover the last 1-2 turns of a session — even from a
multi-megabyte file that represents dozens or hundreds of real turns. (We
confirmed this: one 5.7MB file file evaluated naively yielded 1 turn; properly
recovered, it had 85 real turns. Another had 121, another 125.)

## 4. The fix: snapshot before every full-array replace

Keep a separate archive dict keyed by `requestId`. Every time you're about to
apply a patch where `k == ["requests"]` (a full-array replace), **first**
snapshot the current `requests` array into the archive (keep whichever
version of a given `requestId` has the most complete `response` array, since
a request's response streams in over several patches before the next
compaction event). Also snapshot once more at end-of-file for whatever's
still live. This recovers every real turn across the session's lifetime, not
just the final compacted window.

## 5. Extracting readable text

Per request object in the archived state:

- **User prompt:** `request.message.text`
- **Assistant output:** `request.response` — a list of typed parts. Extract:
  - `kind == "markdownContent"` → prose, in `.content.value` (or `.content`
    if it's a plain string)
  - `kind == "toolInvocationSerialized"` → tool calls, in
    `.pastTenseMessage.value` or `.invocationMessage.value`
  - `kind == "thinking"` → reasoning text, in `.value`

## 6. Assembling the output

Merge turns from all session files, dedupe by `requestId` (keep the fullest
version per the rule above), sort by `timestamp`, and write one combined
markdown log — session header, then `## USER:` / `### ASSISTANT:` pairs in
chronological order.

## Reference implementation

A working Python script implementing all of the above (patch replay,
snapshot-before-compaction, text extraction, multi-file merge) was used to
recover this project's history. See `_chat-history/` in this repo for the
output; the extraction script itself is not committed (it was a one-off
utility) but can be rewritten from the steps above in well under 100 lines —
the core is: a `set_path(state, path, value)` helper, a patch-replay loop
that snapshots `requests` before any `k == ["requests"]` patch, and a text
extractor over the archived request objects.

## Caveats

- This is undocumented, reverse-engineered internal storage format for
  GitHub Copilot Chat in VS Code — it may change between VS Code/Copilot
  extension versions without notice. Validate against a small session file
  first (`wc -l` and inspect a few lines) before trusting it on a large one.
- File `mtime` on the `.jsonl` files does **not** reliably indicate when the
  underlying conversation actually happened — use the `creationDate` field
  in the kind-0 snapshot and each request's own `timestamp` field instead.
- Empty/near-empty session files (a few KB, 0 recovered turns) are normal —
  VS Code creates a session file per opened chat tab even if nothing was
  said in it.
