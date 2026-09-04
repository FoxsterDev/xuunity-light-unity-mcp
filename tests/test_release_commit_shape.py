"""The release-commit shape contract.

A release used to land as one commit carrying the product change, its tests, the docs sweep
and the version bump, so the changelog was the only description of the change and reverting
the release also reverted the product. These pin both halves of the split: a release commit
carries only release metadata and release-facing docs, and no other commit bumps the version.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts" / "testing"
for entry in (SCRIPTS_DIR, REPO_ROOT / "scripts" / "tools"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import check_release_commit_shape as shape  # noqa: E402


def classify(subject: str, paths: list[str], **kwargs) -> list[str]:
    return shape.classify_commit(
        subject=subject,
        changed_paths=paths,
        server_info_changed_lines=kwargs.get("server_info_changed_lines", {}),
        changelog_added_lines=kwargs.get("changelog_added_lines", []),
    )


class ReleaseSubjectTests(unittest.TestCase):
    def test_the_repo_history_subjects_are_recognized(self) -> None:
        for subject in (
            "release: v0.3.71 review findings and evidence integrity",
            "Release v0.3.65 Unity 6000.5 compatibility",
            "release(package): v0.4.0",
        ):
            self.assertTrue(shape.is_release_subject(subject), subject)

    def test_work_subjects_are_not_release_commits(self) -> None:
        for subject in (
            "fix(prefab): support Unity 6000.5 object references",
            "docs(retro): record the greenfield hardening MCP operator retro",
            "chore: prepare release notes",
        ):
            self.assertFalse(shape.is_release_subject(subject), subject)


class ReleaseCommitShapeTests(unittest.TestCase):
    maxDiff = None

    def test_a_metadata_and_docs_only_release_commit_passes(self) -> None:
        errors = classify(
            "release: v0.3.72 something",
            [
                "CHANGELOG.md",
                "package.json",
                "package-lock.json",
                "packages/com.xuunity.light-mcp/package.json",
                "templates/package-manifests/unity-package-6000.json",
                "README.md",
                "docs/reference/STATUS.md",
                "docs/index.html",
                "docs/archive/retros/RETRO_REGISTRY.md",
                "templates/server.py",
            ],
            server_info_changed_lines={"templates/server.py": ['    "version": "0.3.72",']},
        )

        self.assertEqual([], errors)

    def test_a_release_commit_carrying_product_code_is_refused(self) -> None:
        errors = classify(
            "release: v0.3.72 something",
            ["CHANGELOG.md", "packages/com.xuunity.light-mcp/Editor/Bridge/Anything.cs"],
        )

        self.assertEqual(1, len(errors), errors)
        self.assertIn("release_commit_carries_work", errors[0])
        self.assertIn("Editor/Bridge/Anything.cs", errors[0])

    def test_a_release_commit_carrying_tests_or_scripts_is_refused(self) -> None:
        errors = classify(
            "release: v0.3.72 something",
            ["CHANGELOG.md", "tests/test_bridge_runtime.py", "scripts/testing/run_multi_project.py"],
        )

        self.assertEqual(1, len(errors), errors)
        self.assertIn("tests/test_bridge_runtime.py", errors[0])
        self.assertIn("scripts/testing/run_multi_project.py", errors[0])

    def test_a_release_commit_may_not_change_server_logic_beside_the_version(self) -> None:
        errors = classify(
            "release: v0.3.72 something",
            ["CHANGELOG.md", "templates/server_batch_orchestrator.py"],
            server_info_changed_lines={
                "templates/server_batch_orchestrator.py": [
                    '    "version": "0.3.72",',
                    "    EDITOR_LOG_GREP_MIN_CHARS,",
                ]
            },
        )

        self.assertEqual(1, len(errors), errors)
        self.assertIn("release_commit_changes_logic", errors[0])
        self.assertIn("server_batch_orchestrator.py", errors[0])


class WorkCommitShapeTests(unittest.TestCase):
    maxDiff = None

    def test_a_work_commit_with_code_tests_and_unreleased_notes_passes(self) -> None:
        errors = classify(
            "fix(currency): converge after a settled forced refresh",
            [
                "packages/com.xuunity.light-mcp/Editor/Helpers/XUUnityLightMcpProjectActionCurrency.cs",
                "tests/test_session_scoped_evidence_contract.py",
                "docs/reference/STATUS.md",
                "CHANGELOG.md",
            ],
            changelog_added_lines=[
                "## Unreleased",
                "",
                "### Fixed",
                "",
                "- The currency gate converges after a settled forced refresh.",
            ],
        )

        self.assertEqual([], errors)

    def test_a_work_commit_may_not_bump_package_metadata(self) -> None:
        errors = classify(
            "feat: something",
            ["packages/com.xuunity.light-mcp/package.json", "package.json"],
        )

        self.assertEqual(1, len(errors), errors)
        self.assertIn("version_bump_outside_release_commit", errors[0])

    def test_a_work_commit_may_not_bump_the_server_info_version(self) -> None:
        errors = classify(
            "feat: something",
            ["templates/server.py"],
            server_info_changed_lines={"templates/server.py": ['    "version": "0.3.72",']},
        )

        self.assertEqual(1, len(errors), errors)
        self.assertIn("version_bump_outside_release_commit", errors[0])

    def test_a_work_commit_may_edit_server_logic_freely(self) -> None:
        errors = classify(
            "feat: something",
            ["templates/server.py"],
            server_info_changed_lines={"templates/server.py": ["    mark_host_client_kind(HOST_CLIENT_KIND_CLI)"]},
        )

        self.assertEqual([], errors)

    def test_a_work_commit_may_not_open_a_numbered_changelog_section(self) -> None:
        errors = classify(
            "feat: something",
            ["CHANGELOG.md"],
            changelog_added_lines=["## 0.3.72", "", "Release tag: `v0.3.72`"],
        )

        self.assertEqual(1, len(errors), errors)
        self.assertIn("changelog_release_section_outside_release_commit", errors[0])
        self.assertIn("0.3.72", errors[0])

    def test_an_unreleased_heading_is_not_a_release_section(self) -> None:
        self.assertEqual("", shape.added_changelog_release_heading(["## Unreleased", "### Fixed"]))
        self.assertEqual("0.4.0", shape.added_changelog_release_heading(["## 0.4.0"]))


class AllowlistDerivationTests(unittest.TestCase):
    def test_the_allowlist_is_derived_from_the_version_sweep(self) -> None:
        """A doc added to the sweep must not need a second edit here to stay releasable."""
        import sync_release_version as sweep

        for path in sweep.RELEASE_DOCS:
            self.assertIn(path.as_posix(), shape.RELEASE_ALLOWED_PATHS)
        self.assertIn(sweep.CHANGELOG.as_posix(), shape.RELEASE_ALLOWED_PATHS)
        for path in sweep.PACKAGE_MANIFESTS:
            self.assertIn(path.as_posix(), shape.RELEASE_ALLOWED_PATHS)

    def test_product_paths_are_not_release_allowed(self) -> None:
        for path in (
            "packages/com.xuunity.light-mcp/Editor/Bridge/XUUnityLightMcpBridgeBootstrap.cs",
            "templates/server_bridge_payloads.py",
            "tests/test_bridge_runtime.py",
            "scripts/testing/run_multi_project.py",
            "templates/smoke/run_package_self_tests.sh",
        ):
            self.assertNotIn(path, shape.RELEASE_ALLOWED_PATHS)


if __name__ == "__main__":
    unittest.main()
