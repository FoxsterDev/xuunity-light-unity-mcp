# Chat Retro: Play-Mode Liveness Blindness and the Compile-Gate Deadlock

Date: `2026-08-17`
Status: `active public retro`
Source: one long feature session in a Unity consumer project (Unity `6000.3.21f1`,
MCP server `xuunity-mcp 0.3.57`, bridge version 9), driving gameplay-rule changes
through refresh, compile, project actions, prefab render and play mode.

## 1. Executive summary

No Unity-side operation failed in this session. Every operation the wrapper
dispatched was executed by the editor, and every failure the operator chased was
either a real source defect or an **operator-visibility defect in the MCP surface**.

Two findings are new and reusable, and both cost far more than any Unity failure:

1. **Play-mode liveness is unobservable.** The editor throttles its update loop
   when it is not the frontmost application. During that time `playmode_state` is
   `playing`, `is_playing` is `true`, `health_status` is `healthy`, and the
   heartbeat stays 1-2s fresh — while the game loop advances almost no frames. The
   operator sees a "stuck boot" and starts debugging application code that is
   perfectly fine. This happened twice and consumed roughly 25 minutes and ~15
   round trips, including one wrong hypothesis that reached a source edit
   (`Application.runInBackground`) before being disproven.

2. **The compile gate blocks its own remediation on the direct tool, but not on the
   scenario path.** `unity.playmode.set` with `action: exit` is refused with
   `compile_broken`. But when the editor is in play mode, Unity defers the script
   reload, so *exiting play mode is exactly what clears the compile state*, and the
   documented `recommended_next_action` ("run_compile_gate_and_fix_errors") is
   unreachable from that state. The operator concluded the session was stuck and
   asked for manual editor interaction.
   **That conclusion was wrong, and the reason is the finding:** the same transition
   expressed as a scenario step (`unity.scenario.run` with a `playmode_set`
   `action: exit` step) is dispatched inside Unity and is **not** gated — it exited
   play mode in 4 seconds on the first attempt. So the defect is not "no escape
   exists", it is **behavioural divergence between the direct tool and the scenario
   step for the same operation**, with the gated path being the one an operator
   reaches for first and the ungated path being undocumented as the workaround.

Both are lifecycle-observability problems, not transport problems. The transport,
journaling and recovery guidance were consistently good.

## 2. Evidence base

- request journal: 996 entries under `Library/XUUnityLightMcp/journal/requests/`
- scenario results: 11 runs under `Library/XUUnityLightMcp/scenarios/results/`
- captures: 16 under `Library/XUUnityLightMcp/captures/` (game-view + prefab renders)
- `Library/XUUnityLightMcp/state/bridge_state.json`: `bridge_version=9`,
  `bridge_generation` advanced 62 -> 98 across the session,
  `editor_log_path=~/Library/Logs/Unity/Editor.log`
- compile verdicts from `unity.project.refresh` `post_settle_compile` with
  `post_settle_compile_trust_class`
- refusal payloads from `unity.playmode.set` and `unity.ui.click`
- log-lane diagnostics from `unity.console.grep` (`lane`, `lane_reason`,
  `since_anchor`)

## 3. Timeline (condensed)

| Phase | What happened | Cost |
| --- | --- | --- |
| Editor launch | Editor started directly (not through the host wrapper), so the host default log path went stale | set up finding F4 |
| First compile check | `unity_status_summary` reported `script_compilation_failed: true` with `compiler_error_count: 0` and an empty diagnostic list (`compiler_diagnostics_source: script_compilation_failed_flag`) | 1 wasted grep round trip |
| Log grep | `unity_console_grep` searched the stale host log, returned `match_count: 0` on a genuinely broken compile, and correctly flagged `lane: stale_not_written_by_live_editor` with a fix | 1 round trip, self-corrected |
| Authoritative compile | `unity_project_refresh` returned `post_settle_compile: failed`, `trust_class: confirmed`, with the real diagnostic | resolved |
| Iterate 4 compile cycles | refresh -> fix -> refresh; verdicts always trustworthy | smooth |
| Project actions | typed hook actions ran cleanly; one failed because the invoker overrides `action` with the catalog action id (F6) | 1 failed run + 1 recompile |
| Play mode #1 | Boot appeared frozen on splash for 90s+; all health fields green; wrong hypothesis (`runInBackground`) edited into source | ~20 min |
| Diagnosis | Root cause identified as editor throttling while unfocused; confirmed by identical UI snapshot signatures 30s apart | resolved |
| Play mode #2 | Same freeze recurred as soon as focus moved to run a shell command | ~5 min |
| Exit attempt | `playmode_set exit` refused by the compile gate, with diagnostics already fixed on disk (F2, F3) | blocked |
| Escape attempt | OS keystroke automation denied; operator wrongly concluded manual interaction was required | wrong conclusion |
| Escape | Same exit expressed as a scenario `playmode_set` step succeeded in 4s, ungated | resolved in band |
| Rule proof | A project hook driving the game's own API synchronously (no frames, no focus) asserted the changed rules and **caught a real same-frame duplicate-object defect** that screenshots and clicks had missed | best evidence of the session |
| Prefab render | `unity_prefab_render` closed the visual acceptance lane twice in 0.1-0.5s, catching two real layout defects without play mode | best ROI of the session |

