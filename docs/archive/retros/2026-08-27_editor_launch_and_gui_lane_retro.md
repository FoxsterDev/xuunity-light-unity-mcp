# MCP Retro — Editor Launch Blockers and GUI Evidence Lanes

Date: 2026-08-27
Status: `implemented, locally Unity-validated, and released in v0.3.61`

## Summary

A command-line Unity launch could leave a live editor process blocked before the
MCP bridge attached. The helper waited to its readiness deadline, but the
operator received neither the Unity startup argument needed by the host nor the
Editor.log line that already explained the block. The same validation session
also exposed avoidable scenario-authoring failures: profile mutations followed
by refresh, missing hooks hidden behind build-profile define constraints,
one-shot poll-until behavior, unpinned Game Views, mixed progress/result output,
host-specific hook defaults, and quit acknowledgement without process exit.

## Implemented Improvements

1. `open-editor` and `ensure-ready --open-editor` accept repeatable
   `--unity-arg` values and record the effective argument list. Requested
   arguments cannot be falsely attributed to an already-running editor.
2. A live editor whose bridge never attaches returns its PID, Editor.log path
   and idle time. Licensing, API-updater, and startup-dialog markers produce
   `launch_blocked_probable_modal` with the last matched line. Fresh licensing
   markers receive a bounded five-second recovery window because Unity 2022 can
   briefly report a missing channel before starting its version-local client;
   stale invalid-license evidence still fails immediately.
3. `scenario_invalid` includes the first validation cause. Missing-hook
   diagnostics can name the candidate assembly's define constraints and active
   player defines.
4. `mutationSettlePolicy: apply_then_gate` enforces `wait`, `status`, then
   `compile_player_scripts`, and refuses an immediate `project_refresh`.
5. `project_defined_hook_poll_until` continues unmatched successful payloads by
   default when `continueWhen` is omitted.
6. Catalog actions may declare `hostScoped: true` and
   `requiredPayloadFields`; missing project-specific values fail early as
   `hook_is_host_scoped`.
7. `--json-only` is available on every host helper subcommand.
8. UI-evidence guidance requires a fixed Game View size before Play Mode and a
   bounds query after surprising captures.
9. `request-editor-quit --force-after-ms` provides an explicit, identity-gated
   escalation for one same-project editor PID and verifies process exit.

## Operator Rule

A silent launch wait is an Editor.log read. Do not extend a readiness deadline
without inspecting the project-scoped editor log produced by that launch.

## Validation State

Host regressions pass `966/966` with `14` platform skips. Clean Unity
`6000.0.58f2` and `2022.3.67f2` projects reached healthy bridges through the
current Hub channel. The Unity 2022 run also reproduced and closed the transient
missing-channel race described above. Current-source package tests passed
EditMode `91/91` and PlayMode `5/5` on both versions; each temporary editor was
closed with process exit verified. A Unity `2022.3.62f3` consumer also passed
EditMode `91/91` and PlayMode `18` passed with one expected environment skip. A
Unity `6000.0.58f2` consumer passed Android compile plus apply-gate `7/7`, GUI
scenario `18/18`, and profile-restore `8/8` contracts.

Release closeout completed on 2026-08-27. The implementation shipped in
`v0.3.61` at commit `0a310270910d35b39f8d7c3b8158be1d1936d250` after the
required commit and tag gates passed. The non-draft, non-prerelease GitHub
Release is the Latest release before `v0.3.62`; the public product page was
synchronized and production canonical/indexing checks passed. Consumer pins
were preserved because every discovered package manifest and lock was already
dirty at the frozen baseline.
