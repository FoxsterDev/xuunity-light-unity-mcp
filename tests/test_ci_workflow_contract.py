from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_TESTING_DIR = REPO_ROOT / "scripts" / "testing"
if str(SCRIPTS_TESTING_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_TESTING_DIR))

import check_release_ci_gates as gate

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
UNITY_CI_WORKFLOW = WORKFLOWS_DIR / "unity-package-ci.yml"
TAG_GATE_WORKFLOW = WORKFLOWS_DIR / "release-tag-gate.yml"
UNITY_CI_DOC = REPO_ROOT / "docs" / "operations" / "UNITY_PACKAGE_CI.md"


def workflow_display_name(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^name:\s*(.+?)\s*$", line)
        if match:
            return match.group(1)
    return ""


def workflow_unity_versions(text: str) -> list[str]:
    match = re.search(r"unity-version:\s*\[([^\]]+)\]", text)
    if not match:
        return []
    return [item.strip().strip('"') for item in match.group(1).split(",")]


class RequiredGateNamesStayInSyncTests(unittest.TestCase):
    """Renaming a workflow silently breaks the release gate; pin the mapping."""

    def test_every_release_gate_workflow_name_matches_a_checked_in_workflow(self) -> None:
        """Waived names are pinned too: a rename during a waiver would make the restore a silent no-op."""
        display_names = {workflow_display_name(path) for path in WORKFLOWS_DIR.glob("*.yml")}
        for required in gate.RELEASE_GATE_WORKFLOWS:
            self.assertIn(required, display_names)

    def test_the_tag_gate_workflow_is_not_a_required_gate_of_itself(self) -> None:
        self.assertNotIn(workflow_display_name(TAG_GATE_WORKFLOW), gate.REQUIRED_WORKFLOWS)


class UnityPackageCiWorkflowContractTests(unittest.TestCase):
    def test_matrix_covers_two_unity_lines(self) -> None:
        versions = workflow_unity_versions(UNITY_CI_WORKFLOW.read_text(encoding="utf-8"))

        self.assertEqual(len(versions), 2)
        majors = {version.split(".")[0] for version in versions}
        self.assertEqual(len(majors), 2, f"both matrix pins are on the same Unity line: {versions}")

    def test_matrix_covers_the_no_ugui_lane(self) -> None:
        text = UNITY_CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(text, r"lane:\s*\[ugui,\s*no-ugui\]")

    def test_workflow_scaffolds_through_the_tested_python_script(self) -> None:
        text = UNITY_CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/testing/scaffold_unity_ci_project.py", text)
        self.assertTrue((SCRIPTS_TESTING_DIR / "scaffold_unity_ci_project.py").is_file())

    def test_test_runner_action_and_image_are_pinned(self) -> None:
        text = UNITY_CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("game-ci/unity-test-runner@v4.3.1", text)
        self.assertIn("unityci/editor:ubuntu-${{ matrix.unity-version }}-base-3", text)

    def test_missing_license_secrets_fail_instead_of_skipping(self) -> None:
        text = UNITY_CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("license-preflight", text)
        self.assertIn("exit 1", text)
        self.assertIn("::error::Unity license secrets are not configured", text)

    def test_master_push_trigger_has_no_path_filter(self) -> None:
        """A path-filtered master trigger would leave release SHAs without Unity
        evidence and the tag gate would block on missing runs."""
        text = UNITY_CI_WORKFLOW.read_text(encoding="utf-8")
        if "push:" not in text:
            self.skipTest("workflow is manual-only; covered by the manual-only contract test")
        push_block = text.split("pull_request:", 1)[0]
        self.assertIn("- master", push_block)
        self.assertNotIn("paths:", push_block)

    def test_manual_only_mode_states_its_reason_and_stays_accounted_for(self) -> None:
        """Dropping the automatic triggers is allowed only while the workflow says why
        and the release gate still accounts for it — either by requiring it, or by an
        explicit waiver that reports the missing Unity evidence. Manual-only plus a
        silent disappearance from the gate is the one combination that would let a
        release tag a SHA with no Unity evidence and still print a clean verdict."""
        text = UNITY_CI_WORKFLOW.read_text(encoding="utf-8")
        if "push:" in text:
            return
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("manual-only", text)
        name = workflow_display_name(UNITY_CI_WORKFLOW)
        self.assertIn(name, gate.RELEASE_GATE_WORKFLOWS)
        self.assertTrue(
            name in gate.REQUIRED_WORKFLOWS or name in gate.WAIVED_GATES,
            f"{name} is manual-only and neither required nor waived: the gate would report a clean release",
        )


class ReleaseTagGateWorkflowContractTests(unittest.TestCase):
    def test_tag_pushes_trigger_the_gate(self) -> None:
        text = TAG_GATE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("tags:", text)
        self.assertIn('- "v*"', text)

    def test_the_gate_runs_the_tested_python_script(self) -> None:
        text = TAG_GATE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/testing/check_release_ci_gates.py", text)
        self.assertIn("--wait-seconds", text)


class UnityCiDocumentationContractTests(unittest.TestCase):
    def test_the_ci_doc_exists_and_names_the_pinned_unity_versions(self) -> None:
        self.assertTrue(UNITY_CI_DOC.is_file(), "docs/operations/UNITY_PACKAGE_CI.md is missing")
        doc_text = UNITY_CI_DOC.read_text(encoding="utf-8")
        for version in workflow_unity_versions(UNITY_CI_WORKFLOW.read_text(encoding="utf-8")):
            self.assertIn(version, doc_text)

    def test_the_ci_doc_documents_every_license_secret(self) -> None:
        doc_text = UNITY_CI_DOC.read_text(encoding="utf-8")
        for secret in ("UNITY_LICENSE", "UNITY_EMAIL", "UNITY_PASSWORD", "UNITY_SERIAL"):
            self.assertIn(secret, doc_text)


if __name__ == "__main__":
    unittest.main()
