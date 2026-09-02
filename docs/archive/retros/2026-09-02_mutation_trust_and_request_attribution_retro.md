# XUUnity Light Unity MCP Chat Retro — Mutation Trust Class and Request Attribution

Date: `2026-09-02`
Status: `intake; two new P1 findings, one second-sighting escalation, three P2 candidates`
Lane: interactive chat, feature implementation plus dev-backend interactive smoke in a consumer project

## 1. Executive Summary

A session implemented a small server-response-driven fallback on a money path, validated it through the MCP lane
(refresh, compile, EditMode tests, executed regression reds), then switched the project to its dev build profile and
ran an interactive Play Mode smoke. Unity did everything asked of it. The MCP surface got two things wrong about
*what had happened*, and one of them concerned the only mutation in the session that mattered.

Attribution first, because it changes who owns each fix:

| Finding | Attribution | One-line basis |
| --- | --- | --- |
| P1-1 a build-profile mutation that succeeded was reported as `mutation_not_completed` | **product limitation** | The hook returned `status: passed, outcome: environment_applied`; a domain reload then reset the response channel, the journal recorded `request_delivery_unproven`, and the envelope surfaced `mutation_trust_class: not_evaluated` instead of the existing `unity_completed_host_delivery_unproven` trust class. Ground truth required reading the asset on disk. |
| P1-2 concurrent third-party driving of the same editor was invisible | **product gap** | 17 requests reached the bridge after this session's last call. No journal event carries an initiator, client, or session identity; `grep -rIl initiator` over `README.md`, `docs`, and `templates` returns nothing. |
| P1-3 anchored console scope truncated with no operator-controlled window | **product limitation, second sighting** | `since=playmode_start`, `scoped_bytes_available: 2157541`, `searched_window_chars: 500000`, `unsearched_scope_chars: 1657507`, `match_count: 0`, `search_verdict: inconclusive`. Ranking was correct and honest. The answer still had to be fetched off-surface with `tail -c +<offset> | grep`. |
| P2-1 `unity_scenario_validate` passed a step whose payload it knew would be dropped | **product limitation** | A `project_defined_hook` step carrying `payload` validated as `valid` with zero errors and zero warnings, then failed at runtime with an empty action string. Plain hook steps read `payloadJson`/`hookPayloadJson`. |
| P2-2 poll-until treated a hook's `running` status as terminal failure | **operator error** | `continueWhen` is documented in `docs/operations/SMOKE_TESTS.md` and in the 2026-06-12 poll-until design. The scenario was authored without reading either. Cost: one full scenario run, `poll_count: 1`. |
| P2-3 ten minutes spent on `ensure-ready` against a dead editor pid | **operator error** | The session's *first* `unity_status_summary` already returned `recommended_next_action: recover_editor_session` plus the exact command, and `stale_reason: editor_pid_not_alive`. `ensure-ready` was issued anyway, without `--open-editor`. |

P2-3 is the same operator-error shape as P0-2 in the 2026-08-19 retro: **the remediation was already in the first
status call of the session and was not acted on.** Two sightings of one operator failure mode is a signal about the
compact envelope's field prominence, not just about two operators.

The single most valuable reusable fix is P1-1. The trust-class vocabulary that this exact problem produced in the
2026-05-11 lifecycle-reset retro is already implemented and shipped in `server_bridge_final_status.py` — it simply
does not reach the project-action mutation envelope, which invented a weaker, separate verdict instead.

## 2. Evidence Base

Session-local, all checkable:

- `Library/XUUnityLightMcp/journal/requests/*.json` — 46 `request_submitted`, 45 `request_completed`,
  134 `operation_progress`, 15 `bridge_bootstrap_attached`, 7 `request_reclassified`, 1 `request_delivery_unproven`
  for the session date.
- The unproven-delivery event, verbatim: `operation: unity.scenario.result`, `bridge_generation: 1626`,
  `host_delivery_observed: false`, `host_delivery_source: lifecycle_reset_before_response_delivery`,
  `reason: response_channel_reset_before_host_delivery`, `event_at_utc: 11:19:45Z`.