## 4. What worked well

- **`post_settle_compile` + `post_settle_compile_trust_class` is the right compile
  contract.** `confirmed` vs `deferred_during_playmode` was explicit every time and
  never misled the operator. The `deferred_during_playmode` note even named the
  remediation.
- **Log-lane diagnostics are excellent.** `lane`, `lane_reason`, and
  `recommended_next_action` turned a false-negative grep into a self-correcting
  one-step fix.
- **Log rotation forward-resolution.** When a second editor instance was attempted,
  Unity renamed `Editor.log` to `Editor-prev.log`; the tool detected that the
  stamped path held an older file than its rotated sibling (`lane: rotated_sibling`)
  and followed the sibling with an explicit reason. This is subtle behaviour handled
  correctly.
- **`unity_prefab_render` is the standout tool.** It closed both visual and semantic
  acceptance without booting the app, in sub-second time, and caught two layout
  defects (text overlap, text overflow) that would otherwise have needed a full
  play-mode drive.
- **`unity_ui_click` refusals are honest and diagnostic.** `ui_target_not_visible`
  with `effective_alpha`, `active_in_hierarchy` and bounds made it obvious the
  target was mid-animation rather than missing.
- **Typed project actions with declared evidence fields** produced compact,
  decision-ready scalars (`levels_checked`, `failures`, `deterministic`) that
  replaced what would otherwise have been log scraping.

## 5. What worked poorly

- **F1. No play-mode liveness signal.** Nothing in `unity_playmode_state`,
  `unity_status_summary` or the click/query payloads distinguishes "play mode is
  running" from "play mode is running but the update loop is throttled to near
  zero". The heartbeat is an *editor* heartbeat and stays fresh, so it actively
  reinforces the wrong conclusion.
- **F2. Compile gate deadlock on `playmode_set exit`.** Refusing the exit
  transition because compilation is broken removes the only in-band way to let
  Unity recompile.
- **F3. Stale diagnostics presented without provenance.** Both a `playmode_set`
  refusal and an early `status_summary` carried diagnostics that no longer matched
  disk (verified by grep). One had `compiler_diagnostics_source:
  script_compilation_failed_flag` (a flag, not a verdict) and one carried a
  `compilation_pipeline` list captured before the latest recompile.
- **F6. `project_action_invoke` overrides the payload `action`** with the catalog
  action id, silently contradicting the catalog's own `payload.action` declaration.
  The tool description documents the behaviour, but the catalog schema invites the
  opposite expectation.
- **F7. Repeated non-actionable mutation warning.** Eight mutating invocations each
  returned `mutation_trust_class: unverified_mutation` and
  `recommended_next_action: inspect_git_diff_and_update_hook_to_emit_mutation_delta`
  with no pointer to the `xuunity.mutation-delta.v1` shape a hook author must emit.
- **F10. `project_action_invoke` has no compact envelope.** Every invocation
  returned ~8-10 KB (state groups, host prerequisites, transport, artifact
  manifest) to deliver two scalars. Eight invocations is ~70 KB of largely constant
  payload, in a toolset where compact-by-default already shipped elsewhere.

## 6. What was not explicit enough

- That an **editor heartbeat is not a game-loop heartbeat**. Nothing warns that
  play-mode evidence collected while the editor is backgrounded may be meaningless.
- That **`script_compilation_failed` in `status_summary` is a flag, not a verdict**,
  and that the authoritative answer only comes from a refresh settle. The
  `compiler_diagnostics_source` field encodes this, but the operator has to already
  know what it means.
- That **launching the editor outside the host wrapper permanently splits the log
  lane** for the session. The per-call diagnostics are good, but there is no
  up-front warning at the first tool call after such a launch.
- That `event_system_present: false` is **scoped to the searched roots**, not a
  project-wide statement. It read as "this project has no EventSystem" and
  triggered an unnecessary scene-file investigation.

## 7. What the operator needed but did not have

1. A **frame-advance signal** for play mode (e.g. `Time.frameCount` delta between
   two reads, plus `Application.isFocused` / editor interaction-mode state), so
   "frozen because throttled" is one call away instead of a 20-minute hypothesis
   hunt.
2. A **way out of play mode that cannot be gated** by compile state.
3. A **provenance stamp on every diagnostic list** saying which compile pass it came
   from, so a refusal cannot quote already-fixed errors as current.
4. A **compact mode for `project_action_invoke`**, consistent with the rest of the
   surface.
5. A **schema pointer** in the mutation-delta warning.

## 8. Scoring

