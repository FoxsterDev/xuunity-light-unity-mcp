# XUUnity Light Unity MCP Retro — Greenfield Scene/Prefab Authoring And Editor-Truth Gaps

Date: `2026-09-03`
Status: `active public retro`
Server version under test: `v0.3.67`
Session shape: build a new Unity 6000.0 mobile game from an empty project — new assemblies, new
scenes, new prefabs, new UI hierarchy — validating exclusively through MCP.

## 1. Executive Summary

MCP held up well for the *verify* half of greenfield work (compile, refresh, tests, project actions,
screenshots, UI tree/click) and offered nothing for the *author* half (create a scene, build a UI
hierarchy, bind serialized references). The session worked around that by writing a project-local
editor scaffolder and driving it through `unity_project_action_invoke`, which is the pattern the
docs already recommend — but every greenfield project will rediscover it from scratch.

Three findings cost real time and would have been avoided by better surfaces:

1. **Play mode silently does not run when the editor is unfocused.** `unity_playmode_state` reports
   `playmode_throttled_editor_unfocused` correctly, but nothing in the *action* path warns: `playmode_set`
   returns `playing`, `ui_click` returns `refused: ui_node_not_found`, and the operator concludes the
   game is broken. Two full debugging cycles were spent on a game that was simply not ticking.
2. **`Screen.*` and the screenshot render target disagree in the editor.** `unity_game_view_screenshot`
   renders at the configured Game View resolution while `Screen.width/height` return the Game View
   *window* size unless a fixed custom size is created. Any layout logic that reads `Screen` is
   therefore validated against a different frame than the one captured. This produced a wrong
   diagnosis ("the board does not refit") that only a runtime log line disproved.
3. **Scenarios cannot drive UI.** `unity.ui.click` exists as a tool but not as a scenario step kind, so
   an ordered "boot → press Play → capture" flow cannot be captured as one scenario with persisted
   evidence. The session had to interleave standalone tool calls with scenario runs.

## 2. Evidence Base

- Request journal under `Library/XUUnityLightMcp/journal/requests/` — including a
  `request_reclassified` + `request_delivery_unproven` pair for an EditMode run
  (`c756e53d-5c32-4a2c-8b94-8356bec696d2`) whose real cause was an unrelated per-frame editor exception.
- `unity_playmode_state` payloads showing `playmode_frames_advanced_last_interval: 0`,
  `playmode_loop_liveness: throttled`, `editor_application_focused: false`.
- A project runtime log line proving the mismatch: `screen=1512x1078 render=1080x1920 ... cellPx=128.0`.
- `unity_scenario_validate` refusal `scenario must be an object` for a file path argument.
- `unity_project_action_list` / `unity_project_action_invoke` round trips for seven project actions.
- `unity_tests_run_editmode` compact verdicts (`36 total / 1 failed`, then `37 / 37 passed`).

## 3. Timeline (condensed)

1. `xuunity_setup_plan` via MCP returned `unity_projects_not_found` for an explicit `projectRoot`; the
   CLI `setup-plan --project-root` worked. Bridge then required `setup-apply` + editor reopen.
2. Compile/refresh/test loop worked cleanly and cheaply throughout.
3. First play-mode run: `AppBootstrap` never advanced. Diagnosed only after calling
   `unity_playmode_state` on a hunch; fixed by focusing the editor via `osascript`.
4. Board render bug: chased an apparent scale error for two cycles before adding a runtime log line
   that exposed the `Screen` versus render-target divergence.
5. `unity_tests_run_editmode` hit `timeout_before_test_start` after ~15 minutes. Root cause was a
   per-editor-frame exception from an unrelated shared editor tool flooding the console; the MCP
   verdict was accurate but gave no pointer to the console-flood cause.
6. After the flood was fixed, the same test request completed in 12 seconds.

## 4. What Worked Well

- **Compact operation envelopes.** `post_settle_compile`, `post_settle_error_count` and the first three
  `post_settle_diagnostics` were almost always enough to fix a compile error without opening a log.
- **`unity_project_action_invoke` as the authoring lane.** A project-local `IXUUnityLightMcpScenarioHook`
  turned "create two scenes with a full UI hierarchy and 60 wired serialized references" into one
  idempotent, re-runnable, reviewable call. `allowMutating` gating read as proportionate, not noisy.
- **`unity_ui_tree_snapshot` / `unity_ui_click`.** Semantic UI proof (`delivered`, `effective`,
  `state_changed`, before/after signatures) was decisively better than screenshot-only inspection for
  answering "did the button actually do something".
- **Test verdicts.** `first_failures` carried the assertion message inline, which was enough to fix a
  wrong test without opening the result JSON.
- **Refusal quality.** `game_view_configure` refusing an unavailable size with an explicit
  `allowCreateCustomSize=true` remedy is a model refusal: it names the exact next call.

## 5. What Worked Poorly

- **Throttled play mode is invisible at the point of use.** Every play-mode-dependent operation should
  surface liveness, not just the dedicated state call.
- **Editor `Screen` versus render target.** No tool reports the effective render size, so a project cannot
  tell whether its own layout math ran against the captured frame.
- **`unity_scenario_validate` takes an inline object while the CLI takes `--scenario-file`.** The
  asymmetry is undocumented in the tool description and cost a round trip.
- **Scenario step kinds are undiscoverable.** The valid `kind` values and the field names
  (`stepId`, `durationSeconds`, `fileName`) were recovered by grepping the package source.