- All seven `request_reclassified` reasons: six `bridge_generation_changed_during_post_request_settle`
  (`unity.project.refresh` x4, `unity.playmode.set` x2), one `bridge_generation_changed_before_response`
  (`unity.scenario.result`, 11:19:45Z).
- `state/bridge_state.json` — `bridge_version: 9`, generation `1622` at session start to `1637` at close,
  `health_status: healthy`, `bridge_process_class: main_editor`, `transport: tcp_loopback`.
- Scenario result files for the profile-switch action and both smoke attempts.
- Public docs and contract files, grepped for each finding before writing it, to avoid reporting a documented
  behavior as a discovery.

Documentation coverage check (what already exists, so promotion targets are real):

| Term | Present in | Reading |
| --- | --- | --- |
| `continueWhen` | `SMOKE_TESTS.md`, poll-until design, two retros, `server_specs_scenario.py` | documented; discoverability gap only |
| `editor_busy` | `SMOKE_TESTS.md`, readiness retro, two templates | documented |
| `recover-editor-session` | `README.md`, `CONTINUATION.md`, `AGENT_WORKFLOWS.md`, `FEATURES.md`, 8 retros | heavily documented |
| `search_verdict` | `README.md`, `SMOKE_TESTS.md`, `STATUS.md`, 2026-08-19 retro | documented; open P2 is the gap |
| `request_delivery_unproven` | `server_bridge_journal.py`, `server_bridge_final_status.py` **only** | implemented, undocumented for operators |
| `initiator` | nowhere | absent |

## 3. Timeline

Times UTC. Only lane-relevant steps.

| Time | Event | Outcome |
| --- | --- | --- |
| — | `unity_status_summary` | `editor_running: false`, `stale_reason: editor_pid_not_alive`, recommends `recover_editor_session` |
| — | `ensure-ready` (no `--open-editor`) | 10 min, `editor_ready_timeout`; reused a stale host-session record incl. its `background_open: true` |
| — | `recover-editor-session` | `ok`; cleared stale state, did not reopen |
| — | `ensure-ready --open-editor` | `verdict: ready`, `healthy`, `compiler_error_count: 0` |
| 10:58 | `unity.project.refresh` | settled, `post_settle_compile: passed`, trust `confirmed` |
| 11:00 / 11:01 | player compile Android, iOS | both passed, 0 errors |
| 11:02 | EditMode, two touched classes | 38/38; count matched the expected 32 + 6, proving a non-stale assembly |
| 11:04 | EditMode, both assemblies | 433/433 |
| 11:07-11:15 | two executed regression reds + restores | each red failed exactly one intended test; final rerun 433/433 |
| 11:19:16 | profile-switch project action | hook `passed`/`environment_applied`; scenario `failed` on its own post-action compile with `editor_busy` |
| 11:19:45 | `unity.scenario.result` | `request_delivery_unproven`; envelope `mutation_trust_class: not_evaluated` |
| — | asset read from disk | `ConfigName` had in fact changed — **off-surface ground truth** |
| 11:23 | player compile under the dev profile | passed, 0 errors |
| 11:26 | scene open + Play Mode enter | reached the interactive lobby scene |
| 11:27 | `unity_console_grep`, anchored | `match_count: 0`, `search_verdict: inconclusive`, 1.66 MB of scope unsearched |
| — | shell `tail -c +<offset> | grep` | found the evidence immediately |
| 11:29 / 11:32 | project action by canonical id, then by alias | both rejected by the project hook (`unsupported_action`) |
| 11:36 | scenario, poll-until without `continueWhen` | step failed on `running` after one poll; promoted payload fields still returned decision-ready product evidence |
| 11:38 | scenario with `payload` on a plain hook step | validated `valid`, failed at runtime with an empty action |
| 11:41 | Play Mode exit | `edit`, settled |
| 11:51-12:12 | **17 further requests this session did not issue** | refresh, playmode, EditMode tests, scene open, screenshot, 3x ui.query, 2x ui.click, 3x playmode.state, status, playmode.set |

## 4. What Worked Well

- **Unity-side execution was flawless.** Five refreshes, four player compiles, five EditMode runs, two Play Mode
  transitions, six scenario runs, fifteen bridge generations, zero Unity-side failures and zero test flakes.
