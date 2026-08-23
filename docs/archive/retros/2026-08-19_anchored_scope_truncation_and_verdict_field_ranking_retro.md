# XUUnity Light Unity MCP Chat Retro — Anchored Scope Truncation and Verdict-Field Ranking

Date: `2026-08-19`
Status: `P1 anchored-window and verdict-ranking slice implemented in current source; P2/P3 residuals open`
Lane: interactive chat, boot-time authenticated payload capture in a consumer project

## 1. Executive Summary

A session needed one boot-time log line to prove an authenticated request had reached a server. It took three attempts.
Two of them returned `match_count: 0` from `unity_console_grep` while the line was present in the log the whole time.

Attribution matters more than the symptom, so it leads:

| Finding | Attribution | One-line basis |
| --- | --- | --- |
| P0-1 anchored scope searched only its tail | **product limitation** | `EDITOR_LOG_GREP_MAX_CHARS = 500000` is a module constant in `templates/server_health.py`, exposed on neither the MCP tool surface nor the CLI. No operator action can widen it. |
| P0-2 wrong log file searched | **operator error** | `unity_status_summary` had already returned the risk *and* the exact remediation in the first call of the session. The grep was issued without it. |
| P1 stale test set after a source edit | **operator error** | The runner ran what the editor had compiled. A disk write is not an import. |

The reusable product finding is narrow and worth fixing: **when a scope is truncated and nothing matched, the result is
inconclusive, not negative — and it is not reported that way in the field an operator reads as the answer.** The
anchored case makes it sharper. `since=playmode_start` means "from this point forward", while the `max_chars` cut keeps
the **tail** of that scope (see the boundary comment in `read_anchored_editor_log_scope`). For a boot-time line that is
precisely the wrong end: the anchored scope was `1789547` bytes, the search covered the last `500000`, and the target
line sat in the first 1.3 MB that was never read.

The reusable operator finding is the mirror image: every correction the payload offered lived in a field that reads as
metadata — `log_lane`, `since_anchor.resolved`, `scope_truncated`, `editor_launch_lane_risk` — while `match_count`
reads as the verdict. Both operator errors in this session are the same mistake: trusting the headline over the
classification the tool had already computed.

## 2. Evidence Base

- `unity_status_summary` (first call of the session): `editor_launch_lane: "not_opened_by_host"`,
  `editor_launch_lane_risk: "host_default_editor_log_path_may_be_stale"`,
  `editor_launch_lane_recommended_next_action: "pass editorLogPath=<bridge_state.editor_log_path> to console log
  queries, or reopen the project through ensure-ready --open-editor"`. Also `detected_editor_count: 1`,
  `health_status: healthy`, `newer_foreign_editor_log_detected: false`.
- `unity_console_grep` attempt 1, no `editorLogPath`: `match_count: 0`,
  `log_lane.lane: "stale_not_written_by_live_editor"`, `log_lane.lane_reason` naming an 11-second heartbeat against a
  log unwritten for 435020 seconds, `since_anchor.resolved: "anchor_log_mismatch"` with an explanation that the offset
  had been measured against a different file, plus `log_lane_caveat` and `result_trust_class:
  "editor_log_spans_multiple_sessions"`.
- `unity_console_grep` attempt 2, explicit `editorLogPath`: `match_count: 0`,
  `since_anchor.resolved: "playmode_start"`, `anchored: true`, `start_offset_bytes: 3969233`,
  `scoped_bytes_available: 1789547`, `scope_truncated: true`, `searched_tail_chars: 500000`,
  `log_lane.lane: "editor_reported_platform_log"`, `since_anchor_degraded: false`.
- `unity_console_tail` with `maxPayloadBytes`, same scope: 40 items, `payload_bytes_estimate: 8739`, dominated by
  async-framework stack frames rather than message lines.
- Direct file read from `since_anchor.start_offset_bytes`: 52 matches immediately.
- `templates/server_health.py:20` — `EDITOR_LOG_GREP_MAX_CHARS = 500000`; no `max_chars` entry in
  `templates/server_specs_tools.py` or `templates/server_cli_parser.py`.
- `unity_tests_run_editmode` before a refresh: `total: 203`, `status: passed`,
  `persisted_test_result_reconciliation: "reconciled"`, `post_settle_compile: "passed"`. After
  `unity_project_refresh`: `total: 204`.
- Clean lanes, for calibration: `unity_scene_open`, `unity_playmode_set` enter and exit
  (`completion_basis: "unity_playmode_transition_watcher"`), `unity_compile_player_scripts` for two targets, and eleven
  `unity_project_refresh` calls, all with `post_settle_compile_trust_class: "confirmed"`.

## 3. Timeline

