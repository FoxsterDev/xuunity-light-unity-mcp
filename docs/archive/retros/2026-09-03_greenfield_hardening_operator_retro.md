# Greenfield hardening session — MCP operator retro

Date: `2026-09-03`
Server version under test: `v0.3.67` (project pin `com.xuunity.light-mcp#v0.3.67`).
Implementation status: both P1 currency findings are released in
`v0.3.69` through one shared `project_action_currency`
preflight. P2 items remain open. Native autofocus was deliberately declined;
the bridge enables runtime background execution and keeps measured player-loop
liveness authoritative.
Some findings below may already be addressed in `v0.3.68`; each is written against what `0.3.67` actually
emitted in this session, so re-check before implementing.

Session shape: a full day of defect hunting, device bring-up, performance work and feature completion on a
newly built game project. Roughly 2300 journal entries, 82 bridge generations, ~25 mutating project-action
invocations, 6 play-mode entries, 5 player builds, 12 test runs.

## 1. Executive summary

The bridge was **operationally solid**: no lifecycle resets that lost a request, no false-negative verdicts,
no transport churn. Every failure this session was either a real defect in my code or a **staleness problem
the surface did not warn about**. The two highest-cost MCP-side issues were both about *what is live right
now*: a player-script compile does not rebuild the editor domain, and a project action can read a stale
AssetDatabase. Both cost wasted cycles and, worse, produced confident wrong conclusions. The third cost was
sheer payload volume on build and resolve operations.

## 2. Evidence base

- request journal: `Library/XUUnityLightMcp/journal/requests/*.json`, 2339 entries
- bridge state across generations 26 → 82, `health_status: healthy` throughout
- verdicts quoted below come from the tool results, not from recollection

## 3. Timeline of the MCP-relevant incidents

1. Edited `LevelGenerator` (runtime assembly, consumed by an editor action). Ran
   `unity_compile_player_scripts target=Android` → `post_settle_compile: passed`. Invoked
   `arrowpuzzle.generate_levels` → output byte-identical to before the edit. Repeated once more before
   diagnosing. `unity_project_refresh` then produced the expected output.
2. Rewrote a level JSON on disk, invoked `arrowpuzzle.validate_levels` → `levels_invalid ... level 5: no full
   clear found`. My own simulator proved the level clears. `unity_project_refresh` then produced
   `checked=10 failed=0` on the same file.
3. Every mutating `unity_project_action_invoke` returned `operator_verdict: passed_unverified_mutation_delta`
   with a four-line warning and a `recommended_next_action`. Correct once; repeated ~25 times.
4. `unity_build_player` and `unity_edm4u_resolve` returned full `_xuunity_lifecycle` envelopes with complete
   before/after bridge state. A successful build result was ~8 KB of which ~200 bytes were the answer.
5. Play mode needed the editor focused six times; each needed an out-of-band `osascript` call. The status
   surface *did* name the problem (`playmode_loop_liveness: throttled`, with remediation text) — the gap is
   that the operator has to leave the tool surface to fix it.
6. `unity_game_view_screenshot` returns a path, never the image, so every visual check was two calls. I made
   roughly fifteen.

## 4. What worked well

- **Anchored console search.** `unity_console_grep` with `since=playmode_start` was the single most valuable
  operation of the session. It proved the board-fit diagnostic (`board=7x9 cellPx=128.0`) and, earlier,
  proved a resolved exception flood was actually gone. Unanchored search would have been useless against a
  1.6 GB editor log.
- **PlayMode verdicts.** Fast (5-16 s), reliable, and they caught a real defect I had not looked for: a tween
  completion callback outliving a scene unload.
- **Project actions as the automation spine.** Edit → refresh → `scaffold_scenes` made roughly a dozen full
  UI rebuilds cost one invocation each. Without it the visual pass would not have been affordable.
- **Build reliability.** Once a real signing failure was fixed, five builds in a row succeeded, and
  incremental builds ran in 16-52 s.
- **Failure text quality.** The signing failure surfaced as `UnityException: Can not sign the application` in
  the log with the exact `PlayerSettings` fields at fault; the editor-assembly MonoBehaviour rejection said
  precisely `Can't add script behaviour ... because it is an editor script`. Both were one grep from a fix.

## 5. What worked poorly

**P1 — "compiled" does not mean "live for the next action".**
`unity_compile_player_scripts` compiles the player. An editor-invoked project action runs against the editor
domain. When those diverge the operator sees a green compile and a stale result, with nothing in either
payload connecting the two. This is a false-negative generator: it makes a working code change look inert.

**P1 — project actions can read a stale AssetDatabase.**
An action that reads assets edited outside Unity reports a confident wrong verdict. `validate_levels`
returned `levels_invalid` for a file that was, on disk, valid.

**P2 — repeated advisory noise.**
The mutation-delta advisory is right, but emitting it on every invocation of the same hook turns a one-time
contract gap into a per-call tax.