- **`post_settle_compile_trust_class: confirmed`** made every compile claim decision-ready without a second call.
- **The EditMode staleness cross-check paid for itself.** Comparing the reported `total` against the expected test
  count turned "38/38 passed" into proof that the newly written tests were actually in the built assembly. This is
  the cheapest high-value check in the whole lane.
- **`promotePayloadFields` produced decision-ready product evidence from a step that failed.** The first smoke run
  failed on a predicate, yet still returned readiness, option counts, rendered-button counts and the selected
  identifier — enough to conclude the product path was healthy without a rerun.
- **`failure_class` separated infrastructure from product** correctly across the two smoke attempts
  (`startup_lobby` vs `product_assertion`).
- **Stale-state classification was decisive.** `bridge_pid_matches_project: false`, `editor_pid_alive: false`, and
  `discovery_classification: stale_state` correctly refused to treat a healthy-looking recorded bridge as live.

## 5. What Worked Poorly

- A successful mutation surfaced as a failed one, with a verdict field that had no bearing on what Unity did.
- A concurrent actor drove the same editor for twenty minutes with no signal on any surface.
- A truncated console scope remained answerable only by leaving the tool.
- Scenario validation accepted two authoring mistakes it had the information to reject.
- The offline recovery path was the session's largest token consumer: a single `unity_status_summary` against a dead
  editor returned a fully nested error tree — `host_prerequisites`, `transport_state`, `state_groups`,
  `editor_log_diagnosis`, `stale_request_artifacts` — while labelled `payload_mode: compact_status_summary`.

## 6. What Was Not Explicit Enough

- `mutation_trust_class: not_evaluated` reads as "no verdict", not as "Unity probably completed this; the response
  was lost". The distinction is the entire point of the shipped trust-class vocabulary.
- `request_delivery_unproven` exists in the journal and nowhere in the operator documentation, so the one artifact
  that explains P1-1 is undiscoverable at the moment it is needed.
- Nothing said the recorded host session was reusable-but-stale, so `ensure-ready` inherited a previous session's
  `background_open: true` for an editor that no longer existed.
- Nothing warned that a project action's canonical catalog id may be rejected by the hook that implements it.

## 7. What The Operator Needed But Did Not Have

1. A mutation verdict that distinguishes "not applied" from "applied, response lost".
2. Request attribution, so "the editor is idle in Edit Mode" can be trusted to mean *this* session left it that way.
3. A way to widen or page an anchored console search without leaving the MCP surface.
4. Authoring-time rejection of a hook payload the runtime will discard.
5. A fast-fail on `ensure-ready` when no live editor exists and reopening was not requested.

## 8. Scoring

| Category | Score | Basis |
| --- | --- | --- |
| Unity-side execution stability | 9/10 | zero Unity-side failures across 46 requests and 15 generations |
| Request journaling quality | 6/10 | rich taxonomy; no initiator; the decisive event undocumented |
| Bridge health observability | 8/10 | stale-state and pid-match classification were correct and decisive |
| Wrapper-to-operator clarity | 5/10 | a completed mutation reported as not completed |
| Recovery guidance quality | 7/10 | the right command was offered in call one; the lane still allowed a 10-minute dead wait |
| Transport lifecycle transparency | 8/10 | every reclassification carried an accurate, specific reason |
| End-to-end trustworthiness during churn | 5/10 | the session's only material mutation needed off-surface verification |
| Parallel request handling | 4/10 | concurrent driving of the same editor was entirely invisible |
| Token efficiency of the default operator path | 5/10 | the offline error envelope dominated session MCP spend despite compact mode |
| Time-to-diagnosis | 7/10 | minutes for compile/test truth; ~12 min for editor start, ~6 min lost to two authoring misses |
| Validation workflow discipline | 9/10 | compile-first ordering, staleness cross-check, and executed reds all held |

Mean: **6.6/10**.

## 9. Priority Improvements

**P1-1 — propagate the shipped trust-class vocabulary into the project-action mutation envelope.**
When a mutating action's hook reports success and the response is then lost to a lifecycle reset, the envelope must
report `unity_completed_host_delivery_unproven` (or an equivalent mutation-scoped trust class) rather than
`mutation_trust_class: not_evaluated` with `operator_verdict: mutation_not_completed`. Acceptance: a churn test that
resets the response channel after a hook success asserts the completed-but-unproven class, and the recommended next
action is a re-read of state rather than a re-apply of the mutation. Re-applying a mutation on this evidence is the
real hazard the current wording invites.

