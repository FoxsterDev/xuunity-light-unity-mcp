import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from bash_support import resolve_bash_executable, run_with_timeout


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"
SMOKE_DIR = TEMPLATES_DIR / "smoke"


class SmokePayloadContractTests(unittest.TestCase):
    maxDiff = None

    def _assert_block_has_full_payload(self, filename: str, start: str, end: str) -> None:
        text = (SMOKE_DIR / filename).read_text(encoding="utf-8")
        start_index = text.find(start)
        self.assertNotEqual(-1, start_index, f"{filename}: start marker not found: {start}")
        end_index = text.find(end, start_index)
        self.assertNotEqual(-1, end_index, f"{filename}: end marker not found: {end}")
        block = text[start_index:end_index]
        self.assertIn("--include-full-payload", block, f"{filename}: {start}")

    def test_step_level_scenario_smokes_request_full_payload(self) -> None:
        """Smokes that inspect raw scenario steps must not parse compact verdicts."""

        for filename, start, end in [
            (
                "run_post_change_validation.sh",
                "run_step acceptance_scenario",
                'summarize_json \\\n  "acceptance-scenario"',
            ),
            (
                "run_post_change_validation.sh",
                "run_step contract_scenario",
                'summarize_json \\\n  "contract-scenario"',
            ),
            (
                "run_lifecycle_stress_suite.sh",
                "run_step background_contract_scenario",
                'summarize_json \\\n  "background-contract-scenario"',
            ),
            (
                "run_playmode_settled_state_regression.sh",
                '"$WRAPPER" request-scenario-run-and-wait',
                '>"$TMP_DIR/scenario.json"',
            ),
        ]:
            self._assert_block_has_full_payload(filename, start, end)

    def test_playmode_settled_state_smoke_compares_the_matching_persisted_result(self) -> None:
        text = (SMOKE_DIR / "run_playmode_settled_state_regression.sh").read_text(encoding="utf-8")

        self.assertIn('direct_request_id = str(direct.get("request_id") or "")', text)
        self.assertIn('/ "test_results"', text)
        self.assertIn('persisted_state != direct_state', text)
        self.assertIn('"playmode_state_after_test_callbacks"', text)
        self.assertIn('"playmode_state_after_host_settle"', text)
        self.assertIn('"playmode_state_after_settle_source"', text)
        self.assertIn('"playmode_state_accounting_consistent"', text)
        self.assertIn('"lifecycle_churn_observed"', text)
        self.assertIn('persisted_test_result_reconciliation', text)

    def test_post_change_validation_emits_durable_phase_lines(self) -> None:
        text = (SMOKE_DIR / "run_post_change_validation.sh").read_text(encoding="utf-8")
        for phase in [
            "compile preflight",
            "readiness",
            "compile matrix",
            "acceptance scenario",
            "contract scenario",
            "PlayMode/lifecycle checks",
            "auxiliary consistency checks",
            "cleanup/restore",
        ]:
            self.assertIn(f'emit_phase "{phase}"', text)
        self.assertIn('emit_heartbeat "cleanup_restore"', text)
        self.assertIn('emit_heartbeat "auxiliary_consistency_checks"', text)

    def test_post_change_validation_classifies_bridge_churn(self) -> None:
        text = (SMOKE_DIR / "run_post_change_validation.sh").read_text(encoding="utf-8")
        self.assertIn("non_blocking_churn", text)
        self.assertIn("actionable_churn", text)
        self.assertIn("churn_classification=", text)
        self.assertNotIn("high_bridge_generation_churn", text)

    def test_post_change_validation_runs_batch_compile_before_editor_open(self) -> None:
        text = (SMOKE_DIR / "run_post_change_validation.sh").read_text(encoding="utf-8")
        compile_index = text.find('emit_phase "compile preflight" "running"')
        readiness_index = text.find('emit_phase "readiness" "running"')
        self.assertNotEqual(-1, compile_index)
        self.assertNotEqual(-1, readiness_index)
        self.assertLess(compile_index, readiness_index)
        self.assertIn('"$WRAPPER" batch-build-config-compile-matrix', text)
        self.assertIn("--batch-fallback-mode require-batch", text)
        self.assertIn("--no-progress-stdout", text)

    def test_post_change_validation_selects_lane_before_batch_preflight(self) -> None:
        text = (SMOKE_DIR / "run_post_change_validation.sh").read_text(encoding="utf-8")
        probe_index = text.find("lane_decision=probing")
        compile_index = text.find('emit_phase "compile preflight" "running"')
        self.assertNotEqual(-1, probe_index)
        self.assertLess(probe_index, compile_index)
        self.assertIn("lane_decision=interactive_mcp", text)
        self.assertIn("reason=healthy_existing_editor", text)
        self.assertIn("reason=live_editor_requires_interactive_recovery", text)
        self.assertIn("lane_decision=closed_batch_preflight", text)
        self.assertIn("lane_decision=blocked", text)
        self.assertIn('"$WRAPPER" bridge-state', text)
        self.assertNotIn('status_summary_file" 2>/dev/null', text)

    def test_post_change_validation_lane_decision_matrix(self) -> None:
        runner = SMOKE_DIR / "run_post_change_validation.sh"
        fake_wrapper_source = r'''#!/usr/bin/env bash
set -u
printf '%s\n' "$1" >> "$FAKE_WRAPPER_LOG"
case "$1" in
  request-status-summary)
    case "$FAKE_LANE_CASE" in
      healthy)
        printf '%s\n' '{"editor_running":true,"mcp_reachable":true,"health_status":"healthy","pending_request_count":0,"playmode_state":"edit","editor_pid":101,"process_visibility_available":true}'
        ;;
      closed)
        printf '%s\n' '{"editor_running":false,"mcp_reachable":false,"health_status":"offline","pending_request_count":0,"playmode_state":"","editor_pid":0,"process_visibility_available":true}'
        ;;
      *)
        printf '%s\n' 'status probe failed' >&2
        exit 41
        ;;
    esac
    ;;
  bridge-state)
    if [[ "$FAKE_LANE_CASE" == "fallback_live" ]]; then
      printf '%s\n' '{"health_status":"healthy","pending_request_count":0,"playmode_state":"edit","editor_pid":202,"_xuunity_bridge_state":{"state_is_live":true}}'
    else
      printf '%s\n' 'bridge probe failed' >&2
      exit 42
    fi
    ;;
  batch-build-config-compile-matrix)
    exit 91
    ;;
  ensure-ready)
    exit 92
    ;;
  *)
    exit 93
    ;;
esac
'''

        expectations = {
            "healthy": ("lane_decision=interactive_mcp", False, True),
            "fallback_live": ("lane_decision=interactive_mcp", False, True),
            "both_fail": ("lane_decision=blocked", False, False),
            "closed": ("lane_decision=closed_batch_preflight", True, False),
        }

        for lane_case, (expected_line, expects_batch, expects_ready) in expectations.items():
            with self.subTest(lane_case=lane_case), tempfile.TemporaryDirectory() as tmp_dir:
                temp_root = Path(tmp_dir)
                fake_wrapper = temp_root / "fake-wrapper.sh"
                fake_wrapper.write_text(fake_wrapper_source, encoding="utf-8")
                fake_wrapper.chmod(0o755)
                call_log = temp_root / "calls.log"
                project_root = temp_root / "Fake Project"
                project_root.mkdir()
                env = dict(os.environ)
                env.update(
                    {
                        "FAKE_LANE_CASE": lane_case,
                        "FAKE_WRAPPER_LOG": str(call_log),
                        "XUUNITY_LIGHT_UNITY_MCP_WRAPPER": str(fake_wrapper),
                    }
                )

                completed = run_with_timeout(
                    [
                        resolve_bash_executable(),
                        str(runner),
                        "--project-root",
                        str(project_root),
                        "--acceptance-scenario",
                        str(temp_root / "acceptance.json"),
                        "--contract-scenario",
                        str(temp_root / "contract.json"),
                        "--no-restore-editor-state",
                    ],
                    env=env,
                    timeout_seconds=30,
                )

                calls = call_log.read_text(encoding="utf-8").splitlines()
                self.assertIn(expected_line, completed.stdout)
                self.assertEqual(expects_batch, "batch-build-config-compile-matrix" in calls)
                self.assertEqual(expects_ready, "ensure-ready" in calls)
                if lane_case == "both_fail":
                    self.assertNotIn("batch-build-config-compile-matrix", calls)
                    self.assertNotIn("ensure-ready", calls)


