# Editor.log And Console Reliability — History, Root Causes, Hardening Plan

Date: `2026-08-04`
Scope: every `source=console` / `source=editor_log` lane — `unity_console_grep`, `unity_console_tail`,
`request-console-grep`, `request-console-tail`, `build_editor_log_diagnosis`, `build_editor_log_identity`,
and the `since` anchors added on `2026-08-03`.
Status: analysis + plan. The defects marked **OPEN** are not fixed.

## 1. Why This Surface Keeps Breaking

Seven distinct defect classes have hit this surface across `v0.3.29 → 0.3.54`. They are not seven unrelated
bugs; they are two root causes wearing different clothes.

**Root cause A — the host guesses *which file* to read, and nothing verifies the guess.**
`resolve_editor_log_path()` (`templates/server_editor_host_paths.py:304`) returns the caller's explicit path or
`default_editor_log_path()` = `Library/XUUnityLightMcp/logs/unity_editor.log`. It never consults
`bridge_state.editor_log_path`, which is the only field that says where the editor is *actually* writing. That
default is correct for a host-opened editor (the host passes `-logFile`, 5 call sites in
`server_editor_host_lifecycle.py`) and silently wrong for every editor the operator opened from the Hub or by
double-click.

**Root cause B — a log path is treated as a file identity.**
Unity gives one static path (`Application.consoleLogPath`) whose underlying file is replaced on editor start
(truncation) and on a second editor start (rotation to `Editor-prev.log`). Every guard built so far compares
*paths*, so it cannot see the file change underneath.

## 2. The History

| When | Version | Defect | Fix that shipped | Root cause |
| --- | --- | --- | --- | --- |
| 2026-06 | `0.3.29`+ | `unity.console.grep` default `source=console` returned `match_count: 0` for real compile errors — the console ring buffer had been cleared by a domain reload | `source=editor_log` lane added; clear-on-play / eviction caveats documented | console buffer is lossy |
| 2026-07-06 | — | Retro `first_open_6000_upgrade_apiupdate_modal_and_console_source`: root cause was only found by grepping the raw `-logFile`; MCP console returned false-empty. Scored *time-to-diagnosis 5/10*, *token efficiency 4/10* | `source=editor_log` made the default for grep and tail | same, recurring |
| 2026-07 | `0.3.36` | Foreign platform `Editor.log` mistaken for the project's log | `build_editor_log_identity()` + `newer_foreign_editor_log_detected`, surfaced in status summaries | A / B |
| 2026-07 | `0.3.38` | "Enter Safe Mode?" dialog blocks the editor while Unity writes **no** marker to the log — absence read as health | `log_idle_seconds` + `startup_modal_dialog_block` classification | absence ≠ evidence |
| 2026-07 | `0.3.41` | Prior-session compile blockers read as current truth | freshness fields on `editor_log_diagnosis` | stale content |
| 2026-07-10 | — | Windows deep review: cp866/cp1251 decode kills log/stdio paths; `ensure_ascii=False` raises on RU consoles | UTF-8 stdio end to end, BOM/UTF-16 tolerant reads, `PYTHONUTF8` | encoding |
| 2026-08-03 | unreleased | Retro: an unanchored `until grep -q MARKER` matched a **previous play session's** line and returned immediately | `since=playmode_start\|bridge_generation\|request_id` | no session boundary |
| 2026-08-03 | unreleased | `anchor_log_mismatch`: editor stamps against `Application.consoleLogPath`, host defaults to the project-local log | path comparison + typed refusal | A / B |
| 2026-08-03 | unreleased | `session_start` anchor implemented then **removed**: host stamps size before launch, Unity truncates on start, so the offset belonged to the previous log | anchor deleted | B |
| 2026-08-03 | unreleased | Mid-line offset fabricated a match (`xxNOMARKER` → `MARKER`) | partial leading line dropped | offset arithmetic |
| 2026-08-03 | unreleased | Truncated scope mixed absolute and relative line numbers | `anchored_scope_relative` + `anchor_line` | offset arithmetic |
| 2026-08-04 | unreleased | Windows CI: fixtures assumed LF; `Path.write_text()` translated newlines | fixtures write bytes | offset arithmetic |
| 2026-08-19 | `0.3.58` | Anchored `since=playmode_start` scope of 1,789,547 bytes searched only its last 500,000 (`EDITOR_LOG_GREP_MAX_CHARS`), so a boot-time line in the head was missed and reported as `match_count: 0`. The arithmetic at the truncation boundary was correct — the gap was that a truncated zero-match is inconclusive, not negative, and the cut kept the tail when an anchor asked for the head | **fixed in current source 2026-08-23** — anchored greps keep the anchor-adjacent head, promote an explicit search verdict/window direction, and make partial zero-matches inconclusive with recovery; console tail retains recent-tail behavior | absence ≠ evidence (semantic, not offset arithmetic) |