**P2 — no compact mode on the heaviest operations.**
Most operations carry `payload_mode: compact_operation`. `unity_build_player` and `unity_edm4u_resolve` do
not, and they are the two that emit the largest envelopes.

**P3 — focus remediation is named but not actionable in-surface.**

**P3 — screenshots always cost two round trips.**

## 6. What the operator needed but did not have

1. A single field answering "is the editor domain current with my last script edit?"
2. A staleness signal on asset-reading actions: the AssetDatabase's last import time, or an opt-in refresh.
3. A compact result envelope for builds.
4. A way to focus the editor from the tool surface.

## 7. Scoring

| Category | Score | Note |
| --- | --- | --- |
| Unity-side execution stability | 9/10 | no lost or misattributed requests across 82 generations |
| Request journaling quality | 9/10 | complete and correctly ordered |
| Bridge health observability | 8/10 | healthy throughout; staleness is the blind spot |
| Wrapper-to-operator clarity | 6/10 | green compile plus stale action result is the worst case |
| Recovery guidance quality | 7/10 | good for focus and signing, absent for staleness |
| Transport lifecycle transparency | 9/10 | no churn |
| End-to-end trustworthiness during churn | 7/10 | high, except where staleness produced confident wrong verdicts |
| Parallel request handling | n/a | serialized by design this session |
| Token efficiency of the default path | 5/10 | build and resolve envelopes dominate; repeated advisories add up |
| Time-to-diagnosis | 6/10 | two staleness incidents cost four wasted cycles |
| Validation workflow discipline | 8/10 | compile-first ordering held; tests were run at every gate |

## 8. Priority improvements

**P1. Surface editor-domain currency.**
Add to `unity_project_action_invoke` (and to `unity_status_summary`) a field pairing the editor assemblies'
build stamp with the newest script mtime under `Assets/`, e.g.
`editor_domain_current: true|false|unknown`. When false, add
`recommended_next_action: run_unity_project_refresh_before_invoking`. This alone removes the session's most
expensive failure class.

**P1. Make asset staleness visible on asset-reading actions.**
Either report `assetdatabase_last_import_utc` next to the action verdict, or let a catalog action declare
`requiresFreshAssets: true` so the server refreshes before invoking. Prefer the declaration: it makes the
contract explicit per action instead of asking every operator to remember.

**P2. Compact envelope for `unity_build_player` and `unity_edm4u_resolve`.**
Default to the same `payload_mode: compact_operation` the other operations use: outcome, result, duration,
output path, error and warning counts, `top_actionable_error`, artifact manifest. Full lifecycle behind
`includeFullPayload: true`.

**P2. Emit the mutation-delta advisory once per hook per session.**
Keep a one-line `mutation_trust_class` on every call; move the four-line explanation and the recommended
action to the first occurrence.

**P3. Add an editor-focus operation** (or focus implicitly on `unity_playmode_set action=enter`, which
already knows the editor pid).

**P3. Optional inline image on `unity_game_view_screenshot`,** downscaled to a byte budget, so a visual check
is one call.

## 9. Public-promotion recommendations

- `SMOKE_TESTS.md`: add a staleness branch — after editing code that an editor action executes, or assets
  edited outside Unity, run `unity_project_refresh` before invoking the action. Include the two symptoms:
  byte-identical output from a changed generator, and a failing verdict on an asset that is valid on disk.
- `CONTINUATION.md`: record that a player-script compile is not proof that the editor domain is current.
- `README.md`: note which operations are compact by default and which are not, so operators can predict cost.

## 10. Final verdict

**Pass.** The bridge did its job for a long, heavy session without a single trust incident. The improvements
worth making are not about reliability but about *currency* — telling the operator when what they are
looking at is no longer what is on disk. Two small fields would have removed four wasted cycles and one
confidently wrong conclusion from this session alone.

## 11. Re-evaluation for v0.3.69

- Every typed invocation and raw scenario `project_action` now expands through
  a persisted currency step before its project hook. The preflight compares
  `editor_domain_loaded_utc` with the newest `.cs`, `.asmdef`, `.asmref`, or
  `.rsp` mtime under `Assets`; stale and unknown classifications fail closed
  before the hook.
- Catalog `requiresFreshAssets: true` prepends a forced AssetDatabase refresh
  with package resolution and redundant health probing disabled. The scenario
  waits for the existing refresh/domain-settle contract, then requires both a
  current editor domain and a recorded successful refresh before invoking.
- `unity_project_action_currency`, `unity_project_action_invoke`, and
  `unity_status_summary` expose the compact currency evidence and recovery.
- Runtime `Application.runInBackground=true` is re-applied on bootstrap,
  heartbeat, and play-mode state changes. No `PlayerSettings` or OS focus is
  mutated; payloads explicitly report `native_autofocus_enabled=false`, and
  liveness remains the point-of-use trust signal.
