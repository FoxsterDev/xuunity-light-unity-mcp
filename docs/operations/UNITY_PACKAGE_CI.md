# Unity Package CI And Release Tag Gate

Date: `2026-08-14`
Status: `current for v0.3.56-dev`

This document describes the automated Unity package CI gates and the release
tag gate that blocks tag preparation on failed or missing gates.

## Unity Package CI Workflow

`.github/workflows/unity-package-ci.yml` runs on every push to `master`, on
pull requests, and on `workflow_dispatch`. The master push trigger has no path
filter on purpose: every master SHA must carry Unity gate evidence so the
release tag gate never reports a missing gate for a release commit.

The matrix compiles the package and runs its shipped EditMode and PlayMode
self-tests on two supported Unity lines:

- Unity `2022.3.62f1`
- Unity `6000.0.58f2`

Each line runs two project lanes:

- `ugui`: the consumer project installs `com.unity.ugui` (plus
  `com.unity.textmeshpro` on pre-6000 lines), so the capability-gated uGUI and
  TMP test assemblies compile and run.
- `no-ugui`: the consumer project installs neither, proving the package and its
  core test assemblies compile and pass in a project without uGUI.

Each job scaffolds a clean consumer project with
`scripts/testing/scaffold_unity_ci_project.py`, which references the in-repo
package through a `file:` dependency, lists it in `testables`, and pins
`com.unity.test-framework` through the same version policy the setup wizard
uses. Tests execute through `game-ci/unity-test-runner@v4.3.1` with the pinned
editor image `unityci/editor:ubuntu-<version>-base-3` and `testMode: all`.
Result XML files are uploaded as workflow artifacts.

## Unity License Secrets

Unity batch runs in CI require an activated license. The workflow reads these
repository secrets:

- `UNITY_LICENSE`: the full contents of a personal `.ulf` license file, or
- `UNITY_EMAIL` + `UNITY_PASSWORD` + `UNITY_SERIAL` for serial-based licenses.

A preflight job fails with an explicit error when neither secret set is
configured. That failure is intentional and must not be converted into a skip:
a skipped Unity gate would read as a passed one, and the release tag gate
would let an unproven package ship. If licensing is externally blocked, record
the blocker and leave the gate red; do not weaken the acceptance contract.

Fork pull requests do not receive repository secrets, so the Unity jobs are
skipped there. Fork-PR runs are not release evidence: the release gate only
accepts `push` and `workflow_dispatch` runs.

## Release Tag Gate

Release/tag preparation is blocked on the required CI gates in two places:

1. Locally, before pushing a tag:

```bash
python3 scripts/testing/check_release_ci_gates.py --wait-seconds 1800
```

The script queries the GitHub Actions runs for the release SHA (default: the
repo HEAD) and requires a completed, successful `push` or `workflow_dispatch`
run for each required workflow: `Integration Tests` (the Python suite on
Windows, macOS, and Linux), `Unity Package CI`, and `Discovery Checks`. A
failing, still-running, or missing gate exits non-zero — do not push the tag.
`--wait-seconds` bounds an optional poll loop for gates that are still
running; set `GITHUB_TOKEN` to avoid anonymous API rate limits.

2. In CI, on every tag push: `.github/workflows/release-tag-gate.yml` runs the
same script against the tagged SHA. A tag cut against a red, pending, or
missing gate produces a public failing run on that tag.

`tests/test_ci_workflow_contract.py` pins the workflow display names to the
gate script's required set, so renaming a workflow without updating the gate
fails the host suite.

## Local Equivalence Lane

The same scaffold + batch test path runs locally without GitHub:

```bash
python3 scripts/testing/scaffold_unity_ci_project.py --project-root /tmp/CiProject --unity-version <version> --lane no-ugui
"<unity-editor-path>" -batchmode -projectPath /tmp/CiProject -runTests -testPlatform EditMode -testResults /tmp/CiProject-editmode.xml -logFile /tmp/CiProject-editmode.log
"<unity-editor-path>" -batchmode -projectPath /tmp/CiProject -runTests -testPlatform PlayMode -testResults /tmp/CiProject-playmode.xml -logFile /tmp/CiProject-playmode.log
```

The richer interactive matrix (bridge, scenarios, license-aware batch compile)
remains available through `scripts/testing/run_unity_version_matrix.sh`.
