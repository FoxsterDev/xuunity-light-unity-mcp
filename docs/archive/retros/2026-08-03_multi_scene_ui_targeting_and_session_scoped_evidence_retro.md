# XUUnity Light Unity MCP Chat Retro — Multi-Scene UI Targeting and Session-Scoped Evidence

Date: `2026-08-03`
Status: `active public retro`
Session shape: a long feature session (one shared runtime widget rolled across five consumer projects) that ended in an interactive editor verification attempt.

## 1. Executive Summary

No Unity-side operation failed in this session. Every wrapper-reported failure was environmental: a stale bridge from a closed editor, three `editor_running_batch_conflict` refusals from live editors, and one play-mode-blocked player compile. All were correctly detected, correctly named, and correctly recovered.

The session's real costs came from three evidence surfaces, not from execution:

1. **UI read/click tools resolve targets in the active scene only.** In a project that keeps a bootstrap scene active and loads screens additively — and keeps shared overlays under `DontDestroyOnLoad` — `unity_ui_query` / `unity_ui_tree_snapshot` / `unity_ui_click` cannot reach the UI the operator is looking at. The failure surfaces as `ui_target_not_found: No GameObject named 'X'`, which reads like "that object does not exist" rather than "that object is outside the resolvable scope". The interactive verification the operator asked for was impossible to complete, and that only became clear after five probing calls.
2. **Log-based verification has no session boundary.** A `source=editor_log` grep searches a fixed tail (500,000 chars) of a log that accumulates across editor sessions and play sessions. A shell `until grep -q "<marker>"` wait loop matched a line written by a *previous* play session and returned immediately — a false positive. There is no "since play-mode start" or "since bridge generation N" anchor.
3. **Absence of a log line is not evidence.** Plain `UnityEngine.Debug.Log` output from project-side hook classes appeared only 4 times in a 65k-line project log, because the consumer's log-target configuration filters it. Two separate diagnoses in this session initially treated "no marker line in the log" as "the hook did not fire"; in one case the compiled assembly provably contained the call. Nothing in the tool output warns that the console/log channel may be lossy for plain `Debug.Log`.

The strongest surfaces were bridge health and recovery: a stale `bridge_state.json` with a dead `editor_pid` was classified (`stale_state_without_live_editor`), and `recover-editor-session` plus `ensure-ready --open-editor` restored a working lane with no operator guesswork.

## 2. Evidence Base

- request journal entries under `Library/XUUnityLightMcp/journal/requests/*.json`, including the lifecycle-reset event `..._request_reclassified.json` (`settled_after_lifecycle_reset`) emitted when entering play mode
- `bridge_state.json` liveness classification: `state_present: true`, `state_is_live: false`, `editor_pid_alive: false`, `stale_reason: editor_pid_not_alive`
- wrapper output of `recover-editor-session` (`recovery_classification: recovered`, `stale_bridge_state_cleared: true`, `recommended_next_action: open_editor_or_ensure_ready`) and of `ensure-ready --open-editor`
- three batch refusals with `code: editor_running_batch_conflict`, each carrying `live_project_editor_pids`, `recommended_recovery_command`, and `batch_failure_summary.transport_outcome: batch_prepare_blocked`
- one `compile_player_scripts_failed: "Unity editor is busy. isCompiling=False, isPlayingOrWillChangePlaymode=True, isUpdating=False"`
- compact operation envelopes from `unity.project.refresh`, `unity.compile.player_scripts`, `unity.tests.run_editmode`, `unity.tests.run_playmode` (all `payload_mode: compact_operation`)
- full-payload envelopes from `unity.status`, `unity.playmode.state`, `unity.playmode.set`, `unity.game_view.screenshot`, `unity.ui.*` (no compact mode)
- one `unity_game_view_screenshot` call with `includeImage: true` that produced a 184,659-character result and was spilled to a host tool-results file instead of being returned
- `unity_ui_query` / `unity_ui_tree_snapshot` responses whose `target.scene_name` stayed pinned to the active bootstrap scene while the screen under test lived in an additively loaded scene
- multi-project batch matrix aggregate summaries (`projects_total`, `projects_failed`, `operator_verdict_counts`) across four runs

## 3. Timeline