| Category | Score | Note |
| --- | --- | --- |
| Unity-side execution stability | 9 | no dispatched operation failed editor-side |
| Request journaling quality | 8 | 996 entries, ids resolvable, lifecycle legible |
| Bridge health observability | 5 | healthy and fresh while the game loop was frozen |
| Wrapper-to-operator clarity | 6 | superb log-lane messages, but stale diagnostics quoted as current |
| Recovery guidance quality | 6 | usually excellent; the one case that mattered most pointed at an unreachable action |
| Transport lifecycle transparency | 9 | generation/session churn always explicit |
| End-to-end trustworthiness during churn | 7 | compile verdicts trustworthy; play-mode evidence was not |
| Parallel request handling | 8 | no contention observed |
| Token efficiency of default operator path | 4 | full envelopes on every project action; large repeated constant payloads |
| Time-to-diagnosis | 4 | the dominant issue took ~25 min and a wrong source edit |
| Validation workflow discipline | 8 | compile-first, then hooks, then prefab render, play mode last |

## 9. Priority improvements

**P0-1 — Play-mode liveness field.** Add frame-advance evidence to
`unity_playmode_state` and `unity_status_summary`: a monotonic frame/`Time.time`
sample, plus editor focus / interaction-mode state. When `is_playing` is true and
frames are not advancing between two samples, emit an explicit warning such as
`playmode_throttled_editor_unfocused` with the remediation (focus the editor, or
change the editor interaction mode). This single field would have removed the
largest cost in the session.

**P0-2 — Never gate `playmode_set exit` on compile state, and make the direct tool
agree with the scenario step.** Exit is remediation, not mutation. Allow it
unconditionally on the direct tool (or add an explicit `force`). The scenario step
already allows it, so today the same operation succeeds or fails purely by which
surface the operator picks — which is worse than a consistent refusal, because it
teaches the operator that no escape exists. Until the gate is changed, the
refusal message should name the scenario-step workaround in
`recommended_next_action`.

**P0-3 — Gate divergence audit.** `playmode_set exit` is unlikely to be the only
operation where the host-side gate and the scenario dispatcher disagree. Enumerate
every gated direct tool and assert, in the smoke contract, that its scenario-step
equivalent applies the same gate — or that the difference is deliberate and
documented.

**P1-1 — Stamp diagnostic provenance.** Every payload carrying
`recent_compiler_diagnostics` should say which compile pass produced it and whether
it is authoritative, reusing the existing `trust_class` vocabulary. A refusal must
not quote diagnostics that a later recompile has already cleared without labelling
them.

**P1-2 — Compact envelope for `project_action_invoke`.** Default to the action id,
outcome, and the catalog-declared `evidence` scalars; keep the full envelope behind
`includeFullPayload`.

**P1-3 — Resolve the `action` payload contradiction.** Either inject the catalog's
declared `payload.action`, or fail catalog load when the declared payload disagrees
with what will be injected. At minimum, state in the schema docs that hooks must
accept the fully-qualified action id.

**P1-4 — Make the mutation-delta warning actionable.** Include the schema name and
doc path in the message.

**P2-1 — Clarify `event_system_present` scope** in the payload or its docs.

**P2-2 — Warn once on a split log lane.** On the first tool call of a session where
the editor was not opened by the host, surface a one-line notice that
`editorLogPath` must be passed, rather than waiting for each call to discover it.

## 10. Public-promotion recommendations

- `docs/operations/CONTINUATION.md`: add a short "play-mode evidence is only valid
  while the editor is frontmost" rule with the frame-advance check as the
  precondition for trusting any play-mode observation.
- `docs/operations/SMOKE_TESTS.md`: order play-mode smoke steps after an explicit
  liveness assertion; treat a play-mode observation without frame advance as no
  evidence.
- `README.md` / agent docs: state that `ensure-ready --open-editor` is the default
  launch path, and that a self-launched editor requires explicit `editorLogPath` for
  every log query.
- `docs/architecture/DESIGN.md`: record that the compile gate must not cover
  play-mode exit.
- `docs/architecture/ROADMAP.md`: add P0-1 and P0-2; fold P1-2 into the existing
  compact-envelope tail.
- Prefer `unity_prefab_render` over play-mode screenshots for prefab-only UI
  acceptance; worth calling out explicitly in the agent-facing docs as the cheap
  default.
- **Promote the synchronous rule-assertion hook as a first-class validation
  pattern.** When gameplay rules change, a project hook that drives the game's own
  API and asserts state synchronously is strictly better than click-and-screenshot
  driving: it needs no frames, is immune to editor throttling and focus theft, runs
  in ~0.2s, and returns decision-ready scalars through the catalog `evidence`
  contract. In this session it also found a defect the visual lane had missed (a
  same-frame duplicate object caused by Unity's deferred `Destroy`). Worth a short
  section in `docs/operations/SMOKE_TESTS.md` next to the scenario guidance, and
  worth noting that such a hook belongs in the project's own action catalog rather
  than in the public core.

## 11. Final verdict

The MCP layer was reliable and honest about transport, compile and mutation, and it
never lost or misreported a Unity operation. Its weakness in this session was
narrow and specific: **it reports that play mode is running without reporting
whether play mode is progressing, and it can refuse the one transition that would
unblock a compile-broken play session.** Fixing P0-1 and P0-2 would have removed
roughly 30 minutes of diagnosis, one incorrect source edit, and one hard stop
requiring manual editor interaction.
