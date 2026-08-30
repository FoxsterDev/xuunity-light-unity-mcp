# Unity Hub Licensing and GUI PlayMode Operator Retro

Date: 2026-08-30

Status: implementation completed; host, docs and live macOS Hub launch validation green

Observed MCP release: `v0.3.62`

## Executive summary

A real Unity SDK release-validation session exposed an expensive admission path
before a successful local PlayMode run. The Unity test operation did not fail.
Once Unity was launched in the correct GUI lane with the active Unity Hub
licensing IPC channel, the filtered PlayMode assembly passed `20/20` in two
seconds, the editor returned to Edit Mode, post-settle compilation had zero
errors, and the helper restored the original closed-editor state with verified
process exit.

The avoidable cost came from two layers:

1. The operator initially bypassed XUUnity and launched a different installed
   Unity version directly in batch mode instead of resolving the version owned
   by `ProjectVersion.txt` and using the license-aware lane selector.
2. XUUnity `v0.3.62` correctly reported `licensing_client_ipc_failure` and
   recommended the GUI lane, but the default GUI launch still selected an
   unavailable username-derived channel rather than the already-running Unity
   Hub client's dynamic channel. The active Hub channel had to be identified
   and forwarded explicitly through the supported repeatable
   `--unity-arg=-licensingIpc` path.

This was not a package installation failure, Unity test failure, missing Test
Framework dependency, invalid entitlement, or Terms dialog. No manual UI
acceptance was required during the successful run.

The session also exposed two smaller operator-cost issues:

- `--compact-summary` calls still surfaced large nested payloads before their
  compact footer in this CLI path; and
- a PlayMode domain reload produced an intermediate `request_abandoned` event
  before the same request completed and was correctly reclassified as
  `settled_after_lifecycle_reset`.

Overall operator score for the incident: **7.1/10**. Unity execution truth,
journaling, bridge observability, and safe recovery were strong. Default
licensing handoff, compact output, and time-to-diagnosis need improvement.

## Evidence base

The source session was sanitized before promotion. Private project identity,
local paths, raw process arguments, request ids, repository state, and release
artifact identity are intentionally omitted.

| ID | Evidence class | Reusable fact |
| --- | --- | --- |
| E01 | Unity project metadata | The consumer declared Unity `2022.3.62f3` |
| E02 | Package manifest and lock | `com.xuunity.light-mcp` was declared and resolved from public tag `v0.3.62` |
| E03 | Test Framework manifest and lock | `com.unity.test-framework` `1.1.33` was present and resolved |
| E04 | License capability JSON | Batch unsupported; blocker `licensing_client_ipc_failure`; GUI recommended |
| E05 | Direct Unity log | A direct wrong-version batch launch never reached tests and repeatedly failed licensing-channel recovery |
| E06 | Default `ensure-ready` result | Live editor, no bridge, `launch_blocked_probable_modal`, subtype `licensing_channel_unavailable` |
| E07 | Read-only host process evidence | An active Unity Hub licensing client used a different dynamic IPC channel |
| E08 | Explicit-IPC `ensure-ready` result | Correct Unity version, healthy bridge, zero compiler errors |
| E09 | PlayMode request journal | Submission crossed bridge generation/domain reload and later completed |
| E10 | Persisted PlayMode result | `20/20` passed, zero failed/skipped, two-second duration |
| E11 | Post-test status | Healthy, idle, Edit Mode, zero compiler errors |
| E12 | Restore result | Graceful editor quit accepted and process exit verified |
| E13 | Post-session process snapshot | A licensing client from the direct non-MCP attempt remained outside helper ownership |

Evidence denominator:

- one license capability probe;
- one default GUI launch failure;
- one explicit-Hub-IPC GUI launch success;
- one filtered PlayMode request;
- 20 PlayMode tests;
- one post-test status confirmation;
- two helper-owned editor restorations;
- one final read-only residual-process check.

## Timeline

