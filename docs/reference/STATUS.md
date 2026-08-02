# Status

Date: `2026-08-02`
Status: `active public status snapshot`

XUUnity Light Unity MCP is a working same-host Unity Editor automation service
for MCP-capable AI agents. The current released source line is `v0.3.51`.

## Current Package

Unity package:

```text
com.xuunity.light-mcp
```

Current Git UPM URL:

```text
https://github.com/FoxsterDev/xuunity-mcp.git?path=/packages/com.xuunity.light-mcp#v0.3.51
```

Current package path:

```text
packages/com.xuunity.light-mcp
```

Migration note:

- `v0.3.11` and earlier used `templates/unity-package`.
- `v0.3.12+` uses `packages/com.xuunity.light-mcp`.
- `v0.3.14+` keeps the default package metadata on Unity `2021.3` and makes
  Test Framework-backed operations optional.
- `v0.3.15+` adds license-aware batch fallback and Codex helper install-target
  selection.
- `v0.3.29+` adds project-defined hook poll-until scenarios and richer compact
  scenario summaries.
- `v0.3.32+` makes `unity_scenario_run_and_wait` a compact decision-verdict
  surface by default, with lifecycle relaunch attribution and full-payload
  opt-in.
- `v0.3.34+` makes refresh, compile, build-config compile, and direct test MCP
  responses compact by default while preserving authoritative post-settle
  verdict fields and `includeFullPayload=true` recovery.
- Current source qualifies refresh `playmode_state_after_settle` with explicit
  source/trust metadata; bridge identity churn yields `stale_risk` and directs
  PlayMode-sensitive callers to confirm via `unity_playmode_state`.
- Current source also keeps a terminal scenario inconclusive when a confirmed
  project-hook `*_applied` mutation is followed by a refresh-settle timeout,
  while explicitly separating the applied mutation from the unproven settle.
- Current source adds a capability-gated uGUI PlayMode package test assembly.
  It drives the real guarded-click scenario-step path and proves exactly-once
  delivery, a decision-bearing receipt, semantic state change, the runtime
  Play Mode claim, and refusal without a receipt. The dependency-free core
  PlayMode lane remains available to projects without uGUI.
- Current source keeps passive `project_defined_hook_poll_until` readiness
  snapshots running through `status: not_started`; explicit pass/fail
  predicates still win, unmatched statuses still fail closed, and timeout stays
  authoritative.
- Current source promotes the standardized `xuunity.mutation-delta.v1` payload
  from project-defined hooks. `unity_project_action_invoke` keeps Unity
  execution success separate from acceptance: a completed mutating action is
  decision-ready only with a valid, non-destructive delta; missing/invalid
  proof or removals/count shrink produce an explicit mutation trust class,
  operator verdict, warning, and review action.
- `v0.3.38+` makes `unity_status_summary` compact by default for MCP callers,
  with `payload_mode` markers and full nested diagnostics available through
  `includeFullPayload=true`.
- `v0.3.39+` adds opt-in compact output for batch helper CLI commands through
  `--output compact`, while preserving `--output full` as the default.
- `v0.3.36+` makes `ensure-ready` compact by default,
  adds active editor-log identity and path-backed `editor_log` grep, removes
  duplicated scenario `run_start.steps` unless `includeStepPayloads=true`,
  adds post-change validation phase/churn dashboard output, and ships a
  public-safe config-applying project-action build template.
- The old path is kept only as a migration pointer for users pinned to
  `v0.3.11`.

OpenUPM status:

- the package layout is OpenUPM-ready
- the package is not documented as published on OpenUPM yet
- use Git UPM until the OpenUPM package page exists

## Current Surface

SDK rollout safety (`v0.3.45` plus current-source hardening):

- Android `unity.edm4u.resolve` now refuses to fire unless
  `BuildTarget.Android` is active and Android Build Support is loaded. Passing
  request payloads expose the target precondition while keeping
  `resolver_output_freshness=unproven` and `decision_ready=false`.
- Current source adds capability-gated `unity.sdk.android_resolve` /
  `unity_sdk_android_resolve` / `request-sdk-android-resolve`. It uses EDM4U's
  callback as completion proof, requires stable SHA-256 generated outputs across
  idle ticks, and verifies explicit expected coordinates before returning
  `trust_class=decision_grade` and `decision_ready=true`.
- Current source adds closed-project `unity.sdk.package_restore` /
  `unity_sdk_package_restore` / `request-sdk-package-restore`. Unity batchmode
  waits for an idle-stable registered package graph, publishes an atomic
  run-bound `xuunity.sdk-package-restore.v1` receipt with package ids/versions,
  dependency-XML hashes, and manifest/lock hashes, then exits. Missing receipts,
  nonzero exits, timeouts, an open project, or unproven exit all fail closed.