**P1-2 — add initiator attribution to request journal events and to status surfaces.**
A stable per-client or per-session identifier on `request_submitted`/`request_completed`, plus a
`foreign_requests_since` counter (or last-foreign-request timestamp) on `unity_status_summary`. Acceptance: with two
clients driving one project, each can identify which requests are its own, and a status call after foreign activity
says so. This also protects the retro lane itself, whose conclusions rest on journal reads.

**P1-3 — escalate the 2026-08-19 P2 (operator-controlled window / import-freshness hints) to P1 on second sighting.**
The verdict ranking shipped for that retro behaved correctly here — it refused to call a truncated zero-match a
negative. The remaining gap is that `inconclusive` is currently a dead end inside the tool: a `maxSearchChars`
argument, or a documented offset-continuation, would keep the operator on-surface. Two independent sightings, both
ending in a shell fallback.

**P2-1 — make `unity_scenario_validate` reject or warn on a `project_defined_hook` step carrying `payload`.**
The validator knows the step kind and knows which payload fields that kind consumes. Acceptance: the step shape that
silently produced an empty action returns a validation warning naming `payloadJson`/`hookPayloadJson`.

**P2-2 — warn when a poll-until step declares `passWhen`/`failWhen` and no `continueWhen`.**
Documented behavior, repeated operator miss; a validator warning is cheaper than more documentation.

**P2-3 — fast-fail `ensure-ready` when no live editor exists and `--open-editor` was not passed**, and do not inherit
a dead host session's launch flags. Acceptance: the dead-pid case returns in seconds with the recovery command, not
after the full timeout.

**P3 — trim the offline `unity_status_summary` error envelope.** In compact mode, keep the classification, the
blocking codes and the recommended command; move the nested prerequisite/transport/state-group/log-diagnosis trees
behind `includeFullPayload`. The 2026-05-07 token-stability retro established summary-first recovery; the offline
failure path is the remaining offender.

## 10. Public-Promotion Recommendations

- `docs/operations/CONTINUATION.md` — document `request_delivery_unproven` and the mutation trust-class reading as an
  operator branch: hook success plus lost response means verify state, not re-apply.
- `docs/operations/SMOKE_TESTS.md` — add the mutation-churn branch above, and a one-line authoring note that a plain
  hook step takes `payloadJson` while poll-until steps take `startPayload`/`pollPayload`.
- `docs/reference/STATUS.md` — record the second sighting against the open anchored-window residual.
- `README.md` — one line on initiator attribution once P1-2 lands, since multi-client operation is now observed
  rather than hypothetical.
- Wrapper/runtime: P1-1 envelope change, P1-2 journal field, P2-1/P2-2 validator warnings, P2-3 fast-fail.
- Acceptance checks: the churn test in P1-1, the two-client test in P1-2, and validator regression for P2-1/P2-2.

Project-specific evidence stays local and is deliberately not duplicated here: the consumer project's own
catalog-to-hook action-id mismatch (its payout-flow smoke actions were unreachable through the project-action lane because the
hook's normalizer knew only the alias spellings, not the catalog's canonical ids) is tracked as a task in that
project, not as an MCP retro item. The reusable half of it is that neither `project-action-list` nor
`project_action_invoke` can currently detect that a hook will reject the id the invoker is contractually going to
send; a `list_actions` preflight or a stated convention would close that class.

## 11. Final Verdict

**PASS with reservations.** Unity-side execution and validation discipline were the strongest parts of the session:
compile-first ordering, the staleness cross-check, and executed regression reds produced trustworthy evidence and
caught nothing false. The weak axis is operator trust around *mutations* and *concurrency* — the two places where the
lane described a state that did not match reality, once by understating a success and once by staying silent about a
second actor. Neither cost correctness here only because ground truth was available outside the tool, which is the
definition of a surface gap rather than a lucky escape. Three of the six frictions were the operator's, and one of
those repeats a previously retro'd pattern, which argues for field prominence in the compact envelope over more
documentation.