### Found today (this review + a live consumer-project run)

| Defect | Severity | State |
| --- | --- | --- |
| The same fabricated-match bug reachable through the `max_chars` **truncation** boundary, not just the anchor | High | fixed, proven on a 1,187,704-byte real scope |
| `since` anchors trusted a **stale bridge_state from a dead editor** (the pid-liveness check existed one call away and was bypassed by an `or` fallback) | High | fixed (`anchor_stale_dead_session`) |
| `unity_console_tail` reported wrong absolute line numbers — blank lines filtered before numbering, under a payload newly claiming `editor_log_absolute` | Medium | fixed |
| `since=request_id` anchored with the log identity unverified; `recover-editor-session` deletes `bridge_state.json` and leaves the journal | Medium | fixed (journal stamps `editor_log_path`) |
| **`request-console-tail` was never bound to a callable** — registered in the parser, missing from the `server_cli_commands` re-export, so it printed help and exited 1. The documented CLI `--since` lane had never run. `ui-vision-packet`, `ui-vision-submit`, `ui-interaction-validate` were dead the same way | High | fixed + a sweep test over every subcommand |
| **`Editor.log` → `Editor-prev.log` rotation on a second editor.** `lsof` proof on a two-editor host: the consumer project's editor writes `Editor-prev.log` (5.3 MB, growing) while `consoleLogPath` returns `Editor.log` (3.1 MB, owned by the other editor's process). Path equality, size, and liveness all pass | High | guard added (`anchor_log_rotated`), **remediation OPEN** — see §4.1 |
| **The default `source=editor_log` lane reads a stale file for any editor the host did not open.** Measured at 13:00:37Z with a `healthy` heartbeat: default log mtime `Aug 3 21:41` (12 h stale), real log mtime `Aug 4 09:52`. Grep returned a match from the stale file with `result_trust_class: editor_log_path_backed_untyped` and no staleness signal | **High** | **OPEN** |

## 3. What Is Already Solid (do not rebuild)

- The console-buffer lossiness story is closed: `editor_log` is the default, and both false-negative
  (clear-on-play, eviction) and false-positive (stale match) caveats are typed fields, not prose.
- Session scoping works and degrades honestly: `anchor_unavailable`, `anchor_stale`, `anchor_log_mismatch`,
  `since_anchor_degraded`, `result_trust_class`. Verified against a real 3.1 MB log.
- Offset arithmetic is now correct at both boundaries (anchor and truncation), CRLF-safe, and covered by tests
  derived from executed reproductions rather than reasoning.
- `build_editor_log_identity()` already enumerates candidate logs and scores each with
  `same_project_evidence` (does the log mention this project root) and `newer_than_active`.

## 4. Hardening Plan

Ordered by how much false evidence each removes.

### 4.1 P0 — Resolve the log *lane*, and report it on every payload

The single change that closes root cause A. Today the payload says which path it searched but never whether that
path is the right one.

- `resolve_editor_log_path()` must prefer `bridge_state.editor_log_path` when a **live** bridge reports one, over
  the host default. Explicit `editorLogPath` still wins.