- `unity_sdk_generated_diff_guard` / `sdk-generated-diff-guard` provides the
  generated-file vertical slice of the SDK rollout gate. Git-tracked paths use
  a named Git ref; Git-untracked paths can use an explicit `Library/` capture
  bound to project path, Unity version, package-lock hash, and configured SDK
  versions. Capture rejects dirty trees, and comparison rejects stale
  fingerprints or tampered snapshots. The host-side compact proof also detects
  missing required markers, stale expected versions, unallowlisted changes,
  invalid structured files, and normalization-only XML/Gradle rewrites without
  opening Unity. Current source registers every published pass/fail JSON report
  as an `sdk_generated_diff_report` artifact and returns its hash plus registry
  pointer. GUI admission control, batch resolve, and portfolio orchestration
  remain separate open slices.

Implemented Unity-side operations:

- `unity.status`
- `unity.capabilities.get`
- `unity.health.probe`
- `unity.build_target.get`
- `unity.build_target.switch`
- `unity.editor.quit`
- `unity.project.refresh`
- `unity.package.install_test_framework`
- `unity.edm4u.resolve`
- `unity.sdk.android_resolve`
- `unity.sdk.dependency.verify`
- `unity.console.tail`
- `unity.console.grep`
- `unity.scene.snapshot`
- `unity.scene.open`
- `unity.scene.assert`
- `unity.tests.run_editmode`
- `unity.tests.run_playmode`
- `unity.playmode.state`
- `unity.playmode.set`
- `unity.game_view.configure`
- `unity.game_view.screenshot`
- `unity.compile.player_scripts`
- `unity.compile.matrix`
- `unity.build_player`
- `unity.scenario.validate`
- `unity.scenario.run`
- `unity.scenario.result`

Implemented Unity-side scenario step families include status, health probe,
project refresh, scene open/snapshot/assert, console grep, compile, tests, Play
Mode, Game View, waits, project-defined hooks, poll-until hooks, and
catalog-backed `project_action` steps.

Implemented host-side MCP tools and helpers:

- `unity_status`
- `unity_license_capabilities`
- `unity_status_summary`
- `unity_capabilities`
- `unity_health_probe`
- `unity_console_tail`
- `unity_console_grep`
- `unity_loading_timing`
- `unity_scene_snapshot`
- `unity_scene_open`
- `unity_scene_assert`
- `unity_compile_player_scripts`
- `unity_compile_matrix`
- `unity_tests_run_editmode`
- `unity_tests_run_playmode`
- `unity_playmode_state`
- `unity_playmode_set`
- `unity_build_player`
- `unity_game_view_configure`
- `unity_game_view_screenshot`
- `unity_project_refresh`
- `unity_build_target_get`
- `unity_build_target_switch`
- `unity_edm4u_resolve`
- `unity_sdk_android_resolve`
- `unity_sdk_dependency_verify`
- `unity_sdk_generated_diff_guard`
- `xuunity_setup_plan`
- `xuunity_setup_apply`
- `xuunity_setup_validate`
- `xuunity_uninstall_plan`
- `xuunity_uninstall_apply`
- `unity_package_install_test_framework`
- `unity_request_final_status`
- `unity_scenario_result_summary`
- `unity_scenario_results_list`
- `unity_scenario_result_latest`
- `unity_scenario_run_and_wait`
- `unity_compile_build_config_matrix`
- `unity_project_action_list`
- `unity_project_action_invoke`
- `unity_artifact_register`
- `unity_artifact_write_report`
- `unity_ui_reference_register`
- `unity_ui_reference_validate`
- `unity_ui_reference_compare`
- `unity_ui_fixture_validate`
- `unity_ui_vision_packet`
- `unity_ui_vision_submit`
- `unity_ui_interaction_validate`
- `unity_prefab_snapshot`
- `unity_prefab_validate`
- `unity_ui_tree_snapshot`
- `unity_ui_query`
- `unity_ui_exists`
- `unity_ui_get_text`
- `unity_ui_get_bounds`
- `unity_prefab_render`
- `unity_prefab_mutate`
- `unity_ui_click`
- `unity_maintenance_prune`
- `project-discovery-report`
- `registry-context-report`
- `registry-prune-contexts`
- `setup-plan`
- `setup-apply`
- `uninstall-plan`
- `uninstall-apply`
- `validate-setup`
- `install-test-framework`
- `license-capabilities`
- `open-editor`
- `ensure-ready`
- `recover-editor-session`
- `restore-editor-state`
- `request-status-summary`
- `request-final-status`
- `request-latest-status`
- `request-cancel`
- `request-stale-cleanup`
- `request-console-grep`
- `request-loading-timing`
- `request-build-player`
- `batch-compile`
- `batch-compile-matrix`
- `batch-build-config-compile-matrix`
- `batch-editmode-tests`
- `batch-test-framework-version-regression`
- `batch-build-player`
- `project-action-list`
- `project-action-invoke`
- `project-hook-scaffold`
- `artifact-register`
- `artifact-write-report`
- `artifact-probe`
- `sdk-generated-diff-guard`
- `request-sdk-package-restore`