class PackageSelfTestAssemblyPlanTests(unittest.TestCase):
    maxDiff = None

    def _discovery_source(self) -> str:
        script = (SMOKE_DIR / "run_package_self_tests.sh").read_text(encoding="utf-8")
        marker = '"$RUN_MODE" "$ASSEMBLY_PLAN_PATH" <<\'PY\'\n'
        start = script.find(marker)
        self.assertNotEqual(-1, start, "discovery heredoc marker not found")
        start += len(marker)
        end = script.find("\nPY\n", start)
        self.assertNotEqual(-1, end, "discovery heredoc terminator not found")
        return script[start:end]

    def _plan(self, dependencies: dict) -> list[list[str]]:
        source = self._discovery_source()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            script_path = root / "discovery.py"
            script_path.write_text(source, encoding="utf-8")
            project_root = root / "Project"
            packages_dir = project_root / "Packages"
            packages_dir.mkdir(parents=True)
            manifest_path = packages_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps({"dependencies": dependencies, "testables": ["com.xuunity.light-mcp"]}),
                encoding="utf-8",
            )
            lock_path = packages_dir / "packages-lock.json"
            lock_path.write_text(
                json.dumps(
                    {
                        "dependencies": {
                            name: {"version": version, "source": "registry"}
                            for name, version in dependencies.items()
                        }
                    }
                ),
                encoding="utf-8",
            )
            plan_path = root / "assembly_plan.tsv"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    str(manifest_path),
                    str(lock_path),
                    str(project_root),
                    str(REPO_ROOT),
                    "all",
                    str(plan_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120.0,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("[pass] package-self-test-discovery", completed.stdout)
            rows = [
                line.split("\t")
                for line in plan_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            return rows

    def test_plan_includes_every_capability_assembly_whose_dependency_is_installed(self) -> None:
        rows = self._plan(
            {
                "com.unity.test-framework": "1.1.33",
                "com.unity.ugui": "1.0.0",
                "com.unity.textmeshpro": "3.0.6",
            }
        )
        planned = {(row[0], row[1]) for row in rows}

        self.assertIn(("editmode", "com.xuunity.light-mcp.Editor.Tests"), planned)
        self.assertIn(("editmode", "com.xuunity.light-mcp.Editor.Ugui.Tests"), planned)
        self.assertIn(("editmode", "com.xuunity.light-mcp.Editor.Tmp.Tests"), planned)
        self.assertIn(("playmode", "com.xuunity.light-mcp.PlayMode.Tests"), planned)
        self.assertIn(("playmode", "com.xuunity.light-mcp.Editor.Ugui.PlayMode.Tests"), planned)

    def test_plan_drops_capability_assemblies_without_their_dependency(self) -> None:
        rows = self._plan({"com.unity.test-framework": "1.1.33"})
        planned = {(row[0], row[1]) for row in rows}

        self.assertIn(("editmode", "com.xuunity.light-mcp.Editor.Tests"), planned)
        self.assertIn(("playmode", "com.xuunity.light-mcp.PlayMode.Tests"), planned)
        self.assertNotIn(("editmode", "com.xuunity.light-mcp.Editor.Ugui.Tests"), planned)
        self.assertNotIn(("editmode", "com.xuunity.light-mcp.Editor.Tmp.Tests"), planned)
        self.assertNotIn(("playmode", "com.xuunity.light-mcp.Editor.Ugui.PlayMode.Tests"), planned)


if __name__ == "__main__":
    unittest.main()