1. Source edits across one shared package and five consumer projects.
2. `unity_status` on the shared project → `editor_not_running` with stale bridge state; recovery command surfaced verbatim.
3. `recover-editor-session` cleared stale state but did not open an editor; `ensure-ready --open-editor` brought the lane up. Both steps were needed and only the second was obvious from the first response.
4. Compile-first validation: refresh → player compile (two targets) → EditMode assembly filter → PlayMode assembly filter. One PlayMode filter miss (`test_filter_no_match`) was resolved by naming the correct test assembly.
5. Multi-project batch matrix, four runs across the session. Runs 1, 3, 4 each hit `editor_running_batch_conflict` for whichever projects the operator had open at that moment; those projects were then verified through the interactive lane instead.
6. One player compile refused because the project was in play mode.
7. Interactive verification attempt: play mode entered via MCP, screenshots captured, then five probing `unity_ui_*` calls all returned `ui_target_not_found` because the targets were in additively loaded scenes and `DontDestroyOnLoad`.
8. Log-based fallback verification: a wait loop matched a stale marker line, then a corrected offset-anchored loop worked; a missing marker line led to an assembly-level string check to prove the call site existed.

## 4. What Worked Well

- **Stale-bridge classification and recovery.** Dead-pid detection, a named `stale_reason`, and a copy-paste recovery command removed all guesswork.
- **Live-editor batch refusal.** Refusing the closed-project lane while an editor is open prevented library corruption, and each refusal named the blocking pids and the interactive alternative.
- **Compact operation envelopes** on refresh/compile/tests kept the highest-frequency operations cheap and decision-shaped (`post_settle_compile`, `test_verdict`, `total/passed/failed`).
- **Lifecycle-reset transparency.** `bridge_identity_transition` plus the `request_reclassified` journal event made a play-mode-induced domain reload legible instead of looking like a lost request.
- **Targeted test filters** by assembly name gave fast, unambiguous verdicts, and the zero-match verdict was explicit rather than silently green.
- **PlayMode tests as the acceptance surface.** A runtime test asserting real view state caught a genuine API-semantics bug in the code under test (a keyed-registry release that only works when the release key matches the acquire key) that no compile or source review had surfaced.

## 5. What Worked Poorly

- **UI targeting scope.** `active_scene` targeting is useless in an additive multi-scene project whose active scene is a bootstrap scene, and `game_object_name` targeting did not resolve objects in other loaded scenes or in `DontDestroyOnLoad`. The operator-visible message (`No GameObject named 'X'`) is indistinguishable from a genuinely absent object.
- **Screenshot payload.** `includeImage: true` at `maxResolution: 420` produced a 184k-character response that exceeded the result budget, wasting the call. The useful part was a single field: `file_path`.
- **Aggregate batch verdicts.** Live-editor refusals land in the rollup as `projects_failed` with `operator_verdict_counts: {failed_before_unity: N}`. At a glance that reads as "the code does not compile in N projects"; every such case in this session was purely environmental.
- **Play-mode-blocked compile.** The error text is a generic "editor is busy" with three flags; there is no distinct code for "in play mode" and no guidance ("exit play mode, or run the closed-project batch lane").
- **Refresh during play mode reported `post_settle_compile: passed`** while asset import was in fact deferred — a trustworthy-looking green that cannot be trusted at that moment.
- **No session-scoped log query.** Neither the MCP grep nor a shell wait loop can express "only lines from the current play session".

## 6. What Was Not Explicit Enough

- that `unity_ui_*` resolution is scoped, and what the scope is
- that `source=editor_log` searches a fixed tail of a multi-session file, so a match may predate the current run (the existing caveat text warns about console clear/eviction false *negatives*, not stale-match false *positives*)
- that plain `UnityEngine.Debug.Log` from project code may never reach the captured log when the consumer installs a filtering log target, so marker-line absence proves nothing
- that a refresh issued during play mode yields a deferred, non-authoritative compile verdict
- that `recover-editor-session` alone does not open an editor

## 7. What The Operator Needed But Did Not Have

1. A way to read and click UI that is not in the active scene — the single blocker that made the requested interactive verification impossible.
2. A session-anchored log query (`since_playmode_start`, `since_bridge_generation`, or a returned `first_line_index`) so waits and greps cannot match stale lines.
3. A cheap "did my hook fire" signal that does not depend on the consumer's log-target configuration.
4. A verdict bucket that separates "blocked by live editor" from "failed".
5. Compact envelopes for `unity_status`, `unity_playmode_state`, and `unity_game_view_screenshot`.

## 8. Scoring