| Stage | Action | Result | Correct interpretation |
| --- | --- | --- | --- |
| 1 | Direct Unity executable, wrong installed version, batch PlayMode | Sandbox first blocked Package Manager IPC | Environment-blocked; package untested |
| 2 | Same direct command outside sandbox | Repeated licensing waits; no tests | Licensing/session failure; Unity operation unproven |
| 3 | `license-capabilities --refresh` on the real project | Project version resolved correctly; batch blocked; GUI recommended | Strong capability classification |
| 4 | Default `ensure-ready --open-editor` | Editor alive, bridge absent, default licensing channel unavailable | Readiness failure before bridge execution |
| 5 | Read-only Hub/licensing process inspection | One active dynamic Hub channel identified | Missing launch input discovered manually |
| 6 | `restore-editor-state` | Failed wrapper-owned editor closed and exit verified | Safe recovery |
| 7 | `ensure-ready` with explicit Hub IPC | Healthy GUI bridge on Unity `2022.3.62f3` | Successful admission |
| 8 | Filtered GUI PlayMode request | Domain reload, then `20/20` PASS | Unity-side success through lifecycle churn |
| 9 | Status confirmation | Healthy, idle, Edit Mode, zero compiler errors | Terminal state proven |
| 10 | Final restore | Graceful quit and verified process exit | Correct cleanup |
| 11 | Residual check | Direct-launch licensing client still alive | Non-MCP cleanup cost; no unsafe kill attempted |

From capability probe to proven PlayMode result took approximately 2.5 minutes.
The correct GUI lane itself took seconds. The direct route and manual licensing
discovery added the material delay.

## Installation and readiness classification

This was **not an installation failure**:

- manifest and lock sources matched `v0.3.62`;
- the package existed in `Library/PackageCache`;
- bridge enablement was present;
- the bridge attached when Unity received the active Hub IPC;
- compilation was clean; and
- PlayMode tests passed.

The closest install-retro vocabulary is `bridge_not_ready_after_install`, with
runtime subtype `licensing_channel_unavailable`. It must not be classified as:

- `package_declared_not_imported`;
- `server_boot_failed`;
- `unity_compile_error_after_install`;
- `optional_dependency_missing`; or
- `unity_package_resolve_failed`.

### Issue-ready title

`[macOS] ensure-ready recommends GUI but cannot attach until the active Unity Hub licensing IPC is forwarded explicitly`

### Smallest public reproduction

1. Start Unity Hub with a valid signed-in licensing client whose named pipe uses
   a dynamic session suffix.
2. Use a closed Unity `2022.3` project with XUUnity MCP `v0.3.62` resolved and
   bridge enablement present.
3. Run `license-capabilities --refresh`; observe batch blocked and GUI
   recommended.
4. Run `ensure-ready --open-editor` without an explicit licensing IPC argument.
5. Observe a live editor without bridge attachment and
   `licensing_channel_unavailable` for the default channel.
6. Restore the wrapper-owned editor.
7. Rerun `ensure-ready` with the active Hub channel through the supported
   repeated `--unity-arg` form.
8. Observe a healthy bridge and successful PlayMode request.

## What actually failed

### Operator routing failed first

The initial direct Unity call bypassed:

- project-version resolution;
- license capability selection;
- batch-versus-GUI routing;
- same-project editor/process ownership checks;
- bridge and request-journal evidence;
- lifecycle reconciliation; and
- safe editor restoration.

It also selected an installed Unity version different from the consumer's
declared version. This allowed Library upgrade activity before any test result
existed. Local PlayMode should have begun through XUUnity's healthy GUI route.

### XUUnity diagnosed the condition but did not complete the handoff

The `v0.3.62` primitives worked as documented:

- the capability probe classified the batch blocker;
- the launcher accepted ordered extra Unity arguments;
- startup diagnostics exposed editor PID, Editor.log and blocker kind; and
- safe restoration closed the helper-owned failed editor.

The remaining ergonomics gap was between “GUI recommended” and “GUI actually
launchable with the active Hub session.” The operator still needed host-specific
process inspection and knowledge of how to transform the Hub named-pipe value
into a Unity `-licensingIpc` argument.

