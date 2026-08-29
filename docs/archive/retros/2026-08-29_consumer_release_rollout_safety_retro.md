# Consumer Release Rollout Safety Retro

Date: `2026-08-29`
Status: `implemented, validated, and released in v0.3.62`

## Problem

A release can be correct while its downstream Unity-project rollout still
creates misleading coverage. A project omitted by discovery can disappear from
the denominator, package pins can fan out before one published-package canary
compiles, and a timed-out Unity process can outlive a bounded worker without a
safe owner for cleanup.

Those are release-lifecycle trust failures. They can leave many projects edited
without proving that the published Git package resolves and compiles, or turn a
partial matrix into an apparent portfolio pass.

## Highest-ROI Slice

The selected slice is one fail-closed consumer rollout helper that owns the
whole safety sequence without publishing or committing consumer changes:

1. reconcile explicit projects with ignore-independent package discovery;
2. freeze the clean/dirty denominator before mutation;
3. prove the Unity, licensing, write, process-visibility, and cleanup lane;
4. update and compile one canary before any portfolio fan-out;
5. persist resumable per-project evidence and stop at the first unexpected
   result;
6. allow process cleanup only after a root operator re-verifies the exact PID,
   project path, and log path.

This outranks starting another feature because the failure was observed in an
actual release closeout and can make downstream validation coverage look
stronger than it is.

## What Changed

- `scripts/testing/run_consumer_rollout.py` provides `plan`, `execute`,
  `summary`, `cleanup-owned`, and `resume-project` commands.
- Planning combines the declared project list with an ignore-independent
  manifest scan, records baseline Git and package-file state, and refuses a
  dirty canary or unsafe global Unity lane before package mutation.
- Execution updates manifest and lock together, verifies the exact release tag
  and full commit hash, compiles the canary, and only then fans out to the
  remaining clean projects.
- The atomic ledger records every transition, command, log, timeout, package
  proof, compile verdict, and cleanup state so a reviewed run can resume at the
  first unproven project.
- The generated worker packet is provider-neutral and explicitly denies
  diagnosis, release, gate-waiver, dirty-file edits, and process termination.
- Compact evidence is the default. Full evidence is opt-in, and
  credential-shaped process arguments are redacted before persistence.

## Validation Contract

Focused tests must prove the reconciled denominator, dirty-canary refusal,
global Unity preflight, successful canary/fan-out order, canary-failure and
overall-deadline stops, atomic resume, bounded-worker authority, compact output,
credential redaction, workspace side-effect detection, timeout PID capture,
and identity-gated root cleanup.

The full host suite, release version consistency, documentation freshness,
public-safety checks, and public documentation UI checks must pass on the final
release tree. The first post-release use must run `plan` with the complete
expected/discovered portfolio before any consumer edit and must preserve every
baseline-dirty package file.

## Known Limits

- The helper proves Git package resolution and script compilation. It does not
  replace project-specific Edit Mode, Play Mode, UI, or product validation.
- A project whose manifest or lock is dirty at the frozen baseline is skipped;
  the helper never overwrites that work.
- One ledger covers one selected Unity version. Mixed-version portfolios need
  separate ledgers.
- A license or global-process blocker stops before package mutation. The helper
  does not weaken the lane or diagnose an unexpected Unity failure.