| Category | Score | Note |
| --- | --- | --- |
| Unity-side execution stability | 9/10 | no Unity-side failure across ~40 operations and four batch runs |
| Request journaling quality | 8/10 | reclassification event was decisive; still verbose in every response |
| Bridge health observability | 9/10 | dead-pid + stale-reason classification was exemplary |
| Wrapper-to-operator clarity | 6/10 | verdict buckets, "busy" vs play mode, and `ui_target_not_found` all mislead |
| Recovery guidance quality | 8/10 | per-project commands excellent; two-step editor recovery under-signposted |
| Transport lifecycle transparency | 8/10 | generation/session transitions legible |
| End-to-end trustworthiness during churn | 7/10 | one non-authoritative green (refresh during play) |
| Parallel request handling | 7/10 | parallelism 3 across projects held; contention only from live editors |
| Token efficiency of the default operator path | 4/10 | full-payload status/playmode/screenshot dominated; one 184k overflow |
| Time-to-diagnosis | 5/10 | UI-scope discovery took five calls; two false "hook did not fire" reads |
| Validation workflow discipline | 8/10 | compile-first, filtered tests, batch-then-interactive fallback |

## 9. Priority Improvements

**P0 — UI targeting scope (correctness of the interactive lane).**
- Add scene-scope options to `unity_ui_query` / `unity_ui_tree_snapshot` / `unity_ui_click`: `targetKind: all_loaded_scenes` (walk every loaded scene plus the `DontDestroyOnLoad` scene) and `sceneName` for explicit selection.
- Until that exists, return a distinct error code `ui_target_out_of_scope` with `searched_scenes: [...]` and `loaded_scenes: [...]` so "not found" is never confused with "not reachable".
- Report `dont_destroy_on_load_included: true|false` in the `target` block of every UI read.

**P0 — session-scoped log evidence.**
- Add `since` anchors to `unity_console_grep` / `unity_console_tail`: `since=playmode_start | bridge_generation | request_id`, and echo the resolved anchor plus `searched_from_line` in the response.
- Document the offset-anchored wait pattern for shell use (capture the line count first, then poll only the tail beyond it) as the supported way to wait for a fresh marker.

**P1 — verdict buckets in multi-project rollups.**
- Split `projects_failed` into `projects_failed` and `projects_blocked`; add `blocked_by_live_editor` to `operator_verdict_counts`; emit one aggregate hint listing the projects that should be re-run through the interactive lane.

**P1 — play-mode-aware errors and non-authoritative greens.**
- Replace the generic busy message with `editor_in_play_mode` for `compile_player_scripts`, `build_player`, and any closed-project lane, and include the two valid next actions.
- When a refresh completes while the editor is playing, mark the compile verdict `post_settle_compile_trust_class: deferred_during_playmode` instead of a bare `passed`.

**P1 — screenshot payload discipline.**
- Keep `includeImage: false` as the default (already true) and cap `includeImage: true` by an explicit byte budget: above it, drop the base64, return `file_path`, and set `image_omitted_reason: payload_budget`.
- Document "read the returned `file_path` with your image reader" as the intended operator path.

**P2 — compact envelopes for the remaining hot tools.**
- Extend `payload_mode: compact_operation` to `unity_status`, `unity_playmode_state`, `unity_playmode_set`, and `unity_game_view_screenshot`, with `includeFullPayload` opt-in, mirroring refresh/compile/test.

**P2 — hook-fire evidence that does not depend on consumer log configuration.**
- Document that plain `UnityEngine.Debug.Log` may be filtered by a consumer log target, and that marker absence is not proof.
- Prefer a bridge-side assertion path for "did this fire": a scene/UI state assert, or a project-defined hook that returns a receipt through the request journal.

## 10. Public-Promotion Recommendations

- `README.md` — screenshot payload guidance (`file_path`-first), and the session-scoped log-evidence rule with the offset-anchored wait snippet.
- `docs/architecture/DESIGN.md` — UI target resolution scope: active scene vs all loaded scenes vs `DontDestroyOnLoad`, and the `ui_target_out_of_scope` contract.
- `docs/operations/CONTINUATION.md` — the batch-vs-interactive routing rule for live editors, the two-step editor recovery (`recover-editor-session` then `ensure-ready --open-editor`), and the play-mode-blocked lane list.
- `docs/operations/SMOKE_TESTS.md` — add a play-mode-blocked compile case and a stale-marker log case to the acceptance checks.
- Wrapper/runtime — verdict buckets, `editor_in_play_mode`, `post_settle_compile_trust_class`, screenshot byte budget, compact envelopes for status/playmode/screenshot.
- `docs/architecture/ROADMAP.md` — the all-loaded-scenes UI targeting item, since it gates interactive verification in every additive multi-scene consumer.

## 11. Final Verdict

The execution layer is trustworthy: nothing Unity did in this session was wrong, and every refusal protected the project. The evidence layer is where the session lost time. Two gaps are worth fixing before the next interactive verification session: UI targeting cannot see additively loaded scenes or `DontDestroyOnLoad`, and log-based verification has no session boundary, so both "not found" and "no marker line" currently read as false negatives. Both are small, contained contract changes; neither requires new Unity-side capability beyond scene enumeration.