### PlayMode lifecycle churn did not fail

The old bridge wrote a retryable abandoned event during domain reload. The new
bridge then wrote the successful completion for the same request, and the host
reclassified the terminal state as `settled_after_lifecycle_reset` with retry
disabled. Unity passed `20/20`.

### Cleanup was correct inside MCP ownership

Both GUI editors opened by the helper were safely closed and verified. The
direct non-MCP Unity attempt left one licensing process outside helper ownership.
The helper correctly did not guess ownership or terminate it.

## What worked well

### Unity-side execution

- Correct GUI admission produced a healthy bridge quickly.
- Pre- and post-test compilation had zero errors.
- All 20 selected PlayMode tests passed in two seconds.
- Editor state returned to Edit Mode.

### Request journaling

- Submission, start, lifecycle abandonment, completion, delivery and
  reclassification shared one stable request identity.
- Bridge generation/session changes made domain reload visible.
- Persisted test evidence retained counts, duration, lifecycle churn, callback
  state, host-settled state and recovery guidance.
- The host did not blindly retry an already-completed suite.

### Bridge observability and recovery

- Failed readiness surfaced the live editor, exact log source, package import
  state, missing bridge and startup blocker.
- Successful readiness exposed Unity version, bridge identity, transport,
  heartbeat and compiler state.
- `restore-editor-state` enforced project/process ownership and verified exit.
- No broad process termination or ambiguous PID kill occurred.

### Broader validation behavior

The same consumer validation effort also produced:

- package EditMode `186/186`;
- Android compile with 14 assemblies and zero errors;
- macOS Standalone compile with 14 assemblies and zero errors;
- Windows/Linux target-support blockers reported separately from compiler
  failures; and
- a real macOS validation player regression `10/10`.

The broader evidence supports a balanced conclusion: the compile/test bridge and
typed blocker model were valuable. The primary weakness was admission into the
correct licensed GUI session.

## What worked poorly

### The wrong path was too easy

The operator could select a direct, wrong-version Unity executable before
resolving project ownership and license lane. Documentation existed, but the
default operator flow did not prevent this class of mistake.

### GUI recommendation was not executable enough

The capability response recommended GUI while `editor_ui_supported` remained
unknown. The next default GUI launch failed on the same unavailable channel.
The recovery named the concept but did not include a validated candidate or a
copy-ready command.

### Hub IPC discovery required raw process inspection

Dynamic Hub-session discovery is platform expertise that belongs in the host
launcher. It should not depend on an AI operator inspecting and interpreting
raw process arguments.

### Compact output was too expensive

In this path, `--compact-summary` still emitted large JSON payloads before the
compact footer. Approximate model-visible output from five recovery commands
exceeded 16,000 tokens:

| Command | Approximate output tokens |
| --- | ---: |
| Default `ensure-ready` failure | 2,652 |
| First restore | 2,550 |
| Successful PlayMode request | 4,876 |
| Status confirmation | 3,619 |
| Final restore | 2,731 |

The underlying Editor.log exceeded 1.4 MB. Decision-grade facts existed, but the
default operator envelope did not remain bounded enough.

### Terminal lifecycle truth required another command

The PlayMode test payload was a real PASS but marked settled-state trust as
stale because bridge identity changed. A follow-up status check correctly proved
Edit Mode and clean compilation. The host already had enough context to perform
that bounded confirmation automatically.

### Intermediate journal state can be misread

A raw reader sees `request_abandoned` before `request_completed`. Without the
later reclassification, an operator may retry a test suite that already passed.
The terminal summary should make the final disposition primary and keep
intermediate lifecycle events behind artifact pointers.

## What was not explicit enough

1. Local package PlayMode should prefer the licensed GUI bridge.
2. `ProjectVersion.txt` must be authoritative before selecting an executable.
3. “GUI recommended” did not mean “GUI has been proven launchable.”
4. The active Hub dynamic channel differed from the username-derived default.
5. IPC attachment failure did not imply a Terms or activation dialog.
6. Compact summary did not clearly promise suppression of the nested full
   payload in this CLI path.