1. `unity_status_summary` — healthy, single editor, and the log-lane risk stated with its remediation. The risk field
   was read and not acted on.
2. Feature work: refreshes, compiles, EditMode runs. All compact, all `confirmed`, no friction.
3. Play mode entered from an explicitly opened boot scene; the app reached the target request.
4. `unity_console_grep` without `editorLogPath` → `match_count: 0`. The tool refused the anchor by name rather than
   applying a cross-file offset.
5. `unity_console_grep` with the explicit path → `match_count: 0` again, now with `scope_truncated: true` next to a
   1.79 MB scope. Instead of reading that, the session checked play-mode liveness and pulled a tail, which returned
   mostly stack frames.
6. Direct read from the reported anchor offset → 52 matches. Total cost: three extra round trips and one ~8.7 KB tail
   pull for a line that was always there.
7. Later, a test file was edited on disk and the run reported the previous total until a refresh reimported it.

## 4. What Worked Well

- **Refusal by name over silent degradation.** `anchor_log_mismatch` with a written reason is exactly right. Applying a
  byte offset measured against a different file would have scoped the search to an arbitrary position and produced a
  plausible wrong answer instead of an obvious wrong answer.
- **Lane classification was correct and complete.** `stale_not_written_by_live_editor` with an mtime-versus-heartbeat
  comparison in `lane_reason` is a diagnosis, not a hint.
- **Pre-warning with remediation.** The status summary named the risk before any log query was made, in the first call
  of the session, with the flag to pass. Nothing more could reasonably be asked of the tool here.
- **Compact operation summaries earned their keep.** Eleven refreshes, four target compiles and six test runs stayed
  cheap and decisive — `post_settle_compile`, `error_count`, `trust_class`, `completion_basis`. Every compile-blocking
  error was caught by the refresh that followed the edit, with a file and line, in one field.
- **Group-filtered EditMode runs** made "did the new tests actually execute" answerable in one cheap call, which caught
  the stale-test-set case at step 7.

## 5. What Worked Poorly

- **A truncated search that reports zero as a result.** Two fields say the scope was cut; one field says nothing
  matched. Only the second reads like an answer.
- **The cut keeps the wrong end for an anchored search.** Anchoring is a "from here forward" gesture. Keeping the tail
  serves a "what just happened" query and defeats a "what happened at the start of this session" query, which is the
  common case for boot, init and first-request evidence.
- **No operator control and no documented ceiling.** The constant is not on the tool surface, not on the CLI, and not in
  the operator docs, so the ceiling can only be discovered by hitting it and reading a nested field.
- **Untyped tail is the wrong fallback.** With grep truncated, the natural next reach is `unity_console_tail`, whose
  editor-log lane is untyped and dominated by async stack frames. It spent payload without moving the diagnosis.
- **Benign trust warnings dull the trust fields.** `playmode_state_after_settle_trust_class: "stale_risk"` with
  `bridge identity changed during post-request settle` appeared on nearly every refresh and was benign every time. A
  warning that is almost always noise trains operators to skim exactly the fields P0-1 and P0-2 needed them to read.

## 6. What Was Not Explicit Enough

- The relationship between `since` and `searched_tail_chars`. Anchoring implies a scope; the cap silently redefines it.
- Which end of a truncated scope was searched. `scope_truncated: true` does not say "tail kept, head discarded".
- That `match_count: 0` under truncation is not evidence of absence.
- That a source edit on disk is invisible to a test run until an import, and that a passing run with a familiar-looking
  total can therefore be answering about the previous file.

## 7. What The Operator Needed But Did Not Have

1. One verdict-shaped field saying `inconclusive` when a scope was truncated and nothing matched.
2. A way to widen or re-aim the window, or an automatic anchor-adjacent search when a scope exceeds the cap.
3. A stated ceiling in the operator docs, so the limit is knowable before it is hit.
4. A "source changed on disk since the last import" marker on compile and test results.

## 8. Scoring