## Current Validation Evidence

Latest release and current-source validation for `v0.3.51`:

| Area | Evidence | Result |
| --- | --- | --- |
| Package metadata | `packages/com.xuunity.light-mcp/package.json` | `name=com.xuunity.light-mcp`, `version=0.3.51`, `unity=2021.3`, no hard Test Framework dependency |
| Host Python tests | `scripts/testing/run_host_python_tests.sh` (release checks plus full discovery) | The full host suite passes `694` tests with 13 expected platform skips. |
| Compact MCP envelopes | Changelog and regression coverage for `0.3.32`-`0.3.51` | Scenario decision verdicts, compact operation/readiness/status summaries, authoritative post-settle compile/test/refresh fields, editor-log identity, scenario step-payload opt-ins, PlayMode already-playing stale-risk summaries, deterministic scene-open setup, opt-in compact batch helper output, safer `Editor.log` console grep/tail defaults, compact transport/idle timeout errors, compile-first post-change validation, lane-agnostic GUI-fallback compile evidence, and requested-filter zero-match verdicts are documented with full-payload recovery. |
| `v0.3.51` release package tests | Clean devmode projects on installed Unity editors | Unity `2021.3.45f2` and `6000.0.58f2` each discovered 99 EditMode tests: 98 passed, 0 failed, and 1 graphics-dependent render test self-skipped headless. |
| Current-source guarded interaction proof | Development-system Unity `2022.3.62f3` and main-consumer Unity `6000.0.58f2`, both in devmode | Package PlayMode tests pass `7/7` on each consumer, including the uGUI-gated guarded-click delivery and refusal tests; each project was restored to its original Git UPM pin afterwards. |
| Current-source full package gate | Clean devmode projects on Unity `2022.3.62f3` and `6000.0.58f2` | Both versions pass EditMode `62/62` and dependency-free PlayMode `5/5`, with authoritative post-settle compile green and verified editor closeout. The former prefab-mutation failure was a test dependency leak: the core test requested uGUI's `LayoutElement` in a no-uGUI project. It now uses built-in `MeshFilter` and proves both add and remove transactions. |
| Reference-driven UI acceptance | Unity `2021.3` and `6000.0` EditMode over `XUUnity.MCP.SelfTest` | `77/78` pass on both editors with one graphics-device-dependent test correctly self-skipping; the graphics-enabled `XUUnity.MCP.UiRenderClick` category passes `11/11`; a project without `com.unity.ugui` compiles with zero errors and builds only the core editor assembly. |
| Typed resolver oracle | Current-source Unity `2022.3` + EDM4U callback adapter | Inactive Android and resolver callback failure fail closed; a project-local Maven coordinate passes with callback success, two stable SHA-256 samples, explicit dependency proof, `trust_class=decision_grade`, and a cleared package-operation busy flag. |
| Consumer regression route | Compile preflight + scenario/contract + PlayMode lifecycle + consistency | Unity `6000.0` passes compile preflight `6/6`, acceptance `10/10`, refresh/compile contract, settled-state and lifecycle recovery, healthy final Edit Mode with zero compiler errors/unrecovered abandons, and project-action consistency. |
| Public site checks | `scripts/testing/run_site_ui_checks.sh` | Public site Playwright checks passed for `v0.3.51`: `42/42`. |
| Historical Git UPM release smoke | Clean Unity project pinned to an earlier public tag | Bridge reached healthy `git_pinned` status, Android APK smoke passed, package self-tests passed, and closeout verified process exit. |
| Multi-project compile matrix | Public summary evidence from consumer validation | `9/9` projects, `38/38` compile lanes, `0` failures |
| Git tag visibility | Remote Git refs | Release tag `v0.3.51` is the current Git UPM release target; remote publication requires an authenticated push. |

Cross-platform status:

| Target | Status | Notes |
| --- | --- | --- |
| macOS host tools | `validated on this host` | Shell wrapper, host tests, same-host Unity readiness/status/health probes, and post-change validation route passed. |
| Linux host tools | `portable by design` | Bash-compatible launchers/templates exist; run a Linux Unity smoke before claiming live proof. |
| Native Windows clients | `templates provided; CI-exercised` | `run.cmd`, `run.ps1`, and Windows client configs exist; the Windows CI leg drives the real `.cmd` launcher through MCP stdio `initialize`/`tools/list`/`tools/call` end to end (`tests/test_mcp_stdio_e2e.py`), incl. a Cyrillic+spaces project path, plus: a real install through the refresh launcher serving MCP from the installed copy and a spawn of the exact command written by `--install-claude-config` (`tests/test_installed_delegate_e2e.py`), the verbatim README PowerShell 5.1 quickstart with a UTF-16 plan file (`tests/test_readme_quickstart_windows_e2e.py`), the file-IPC transport against a live editor-simulator process incl. a two-process torn-read stress (`tests/test_file_ipc_bridge_simulator_e2e.py`), and cp866/cp1252 hostile-codepage legs (`tests/test_ru_console_codepage_e2e.py`); a live Windows host session with a real Unity editor still needs execution proof. |
| Unity 2021.3+ | `default package line` | Checked-in package metadata targets Unity `2021.3`; setup wizard chooses optional Test Framework recommendations per project. |
| Optional Test Framework | `capability-gated` | Core readiness stays healthy when missing; tests report `disabled_missing_dependency`, `disabled_dependency_too_old`, or supported with `upgrade_recommended` when an existing dependency should be reviewed. |
| License-aware batch fallback | `implemented; host validated` | `license-capabilities` reports batchmode support, blocker code, probe log, and recommended lane. `batch-*` commands default to `--batch-fallback-mode auto` and emit lane summary fields. Live installed-editor matrix remains follow-up evidence. |

## Package Source Modes

Use Git UPM for production consumers:

```json
{
  "dependencies": {
    "com.xuunity.light-mcp": "https://github.com/FoxsterDev/xuunity-mcp.git?path=/packages/com.xuunity.light-mcp#v0.3.51"
  }
}
```

Use local `file:` only while developing this MCP package:

```json
{
  "dependencies": {
    "com.xuunity.light-mcp": "file:/absolute/path/to/xuunity-mcp/packages/com.xuunity.light-mcp"
  }
}
```

Mode switch helpers:

```bash
bash xuunity_light_unity_mcp.sh devmode --project-root /path/to/UnityProject
bash xuunity_light_unity_mcp.sh prodmode --project-root /path/to/UnityProject
```

Rules:

- `devmode` points a Unity project at the local package working tree.
- `prodmode` pins the Unity project to the published release tag that matches
  the package version, for example `#v0.3.51`.
- `prodmode` refuses to pin when that release tag is not visible on `origin`.
- both modes remove the package lock entry so Unity re-resolves honestly.

## Install And Smoke Commands

Install host helper:

```bash
bash init_xuunity_light_unity_mcp.sh
```

Enable one project:

```bash
bash init_xuunity_light_unity_mcp.sh \
  --project-root /path/to/UnityProject \
  --enable-project
```

Readiness check:

```bash
bash xuunity_light_unity_mcp.sh ensure-ready \
  --project-root /path/to/UnityProject \
  --open-editor \
  --background-open
```

Package self-test lane:

```bash
templates/smoke/run_package_self_tests.sh \
  --project-root /path/to/UnityProject \
  --mode all
```

Multi-project compile matrix:

```bash
scripts/testing/run_multi_project_batch_compile_matrix.sh \
  --repo-root /path/to/repo-with-unity-projects \
  --parallelism 4
```

## Safety Status

Current safety guarantees:

- editor-only package assembly
- disabled-by-default bridge activation
- no normal player-build footprint by default
- no dynamic Roslyn execution path
- no SignalR or external relay dependency
- local same-host transport model
- capability-gated reflection-sensitive operations
- mutable bridge/request artifacts stay under `Library/XUUnityLightMcp/`

Current limitations:

- OpenUPM publication is still pending
- Linux and native Windows need live host smoke proof before strong support claims
- Game View operations remain reflection-gated and must be capability-probed
- License-aware batch fallback is host-capability based; unknown probe failures
  keep batch as a diagnostic path instead of pretending GUI fallback is safe
- device/runtime automation is outside the base package
- broad unrestricted editor mutation is intentionally out of scope

## Related Docs

- `../../INSTALL.md`
- `FEATURES.md`
- `../../SECURITY.md`
- `COMPARISON.md`
- `DISCOVERY.md`
- `../agents/AI_INTEGRATION.md`
- `../agents/AGENT_WORKFLOWS.md`
- `../operations/BUILD_AUTOMATION.md`
- `../operations/SMOKE_TESTS.md`
- `../architecture/ROADMAP.md`