7. The terminal owner of an abandoned-then-completed request was not obvious to
   a raw journal reader.
8. Licensing processes spawned by a failed direct launch were outside helper
   restoration ownership.

## What the operator needed

- A single preparation path that resolves project Unity, probes licensing,
  discovers the active Hub IPC, opens/reuses GUI safely and returns a healthy
  bridge.
- Structured `licensing_ipc_resolution` with candidate count, source,
  confidence, validation result and redacted recovery command.
- A true compact terminal response with outcome, test counts, request identity,
  trust class, artifact pointers and next action only.
- Automatic post-domain-reload status confirmation for successful PlayMode
  results whose only stale signal is bridge identity churn.
- Helper-owned child-process residual accounting.
- A clear `manual_user_action_required` versus
  `machine_recoverable_with_hub_session` distinction.
- A direct-lane Unity-version mismatch guard.

## Scoring

Parallel request handling was not exercised and is reported as N/A.

| Category | Score | Reason |
| --- | ---: | --- |
| Unity-side execution stability | 9/10 | Correct GUI lane passed quickly and settled cleanly |
| Request journaling quality | 8/10 | Strong event chain; intermediate abandonment can confuse raw readers |
| Bridge health observability | 9/10 | Strong identity, transport, compiler and blocker evidence |
| Wrapper-to-operator clarity | 6/10 | Correct diagnosis, but no actionable Hub candidate and verbose output |
| Recovery guidance quality | 7/10 | Safe restore was excellent; licensing recovery required manual expertise |
| Transport lifecycle transparency | 8/10 | Generation churn and terminal reclassification were explicit |
| End-to-end trustworthiness during churn | 8/10 | Final verdict was correct; one status command remained |
| Parallel request handling | N/A | Not exercised |
| Token efficiency | 4/10 | Compact calls exposed thousands of tokens |
| Time-to-diagnosis | 6/10 | Fast after Hub evidence, but direct route and IPC discovery were avoidable |
| Validation workflow discipline | 6/10 | Final flow was disciplined; initial direct wrong-version batch was not |

Overall excluding N/A: **71/100 = 7.1/10**.

## Priority improvements

### P0 — automatic and truthful Hub licensing handoff

1. Discover active Unity Hub licensing-client candidates through host-native,
   read-only process evidence.
2. Normalize the Unity argument form without persisting the raw pipe in
   public-facing logs.
3. If exactly one valid candidate exists, use it for a wrapper-owned GUI launch
   or return a one-command approved retry according to the security policy.
4. If zero or multiple candidates exist, fail closed with candidate count,
   confidence and required human action.
5. Distinguish `terms_or_activation_ui_required` from
   `hub_ipc_available_but_not_forwarded`.
6. Make `editor_ui_supported` consistent with the proof used to recommend GUI.

Acceptance:

- one active Hub session + closed editor reaches a healthy bridge without raw
  process inspection;
- no Hub session returns a typed human action;
- multiple candidates are refused rather than guessed;
- stale candidates do not produce false readiness;
- successful output carries redacted provenance; and
- macOS, Windows and Linux adapters have platform-specific tests.

### P0 — project-version and PlayMode lane guard

- resolve `ProjectVersion.txt` before executable selection;
- refuse or prominently warn when a direct executable differs outside an
  explicit version matrix;
- route local PlayMode through the healthy GUI bridge by default; and
- reserve batch PlayMode for explicitly proven headless/CI lanes.

Acceptance: the wrong-version direct route is refused before Unity mutates
Library.

### P1 — true compact output

- compact mode emits one bounded envelope, not full payload plus compact footer;
- retain outcome, request id, Unity verdict, counts, trust class, first failure,
  artifact pointers, restore status and next action;
- expose full details only by explicit opt-in or artifact path; and
- enforce a documented byte/token ceiling in regression tests.

### P1 — one terminal PlayMode lifecycle verdict

- aggregate submitted → abandoned-on-reload → completed-on-new-generation →
  reclassified into one terminal disposition;
