# Import Worker Bridge Ownership Retro

Date: `2026-08-26`
Status: `P0 bridge-ownership cluster implemented in current source`

## Problem

Unity Asset Import Workers are headless child processes of one main editor.
They run editor-domain initialization so import hooks can execute, but they do
not own the main editor's compile state. The bridge bootstrap previously ran in
those worker domains. A worker could therefore write `bridge_state.json` with a
fresh heartbeat, `health_status=healthy`, and zero compiler errors while the
main editor had a different compile result.

This was a false-green trust defect, not a duplicate-editor or Unity lockfile
problem. The host already separated worker processes in discovery, but the
headline bridge and compile fields could still outrank that nested evidence.

## Highest-ROI Slice

The selected slice closes three dependent obligations together:

1. prevent Asset Import Workers from initializing the bridge;
2. refuse legacy or explicit non-main bridge state on the host and never report
   its compile fields as clean;
3. make successful bootstrap journal events attributable to their writer.

This ranks above broader SDK orchestration because it prevents an observed
false positive on the core compile-verdict path and can be completed without
widening the operation surface.

## What Changed

- Bridge bootstrap checks Unity's import-worker API and command-line signatures
  before session, transport, lifecycle, heartbeat, request-pump, or journal
  initialization. Import workers return immediately.
- Main-editor and ordinary batch domains are classified separately. Bridge
  state records `bridge_process_class`, `runtime_execution_allowed`, and the
  compiler-diagnostics process class.
- Bootstrap journal events record writer pid, process class, and editor-log
  path.
- Host discovery cross-checks the recorded pid against main-editor and worker
  process tables. A proven live non-main writer becomes
  `bridge_owned_by_non_main_process`, blocks the readiness prerequisite, and
  cannot dispatch a request.
- Legacy state without a process-class field remains compatible when no
  non-main evidence exists. A legacy `AssetImportWorker*.log` identity or a
  worker/process-table mismatch is refused.
- Compact status replaces compile booleans, counts, and diagnostics from an
  untrusted writer with unknown values and a provenance note.

## Validation Contract

Focused host regression must prove:

- import-worker detection through Unity API state and both known command-line
  forms;
- the bootstrap guard appears before every initialization side effect;
- main-editor and ordinary batch classification remain distinct;
- explicit and legacy worker state cannot be read as live;
- process-table ownership wins over an apparent healthy state;
- readiness, transport, runtime dispatch, bridge stabilization, and compact
  status all fail closed;
- bootstrap journal source contains pid, process class, and log path.

Live release validation must compile and run the package tests on the supported
Unity 2022 and Unity 6000 consumer lanes. The consumer scenario/result-summary
smoke remains required because the change affects bridge lifecycle and compact
verdicts.

## Known Limits

- A state file from an older package with no process class and no worker-shaped
  log path remains legacy-unclassified until host process discovery attributes
  its pid. This preserves version-skew compatibility while still refusing a
  live mismatched writer.
- Readiness log diagnosis, UI selector truncation, click causality, package
  removal preflight, and operator-contention tracking are separate findings and
  are not implemented by this slice.