- Add a typed `log_lane` block to every `source=editor_log` payload:
  - `host_owned_logfile` — the host launched the editor with `-logFile`; path and writer agree.
  - `editor_reported_platform_log` — a hand-opened editor; using the path the editor itself reports.
  - `rotated_sibling` — the reported path predates its own stamp; the writer is the `-prev` sibling.
  - `stale_not_written_by_live_editor` — a live, healthy heartbeat but the log's mtime is far older than it.
    **Refuse or degrade loudly; never return matches as if fresh.**
- Carry `editor_log_mtime_utc`, `editor_log_age_seconds`, and `heartbeat_age_seconds` so an operator (or an
  agent) can see the contradiction without a second call.
- Regression: a live-heartbeat + stale-log fixture must not yield a silent match. This is the case measured in
  §2 and it is the one currently shipping.

### 4.2 P0 — Make `anchor_log_rotated` remediation followable

The guard added today fails closed, which is right, but its advice ("pass `editorLogPath=Editor-prev.log`") then
trips `anchor_log_mismatch`, because that check compares the searched path against the stamped path. The two
guards deadlock: on a two-editor host neither the stamped path nor the real log anchors.

Fix: forward-resolve a rotated stamp. When the stamped path predates its stamp and the `-prev` sibling postdates
it, treat the sibling as the stamped log's identity and anchor against it, reporting
`anchor_log_forward_resolved` with both paths. Add `-prev` to `platform_editor_log_candidates()` so
`build_editor_log_identity` can see it too.

### 4.3 P1 — Verify file identity, not path equality

Close root cause B for good. Options, cheapest first:

- **mtime-vs-stamp** (shipped today): a log the editor is writing cannot be older than the stamp describing it.
  Portable, catches rotation and truncation. Already in `_log_predates_its_own_stamp`.
- **stamp a creation time**: the editor writes `File.GetCreationTimeUtc(consoleLogPath)` beside each offset; the
  host compares. Catches same-second rotation that mtime cannot. Degrades open where the filesystem lacks
  birthtime, so it is additive, not a replacement.
- **stamp a head signature**: first 256 bytes of the log at stamp time. Strongest, costs one small read per
  stamp — acceptable in `ProcessDecodedRequest`, **not** in a tick (see `skills/editor_main_thread`).

### 4.4 P1 — Close the plumbing class permanently

The `request-console-tail` defect was invisible to review because the binding is a name lookup
(`getattr(server_cli_commands, func_name)`) that silently yields `None`. The sweep test added today
(`CliCommandBindingTests`) fails if any subcommand loses its callable. Two follow-ups:

- assert every `TOOLS` entry with a `bridgeOperation` resolves to a registered editor operation, the MCP-side
  twin of the same class;
- assert every documented CLI flag in `SMOKE_TESTS.md` exists in `build_parser()`, so a documented lane cannot
  be undeliverable.

### 4.5 P2 — Absence is still not evidence

Documented in `README.md` but not enforced. A `match_count: 0` on a lane where the marker *cannot* appear should
say so: when the project installs a filtering log target, plain `Debug.Log` never reaches the captured log. The
retro's recommendation stands — prefer a state assert or a journal receipt over log absence — and the payload
could name it (`absence_proof_class: not_provable_by_log`).

### 4.6 P2 — One acceptance case per historical defect

`SMOKE_TESTS.md` cases 21–23 cover the 2026-08-03 batch. Each row in §2 deserves one, so the suite encodes the
history rather than the last incident. The host-side runner added today
(`scripts/testing/run_anchor_regression_on_project.py`) is the right home for the ones that need a real
multi-megabyte log: it already proves the truncation boundary, the mismatch refusal, the rotation refusal, and
the journal identity stamp against a live editor.

## 5. Verdict

The evidence *semantics* on this surface are now good — every degradation has a name, and the trust classes are
honest. What is still weak is one layer below: **which file the host opens.** Root cause A has never been fixed;
it was worked around three times (project-local default, foreign-log detection, `anchor_log_mismatch`) and it
produced two of today's three High findings. Until §4.1 lands, `unity_console_grep source=editor_log` — the lane
the docs recommend for compile-error decisions — can return matches from a 12-hour-old file while a healthy
editor writes somewhere else, and say nothing.