- **`xuunity_setup_plan` MCP tool ignored an explicit `projectRoot`** where the CLI honoured it.
- **`unity_project_refresh` verdict during play mode** is correctly flagged `deferred_during_playmode`,
  but the operator still has to remember to exit play mode first; the tool could refuse instead.

## 6. What Was Not Explicit Enough

- Nothing said "your editor is unfocused, so nothing you do in play mode will take effect".
- Nothing said "this screenshot was rendered at a different size than `Screen` reports".
- Nothing linked a test-run timeout to console-flood pressure, even though the console is already read.
- The mutating-action `mutation_delta` contract is warned about on every invoke but the hook-side
  helper to emit it is not offered anywhere in the package, so every project ships `unverified_mutation`.

## 7. What The Operator Needed But Did Not Have

| Need | Today | Proposed |
| --- | --- | --- |
| Guarantee play mode actually ticks | manual `osascript` focus | `unity_editor_focus` action, or `ensureLive: true` on `playmode_set` |
| Know the captured frame's true size | infer | `render_width` / `render_height` in `game_view_screenshot` and `ui_*` payloads |
| Ordered UI flows as one scenario | interleave tool calls | `ui_click` / `ui_assert` scenario step kinds |
| Discover scenario schema | grep package source | `unity_scenario_capabilities`, or step kinds in the tool description |
| Scaffold a project hook | hand-write the interface | `project-hook-scaffold` exists in the CLI but is not surfaced as an MCP tool |
| Explain a test-run stall | raw log dig | `console_error_rate_since_anchor` in the test-run envelope |

## 8. Scoring

| Category | Score | Note |
| --- | --- | --- |
| Unity-side execution stability | 9 / 10 | no MCP-caused Unity failure across ~120 operations |
| Request journaling quality | 9 / 10 | the reclassified/unproven pair was accurate and self-explaining |
| Bridge health observability | 8 / 10 | `bridge_disabled` and stale-state diagnosis were precise |
| Wrapper-to-operator clarity | 7 / 10 | strong on compile/tests, weak on play-mode liveness |
| Recovery guidance quality | 8 / 10 | most refusals name the exact next command |
| Transport lifecycle transparency | 9 / 10 | generation/session deltas were traceable |
| End-to-end trustworthiness during churn | 8 / 10 | no false green observed |
| Parallel request handling | n/a | single-operator session |
| Token efficiency of the default path | 6 / 10 | full payloads are very large; compact mode is good but `ui_click` and `status_summary` still dominate |
| Time-to-diagnosis | 5 / 10 | two multi-cycle detours, both from missing editor-truth signals |
| Validation workflow discipline | 8 / 10 | compile → refresh → tests → play ordering held |

## 9. Priority Improvements

**P0 — play-mode liveness at the point of use.** Add `playmode_liveness` to every operation that
depends on the player loop (`ui_click`, `ui_query`, `game_view_screenshot`, `scenario` steps). When
liveness is `throttled`, downgrade the result trust class and name the remedy. Optionally add an
`unity_editor_focus` operation so an agent can fix it without shelling out to the OS.

**P0 — report the effective render target.** Add `render_width`/`render_height` (and, when they differ,
a `screen_width`/`screen_height` pair plus a `render_target_differs_from_screen: true` flag) to
`game_view_screenshot` and the UI read payloads. Without it, editor-lane layout validation can be
confidently wrong.

**P1 — UI steps in scenarios.** Add `ui_click`, `ui_exists`, `ui_get_text` step kinds so a boot →
interact → capture flow becomes one scenario with persisted, ordered evidence.

**P1 — scenario schema discoverability.** Either add `unity_scenario_capabilities` returning the valid
step kinds and their fields, or enumerate them in the `unity_scenario_run` tool description. Also
accept a file path in `unity_scenario_validate` for parity with the CLI.

**P1 — console pressure in the test envelope.** Include `console_error_count_since_request_start` in
test and playmode verdicts. A test run that stalls behind a per-frame editor exception should say so.

**P2 — `mutation_delta` helper.** Ship a `XUUnityLightMcpMutationDelta` builder in the package so
project hooks can emit the contract instead of every project reporting `unverified_mutation`.

**P2 — `xuunity_setup_plan` projectRoot parity** with the CLI.

**P2 — `project-hook-scaffold` as an MCP tool**, so greenfield projects get the authoring lane in one
call instead of hand-writing `IXUUnityLightMcpScenarioHook`.

## 10. Public-Promotion Recommendations

- `README.md` / `AI_INTEGRATION.md`: add a **greenfield authoring** section stating the intended
  division of labour — MCP verifies, a project-local hook authors — with the minimal hook skeleton and
  the `project_actions.yaml` shape. This session had to reconstruct it from another project's source.
- `SMOKE_TESTS.md`: add a play-mode precondition step — assert `playmode_loop_liveness == advancing`
  before any UI interaction or screenshot assertion.
- `DESIGN.md`: document the editor `Screen` versus render-target divergence as a first-class evidence
  boundary, alongside the existing editor-resident-evidence boundary.
- `CONTINUATION.md`: record the P0/P1 items above.
- Tool descriptions: enumerate scenario step kinds; note the `scenario_validate` object-only input.

## 11. Final Verdict

**MCP was sufficient to build and validate a new game end to end without ever leaving the integrated
lane, and it never produced a false green.** Its weakness in this session was not correctness but
*editor-truth observability*: two of the three real defects found were defects in what the editor was
actually doing (not ticking; rendering at a different size than it reported), and in both cases MCP
had the information somewhere but not at the point where the operator was making the decision.

Fixing P0-liveness and P0-render-size would have removed an estimated 30–40% of this session's
diagnosis time.
