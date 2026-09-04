#!/usr/bin/env python3
"""Keep release commits separate from the work they publish.

A release used to land as one commit carrying the feature code, its tests, the whole
documentation sweep and the version bump. That loses bisect and revert granularity: the
only description of the change is the changelog, and reverting the release also reverts
the product change. It also lets a version bump ride inside a feature commit unnoticed.

The contract this enforces:

* A `release:` commit may only carry release metadata and release-facing documentation —
  the files `scripts/tools/sync_release_version.py` sweeps, plus the changelog and the two
  release bookkeeping documents. `templates/server.py` and
  `templates/server_batch_orchestrator.py` are swept for their `SERVER_INFO` version, so a
  release commit may change those files only on that line.
* Any other commit must not bump the version: no package metadata, no package manifests,
  no `SERVER_INFO` version, and no new numbered changelog section. Writing under
  `## Unreleased` is how work describes itself.

Run it on the release candidate before tagging, or over a range in CI.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from sync_release_version import (  # noqa: E402
    CHANGELOG,
    PACKAGE_JSON,
    PACKAGE_MANIFESTS,
    RELEASE_DOCS,
    ROOT_PACKAGE_JSON,
    ROOT_PACKAGE_LOCK,
    SERVER_INFO_TEMPLATES,
)

RELEASE_SUBJECT_PREFIXES = ("release:", "release(", "Release v")

VERSION_METADATA_PATHS = frozenset(
    path.as_posix()
    for path in (ROOT_PACKAGE_JSON, ROOT_PACKAGE_LOCK, PACKAGE_JSON, *PACKAGE_MANIFESTS)
)
SERVER_INFO_PATHS = frozenset(path.as_posix() for path in SERVER_INFO_TEMPLATES)
BOOKKEEPING_PATHS = frozenset(
    {
        "docs/archive/retros/RETRO_REGISTRY.md",
        "docs/architecture/designs/DESIGN_PLAN_HISTORY.md",
    }
)
RELEASE_ALLOWED_PATHS = frozenset(
    {CHANGELOG.as_posix()}
    | VERSION_METADATA_PATHS
    | SERVER_INFO_PATHS
    | BOOKKEEPING_PATHS
    | {path.as_posix() for path in RELEASE_DOCS}
)


def is_release_subject(subject: str) -> bool:
    return str(subject or "").strip().startswith(RELEASE_SUBJECT_PREFIXES)


def added_changelog_release_heading(changelog_added_lines: list[str]) -> str:
    for line in changelog_added_lines:
        text = line.strip()
        if not text.startswith("## "):
            continue
        heading = text[3:].strip()
        if heading and heading[0].isdigit():
            return heading
    return ""


def classify_commit(
    *,
    subject: str,
    changed_paths: list[str],
    server_info_changed_lines: dict[str, list[str]],
    changelog_added_lines: list[str],
) -> list[str]:
    """Return the contract violations for one commit. Empty means the shape is fine."""

    errors: list[str] = []
    release = is_release_subject(subject)
    paths = sorted({str(path) for path in changed_paths if str(path)})

    if release:
        stray = [path for path in paths if path not in RELEASE_ALLOWED_PATHS]
        if stray:
            errors.append(
                "release_commit_carries_work: a release commit may only carry release metadata "
                "and release-facing docs. Move these into their own commit and re-run the "
                "release commit on top: " + ", ".join(stray)
            )
        for path in sorted(SERVER_INFO_PATHS & set(paths)):
            offending = [
                line
                for line in server_info_changed_lines.get(path, [])
                if '"version":' not in line
            ]
            if offending:
                errors.append(
                    f"release_commit_changes_logic: {path} is swept for its SERVER_INFO version, "
                    "so a release commit may only change that line. Offending change: "
                    + offending[0].strip()[:120]
                )
        return errors

    bumped = sorted(VERSION_METADATA_PATHS & set(paths))
    if bumped:
        errors.append(
            "version_bump_outside_release_commit: the version sweep belongs in the release "
            "commit. Revert these here and let `sync_release_version.py` write them: "
            + ", ".join(bumped)
        )
    for path in sorted(SERVER_INFO_PATHS & set(paths)):
        version_lines = [
            line for line in server_info_changed_lines.get(path, []) if '"version":' in line
        ]
        if version_lines:
            errors.append(
                f"version_bump_outside_release_commit: {path} changes the SERVER_INFO version "
                "outside a release commit."
            )
    heading = added_changelog_release_heading(changelog_added_lines)
    if heading:
        errors.append(
            f"changelog_release_section_outside_release_commit: this commit opens `## {heading}`. "
            "Describe work under `## Unreleased`; the release commit promotes it."
        )
    return errors


def run_git(args: list[str], repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60.0,
    )
    if completed.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {(completed.stderr or '').strip()}")
    return completed.stdout


def commit_subject(repo_root: Path, rev: str) -> str:
    return run_git(["show", "--no-patch", "--format=%s", rev], repo_root).strip()


def commit_parent_count(repo_root: Path, rev: str) -> int:
    line = run_git(["rev-list", "--parents", "-n", "1", rev], repo_root).split()
    return max(0, len(line) - 1)


def commit_changed_paths(repo_root: Path, rev: str) -> list[str]:
    output = run_git(["show", "--name-only", "--format=", rev], repo_root)
    return [line.strip() for line in output.splitlines() if line.strip()]


def commit_added_lines(repo_root: Path, rev: str, path: str) -> list[str]:
    output = run_git(["show", "--format=", "--unified=0", rev, "--", path], repo_root)
    return [line[1:] for line in output.splitlines() if line.startswith("+") and not line.startswith("+++")]


def commit_changed_lines(repo_root: Path, rev: str, path: str) -> list[str]:
    output = run_git(["show", "--format=", "--unified=0", rev, "--", path], repo_root)
    changed: list[str] = []
    for line in output.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            changed.append(line[1:])
    return changed


def check_commit(repo_root: Path, rev: str) -> tuple[str, list[str]]:
    subject = commit_subject(repo_root, rev)
    if commit_parent_count(repo_root, rev) > 1:
        return subject, []
    paths = commit_changed_paths(repo_root, rev)
    server_info_changed_lines = {
        path: commit_changed_lines(repo_root, rev, path)
        for path in SERVER_INFO_PATHS
        if path in paths
    }
    changelog_added_lines = (
        commit_added_lines(repo_root, rev, CHANGELOG.as_posix())
        if CHANGELOG.as_posix() in paths
        else []
    )
    return subject, classify_commit(
        subject=subject,
        changed_paths=paths,
        server_info_changed_lines=server_info_changed_lines,
        changelog_added_lines=changelog_added_lines,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check release-commit shape.")
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--range", dest="commit_range", default="")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    if args.commit_range:
        revs = [
            line.strip()
            for line in run_git(["rev-list", "--reverse", args.commit_range], repo_root).splitlines()
            if line.strip()
        ]
    else:
        revs = [args.commit]

    failures = 0
    for rev in revs:
        subject, errors = check_commit(repo_root, rev)
        short = run_git(["rev-parse", "--short", rev], repo_root).strip()
        if errors:
            failures += 1
            print(f"release_commit_shape=failed commit={short} subject={subject!r}")
            for error in errors:
                print(f"  - {error}")
        else:
            shape = "release" if is_release_subject(subject) else "work"
            print(f"release_commit_shape=ok commit={short} shape={shape}")

    if failures:
        print(f"release_commit_shape=failed commits={failures}")
        return 1
    print(f"release_commit_shape=ok commits={len(revs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