- automatically run bounded status confirmation when the suite passed and the
  only stale signal is bridge generation churn; and
- state whether retry is safe, forbidden or unnecessary.

Acceptance: this incident shape returns
`confirmed_success_after_lifecycle_churn`, counts, confirmed Edit Mode and
`retry=false` without a second operator command.

### P1 — helper-owned child-process residual accounting

- record licensing clients spawned as children of a wrapper-owned launch;
- revalidate exact identity during cleanup;
- terminate only when ownership remains unambiguous and policy permits; and
- never touch the shared Unity Hub licensing client.

### P2 — bounded diagnostic retro bundle

Add a read-only command that emits a sanitized bundle containing project Unity
version, MCP manifest/lock/cache alignment, license capability, editor/Hub/bridge
ownership, terminal request lifecycle, test result, restore status and bounded
log excerpts.

## Public promotion targets

| Target | Recommended addition |
| --- | --- |
| `README.md` | GUI PlayMode quick path: capability probe → Hub-aware ensure-ready → PlayMode → restore |
| `INSTALL.md` | Dynamic Hub IPC discovery, ambiguity and Terms-versus-IPC distinction |
| `docs/agents/AGENT_WORKFLOWS.md` | Resolve project Unity first; GUI-first local PlayMode; avoid direct wrong-version batch |
| `docs/operations/CONTINUATION.md` | Abandoned-plus-completed lifecycle example with one terminal owner |
| `docs/operations/SMOKE_TESTS.md` | Dynamic Hub IPC handoff and helper-owned licensing-child cleanup smoke |
| `docs/architecture/DESIGN.md` | Licensing IPC provenance/trust model and compact-output budget |
| CLI help | Candidate count, copy-ready recovery and user-action classification |
| Host/runtime | Hub channel resolver, terminal lifecycle aggregator and bounded compact envelope |

## Smallest reusable apply package

### Slice A — license resolver and launch admission

- platform-native candidate discovery;
- typed provenance/ambiguity;
- GUI launch integration;
- sanitized output;
- cross-platform host tests; and
- one live macOS Hub acceptance run.

### Slice B — compact terminal envelope

- suppress nested full payload in compact mode;
- preserve artifact pointers;
- normalize license/readiness/test/restore outcomes; and
- add byte-budget tests.

### Slice C — PlayMode terminalization and cleanup residuals

- bounded status confirmation after generation churn;
- terminal request aggregation;
- helper-owned licensing-child tracking; and
- live domain-reload PlayMode proof.

Slice A has the highest immediate operator value and can ship independently.

## Recommended validation order

1. Resolve the consumer project's declared Unity version.
2. Confirm MCP package/lock/cache/bridge setup.
3. Run `license-capabilities --refresh` before a closed-project batch action.
4. For local PlayMode, use Hub-aware GUI admission through XUUnity.
5. Confirm compile and idle state.
6. Run filtered PlayMode through the bridge.
7. Consume the terminal request/test result, not an intermediate journal event.
8. Confirm Edit Mode after lifecycle churn when the terminal envelope has not
   already done so.
9. Persist compact evidence outside Library.
10. Restore the helper-owned editor and verify exit.
11. Report unowned residual processes without guessing termination authority.

Platform-native ADB, Android emulator, iOS Simulator, `xcodebuild`, and XCUITest
automation remain separate responsibilities. XUUnity should own Unity
project/editor/build/test truth; platform runners should own device and
simulator state.

## Implementation follow-through — 2026-08-30

All implementation tracks from this retro are now closed in the host/runtime,
CLI contracts, tests and public documentation:

| Track | Implemented result |
| --- | --- |
| P0 — automatic Hub IPC handoff | Platform-native process discovery now accepts exactly one live licensing client whose current parent is Unity Hub, injects its dynamic channel internally, emits only redacted provenance/fingerprints, and fails closed for zero, stale or multiple candidates. Explicit operator-provided IPC remains supported and redacted. |
| P0 — project-version and lane guard | An explicit Unity executable whose resolved version differs from `ProjectVersion.txt` is refused before launch. License capability output distinguishes machine-recoverable Hub handoff, no-Hub/manual action, ambiguity, and Terms/activation UI. Batch lanes no longer blindly route manual-action blockers into GUI automation. |
| P1 — compact output | `--compact-summary` now captures child stdout/stderr and emits one terminal JSON envelope only. The envelope has an 8192-byte hard ceiling and retains action/request identity, verdict/counts, trust/retry state, first failure, artifacts, lifecycle disposition, licensing resolution and next action. |
| P1 — lifecycle terminalization | A passed PlayMode result followed by fresh healthy/idle/Edit Mode state after bridge generation churn is terminalized as `confirmed_success_after_lifecycle_churn` with `retry_required=false`; intermediate abandonment is not promoted over the later terminal completion. |
| P1 — owned residual cleanup | Launch sessions snapshot licensing processes, track only new children with verified editor ancestry, revalidate PID plus command fingerprint at cleanup, and refuse any client currently owned by Unity Hub. Cleanup remains exact-PID only. |
| P2 — diagnostic bundle | `diagnostic-retro-bundle --project-root ...` emits a read-only sanitized bundle with project/package/license/Hub/editor/request/restore evidence, at most 12 relevant 240-character log excerpts, and a 32768-byte bundle ceiling. Raw channel values, process commands, request ids, project/home paths, licensing identifiers and credential-like log fragments are excluded. |
| Public promotion | The Hub-aware GUI path, ambiguity/manual-action model, lifecycle terminal verdict, compact budget, ownership cleanup and diagnostic command are documented in the README, install guide, agent workflow, continuation, smoke, architecture, features and status surfaces. |

Validation evidence:

- `scripts/testing/run_host_python_tests.sh`: **979 tests passed**, 14
  platform-specific skips;
- focused Hub/licensing/operator regression tests cover macOS, Windows and Linux
  process shapes, fail-closed ambiguity/staleness, redaction, output budgets,
  lifecycle terminalization, version refusal and shared-Hub cleanup refusal;
- public-site static verification: **pass**;
- Playwright public-site UI verification: **42/42 passed** across desktop,
  mobile and narrow viewports; and
- the mandatory privacy preflight passed across all seven discovered Unity
  projects and the host opt-out;
- a live macOS launch with Unity initially closed resolved exactly one current
  Hub-owned licensing candidate, excluded one unrelated non-Hub candidate and
  reached a healthy TCP bridge on the project-declared Unity `2022.3.62f3`
  without any explicit `-licensingIpc` argument;
- the live status operation confirmed fresh heartbeat, idle Edit Mode, zero
  compiler errors, zero pending requests and a main-editor-owned bridge; and
- restore verified same-project process exit, found no remaining project
  editor, and accounted for the one helper-owned licensing child as already
  exited with zero cleanup refusals.

The live diagnostic also caught credential-like success lines emitted by
Unity's licensing module. The excerpt selector was tightened during the smoke
to retain only actionable licensing failures, exclude path-bearing compile
noise and defensively redact credential assignments and path-shaped tokens.
The hardened command was rerun against the same real log and exposed only
redacted channel failures and non-secret blocker classifications.

## Final verdict

XUUnity MCP was trustworthy at the Unity execution boundary. It distinguished
readiness infrastructure from the test result, preserved a real `20/20` PASS
through domain reload, exposed sufficient bridge/journal evidence, and restored
its editor safely.

The operator path was still too expensive. A capable operator had to correct a
wrong direct route, discover the active Hub IPC manually, interpret a GUI
recommendation that was not executable by default, read large payloads, and run
an additional status confirmation.

The reusable conclusion is:

> XUUnity `v0.3.62` has the primitives for license-aware GUI PlayMode, but the
> default host path still needs automatic, validated Unity Hub IPC handoff and a
> smaller terminal operator envelope.

The actionable work belongs in the public launcher, host summaries, lifecycle
aggregation, documentation, and smoke contracts—not in the consumer package.