| Category | Score | Note |
| --- | --- | --- |
| Unity-side execution stability | 10/10 | Nothing failed Unity-side. Scene open, play-mode enter and exit, four target compiles, six test runs, eleven refreshes — all clean. |
| Request journaling quality | 8/10 | Journal head and request ids surfaced on every operation; not stressed this session. |
| Bridge health observability | 9/10 | The status summary diagnosed the log-lane risk before it mattered and carried the remediation. |
| Wrapper-to-operator clarity | 6/10 | The classifications were correct but ranked below the field that reads as the answer. |
| Recovery guidance quality | 9/10 | Both the launch-lane risk and the anchor refusal came with the concrete next action. |
| Transport lifecycle transparency | 9/10 | `post_settle_compile`, `trust_class`, `completion_basis` and settle phase were unambiguous throughout. |
| End-to-end trustworthiness during churn | 8/10 | Bridge identity changed across refreshes and every follow-up read confirmed `edit`; correct, but the repeated warning is desensitising. |
| Parallel request handling | not exercised | Strictly sequential session; no evidence either way. |
| Token efficiency of the default operator path | 7/10 | Compact summaries were excellent. The single detour — a truncated grep plus an untyped tail — cost roughly 9 KB and three round trips for one line. |
| Time-to-diagnosis | 6/10 | Two confident false negatives before the payload was read properly. |
| Validation workflow discipline | 8/10 | Compile-first ordering held and refreshes followed edits, with one lapse: a test run before the refresh that would have imported the edited test. |

**Overall: PASS.** No Unity-side or transport failure. One product change worth shipping, and two operator habits worth
writing into the docs.

## 9. Priority Improvements

**P1 — report a truncated zero-match as inconclusive.** When `scope_truncated` is true and `match_count` is `0`, set
the verdict-shaped field to inconclusive and name the remedy, exactly as `anchor_log_mismatch` already does for the
anchor case. Absence of proof from a partial scope is not proof of absence.

**P1 — for an anchored scope, search the anchor-adjacent window.** When an anchor resolves and the scope exceeds the
cap, keep the window at the anchor rather than at the tail, or state the direction in the payload and let the caller
choose. Boot, init and first-request evidence lives at the head of an anchored scope.

**P2 — expose the window on the tool and CLI surface** with the current constant as the default, and state the ceiling
in the console-lane docs so it is knowable before it is hit.

**P2 — mark stale sources on compile and test results.** A cheap "source changed on disk since the last import"
indicator turns a familiar-looking total into a caught mistake.

**P3 — quiet the benign settle warning.** When a follow-up state read confirms the state, downgrade
`bridge identity changed during post-request settle` from `stale_risk`. Trust fields only work while they are rare.

## 10. Public-Promotion Recommendations

- `docs/archive/reports/2026-08-04_editor_log_and_console_reliability_history.md` — add a dated row: the truncation
  boundary is arithmetically correct and tested, and the remaining gap is semantic, so this is a new failure mode in an
  already-tracked family rather than a regression of a fixed one.
- `docs/operations/SMOKE_TESTS.md` — a troubleshooting branch for zero matches under `scope_truncated: true`, with the
  anchor-offset direct-read fallback as the interim workaround.
- `README.md` and the console-lane tool docs — state the search ceiling and the tail-keeping behaviour.
- `docs/architecture/ROADMAP.md` — the two P1 items.
- Operator guidance, wherever the console lane is documented: treat `log_lane`, `since_anchor.resolved`,
  `scope_truncated` and `editor_launch_lane_risk` as verdict fields. In this session every needed correction was
  already in one of them.

## 11. Final Verdict

The product was right about everything it was asked and wrong about nothing it claimed. It also let a partial answer
occupy the shape of a complete one, twice, and that is the fixable part. Two of the three findings were operator errors
against guidance the tool had already volunteered — which is itself the strongest argument for the P1 ranking change:
a classification an operator skips is functionally the same as a classification that was never computed.

## 12. Implementation Closeout — 2026-08-23

Current source closes both P1 items as one anchored-grep verdict slice:

- bounded anchored greps keep the anchor-adjacent head rather than the scope
  tail, preserving early boot/init evidence
- the payload promotes `search_verdict`, `search_verdict_reason`,
  `scope_truncated`, `search_window_direction`, and `searched_window_chars`
- a partial zero-match is explicitly `inconclusive`, carries
  `session_scoped_editor_log_partial_scope`, and names recovery; only a
  complete anchored zero-match is `not_matched`
- a partial trailing line at the head-window boundary is dropped before regex
  matching, so the new cut cannot fabricate an end-anchored match
- `unity_console_tail` retains its separate recent-tail behavior

Focused host regression covers early-marker recovery, partial-zero verdicts,
complete-scope negatives, truncation-boundary regex safety, absolute line
numbering, and tail compatibility. The focused host surface is green across
213 tests. Live regression is also green in Unity 2022.3.62f3 (14/14 package
EditMode and 5/5 PlayMode tests) and Unity 6000.0.58f2 (6/6 compile lanes,
10/10 acceptance steps, contract, lifecycle, churn, and project-action
consistency). The full host suite ran 932 tests; its only six errors were
sandbox-denied TCP loopback binds, unrelated to the Editor.log path.

Remaining scope is intentionally deferred: P2 window-size control and
source-on-disk import freshness, plus the P3 benign settle-warning downgrade.
