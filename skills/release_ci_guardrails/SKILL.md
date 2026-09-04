---
name: release-ci-guardrails
description: XUUnity Light Unity MCP release, tag, and CI-failure guardrails; use for version bumps, release tags, GitHub Actions failures, and follow-up fixes after CI catches platform-only regressions.
---

# Release and CI Guardrails

Use this skill before creating a release/tag and whenever GitHub Actions reports
a platform-only failure.

## Release Checklist

1. Run release checks after the final edit, not before:
   - `python3 scripts/testing/check_release_version_consistency.py`
   - `python3 scripts/testing/check_release_docs_freshness.py`
   - `python3 scripts/testing/check_public_release_safety.py`
   - `python3 scripts/testing/check_release_commit_shape.py --range origin/master..HEAD`
2. Run the host Python suite after the final edit:
   - `scripts/testing/run_host_python_tests.sh`
3. If docs/site files changed, run:
   - `scripts/testing/run_site_ui_checks.sh`
4. Clean generated artifacts before staging:
   - `node_modules`, `__pycache__`, `playwright-report`, `test-results`
5. Land the work and the release as separate commits. A release is never one
   commit.
   - One or more **work commits**: the product change with its tests and the
     documentation that describes it, each self-contained, each describing
     itself under `## Unreleased` in the changelog. A work commit must not bump
     any version.
   - Then exactly one **release commit** whose subject starts with `release:`,
     carrying only what `scripts/tools/sync_release_version.py` writes plus the
     changelog section it opens: package and lock metadata, both package
     manifests, the `SERVER_INFO` version line, the release docs, and the retro
     registry or design-plan history when their release bookkeeping changed. It
     must not carry package C#, server logic, tests, scripts or smoke runners.
   - `python3 scripts/testing/check_release_commit_shape.py --range
     origin/master..HEAD` enforces both halves and names the files to move.
     Run it before the tag; the release commit is the only commit it accepts a
     version bump from.
   - Why: the monolith loses bisect and revert granularity, makes the changelog
     the only description of the change, and lets a version bump ride inside a
     feature commit unnoticed. Reverting a release must not revert the product
     change with it.
6. Create the release commit before the annotated tag. If CI fails after a tag
   was created or pushed, prefer a follow-up fix commit unless the maintainer
   explicitly asks to retag.
7. After pushing master and before pushing the tag, run
   `python3 scripts/testing/check_release_ci_gates.py --wait-seconds 1800`.
   It blocks the tag until every required workflow has a completed successful
   `push`/`workflow_dispatch` run for the release SHA. Failed, pending, missing,
   or unverifiable gates all block; never bypass by tagging anyway. The tag-push
   `Release Tag Gate` workflow re-verifies the same contract in CI.
8. A workflow that cannot run at all (no runner license, infrastructure gone)
   may be suspended in the gate's `WAIVED_GATES` table — with a reason, the
   evidence gap, and a restore condition — instead of being dropped from the
   required set. The run then reports `status=ok_with_waived_gates`, and the
   release notes must carry the gap. Never silently delete a gate.
   `Unity Package CI` is waived today: no runner Unity license.
9. Write the changelog and GitHub Release notes with
   `docs/operations/RELEASE_NOTES_STYLE.md`. Run the fact review before the
   language review. The notes must explain the developer pain, the concrete
   behavior change, the practical benefit, exact validation, and every waiver.
10. After the annotated tag is pushed, wait for the tag-triggered
   `Release Tag Gate` to finish successfully. Then create a non-draft,
   non-prerelease GitHub Release for the existing tag with `gh release create
   --verify-tag`. Verify the published object with `gh release view`; a Git tag
   without a GitHub Release is not a completed public release.
11. Complete every host-declared downstream closeout after the GitHub Release:
    update consumer package pins, resolve and validate their package locks, and
    sync the external product site. Keep private project names and filesystem
    paths in host automation only, never in this public skill or release notes.
    A downstream failure does not rewrite release history; report the exact
    incomplete lane and recovery step.

## Windows CI Assumptions

- Do not assume `HOME`, `USERPROFILE`, `HOMEDRIVE`, or `HOMEPATH` exist in CI.
  `Path.home()` can raise `RuntimeError`. Code that only builds plans, reviews,
  helper targets, recovery commands, or optional config paths must use a safe
  fallback and must not crash when the host home directory is unavailable.
- Add a regression for home-sensitive code by clearing `os.environ` and mocking
  `Path.home()` to raise `RuntimeError("Could not determine home directory.")`.
- Do not compare raw platform path strings in tests. For structured payload paths
  that are not shell commands, compare separator-normalized suffixes or resolved
  `Path` equality.
- For shell-facing commands, do not normalize the assertion after the fact; assert
  that the emitted command already uses POSIX-safe separators and contains no
  unintended backslashes.

## CI Failure Fix Loop

1. Classify the failure as product bug, test bug, platform assumption, or release
   metadata drift.
2. Reproduce the exact failing test locally when possible.
3. Add or tighten a regression that simulates the platform invariant directly
   instead of relying on the current host OS to reproduce it.
4. Run the focused failing tests, then the relevant file-level suite, then the
   full host suite before committing.
5. Keep follow-up CI fixes small and separate from broad release/content edits.
