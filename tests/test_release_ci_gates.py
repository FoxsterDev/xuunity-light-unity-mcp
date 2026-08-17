from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_TESTING_DIR = REPO_ROOT / "scripts" / "testing"
if str(SCRIPTS_TESTING_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_TESTING_DIR))

import check_release_ci_gates as gate


def make_run(
    name: str,
    run_number: int = 1,
    event: str = "push",
    status: str = "completed",
    conclusion: str = "success",
) -> dict:
    return {
        "name": name,
        "run_number": run_number,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/FoxsterDev/xuunity-mcp/actions/runs/{run_number}",
    }


def all_green_runs() -> list[dict]:
    return [make_run(name) for name in gate.RELEASE_GATE_WORKFLOWS]


class EvaluateGatesTests(unittest.TestCase):
    def test_all_required_workflows_green_passes(self) -> None:
        gates = gate.evaluate_gates(all_green_runs(), gate.RELEASE_GATE_WORKFLOWS)

        self.assertFalse(gate.gates_blocked(gates))
        self.assertEqual([g["verdict"] for g in gates], ["pass"] * len(gate.RELEASE_GATE_WORKFLOWS))

    def test_a_failed_required_workflow_blocks(self) -> None:
        runs = all_green_runs()
        runs[0] = make_run("Integration Tests", conclusion="failure")

        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)

        self.assertTrue(gate.gates_blocked(gates))
        self.assertEqual(gates[0]["verdict"], "failed")
        self.assertIn("do not tag", gates[0]["remediation"])

    def test_a_missing_required_workflow_blocks(self) -> None:
        runs = [make_run(name) for name in gate.RELEASE_GATE_WORKFLOWS if name != "Unity Package CI"]

        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)
        by_name = {g["workflow"]: g for g in gates}

        self.assertTrue(gate.gates_blocked(gates))
        self.assertEqual(by_name["Unity Package CI"]["verdict"], "missing")
        self.assertIn("workflow_dispatch", by_name["Unity Package CI"]["remediation"])

    def test_an_in_progress_required_workflow_blocks_as_pending(self) -> None:
        runs = all_green_runs()
        runs[1] = make_run("Unity Package CI", status="in_progress", conclusion="")

        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)

        self.assertTrue(gate.gates_blocked(gates))
        self.assertEqual(gates[1]["verdict"], "pending")

    def test_the_latest_run_by_run_number_wins(self) -> None:
        runs = all_green_runs()
        runs.append(make_run("Integration Tests", run_number=2, conclusion="failure"))

        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)
        self.assertEqual(gates[0]["verdict"], "failed")

        runs.append(make_run("Integration Tests", run_number=3, conclusion="success"))
        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)
        self.assertEqual(gates[0]["verdict"], "pass")
        self.assertEqual(gates[0]["run_number"], 3)

    def test_pull_request_runs_are_not_gate_evidence(self) -> None:
        runs = [make_run(name, event="pull_request") for name in gate.RELEASE_GATE_WORKFLOWS]

        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)

        self.assertTrue(gate.gates_blocked(gates))
        self.assertEqual([g["verdict"] for g in gates], ["missing"] * len(gate.RELEASE_GATE_WORKFLOWS))

    def test_workflow_dispatch_runs_count_as_gate_evidence(self) -> None:
        runs = [make_run(name, event="workflow_dispatch") for name in gate.RELEASE_GATE_WORKFLOWS]

        gates = gate.evaluate_gates(runs, gate.RELEASE_GATE_WORKFLOWS)

        self.assertFalse(gate.gates_blocked(gates))


class CheckReleaseCiGatesTests(unittest.TestCase):
    def test_fetch_errors_block_with_cannot_verify(self) -> None:
        def failing_fetcher(repository: str, sha: str, token: str) -> list[dict]:
            raise gate.GateQueryError("GitHub API request failed")

        result = gate.check_release_ci_gates(
            repository="FoxsterDev/xuunity-mcp",
            sha="deadbeef",
            token="",
            required_workflows=gate.RELEASE_GATE_WORKFLOWS,
            wait_seconds=0.0,
            poll_interval_seconds=1.0,
            fetcher=failing_fetcher,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(
            [g["verdict"] for g in result["gates"]],
            ["cannot_verify"] * len(gate.RELEASE_GATE_WORKFLOWS),
        )
        self.assertIn("GitHub API request failed", result["error"])

    def test_wait_loop_polls_until_pending_gate_turns_green(self) -> None:
        pending = all_green_runs()
        pending[1] = make_run("Unity Package CI", status="in_progress", conclusion="")
        responses = [pending, pending, all_green_runs()]
        sleeps: list[float] = []
        ticks = iter(range(100))

        result = gate.check_release_ci_gates(
            repository="FoxsterDev/xuunity-mcp",
            sha="deadbeef",
            token="",
            required_workflows=gate.RELEASE_GATE_WORKFLOWS,
            wait_seconds=600.0,
            poll_interval_seconds=30.0,
            fetcher=lambda repository, sha, token: responses.pop(0),
            sleeper=sleeps.append,
            clock=lambda: float(next(ticks)),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(sleeps, [30.0, 30.0])

    def test_wait_loop_gives_up_at_the_deadline(self) -> None:
        pending = all_green_runs()
        pending[1] = make_run("Unity Package CI", status="in_progress", conclusion="")
        ticks = iter([0.0, 100.0, 200.0])

        result = gate.check_release_ci_gates(
            repository="FoxsterDev/xuunity-mcp",
            sha="deadbeef",
            token="",
            required_workflows=gate.RELEASE_GATE_WORKFLOWS,
            wait_seconds=150.0,
            poll_interval_seconds=30.0,
            fetcher=lambda repository, sha, token: pending,
            sleeper=lambda seconds: None,
            clock=lambda: next(ticks),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["gates"][1]["verdict"], "pending")

    def test_a_conclusively_failed_gate_does_not_wait(self) -> None:
        failed = all_green_runs()
        failed[0] = make_run("Integration Tests", conclusion="failure")
        fetch_count = [0]

        def fetcher(repository: str, sha: str, token: str) -> list[dict]:
            fetch_count[0] += 1
            return failed

        result = gate.check_release_ci_gates(
            repository="FoxsterDev/xuunity-mcp",
            sha="deadbeef",
            token="",
            required_workflows=gate.RELEASE_GATE_WORKFLOWS,
            wait_seconds=600.0,
            poll_interval_seconds=30.0,
            fetcher=fetcher,
            sleeper=lambda seconds: self.fail("must not sleep on a conclusive failure"),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(fetch_count[0], 1)


class MainContractTests(unittest.TestCase):
    def test_main_exits_zero_when_all_gates_pass(self) -> None:
        exit_code = gate.main(
            ["--sha", "deadbeef"],
            fetcher=lambda repository, sha, token: all_green_runs(),
        )
        self.assertEqual(exit_code, 0)

    def test_main_exits_one_when_a_gate_is_missing(self) -> None:
        exit_code = gate.main(
            ["--sha", "deadbeef"],
            fetcher=lambda repository, sha, token: [],
        )
        self.assertEqual(exit_code, 1)

    def test_require_overrides_the_default_required_set(self) -> None:
        exit_code = gate.main(
            ["--sha", "deadbeef", "--require", "Integration Tests"],
            fetcher=lambda repository, sha, token: [make_run("Integration Tests")],
        )
        self.assertEqual(exit_code, 0)


class WaivedGateTests(unittest.TestCase):
    """A waived gate is unproven, not passed, and must stay visible while it is suspended."""

    def test_every_waived_gate_names_a_reason_a_gap_and_a_restore_condition(self) -> None:
        for workflow_name, record in gate.WAIVED_GATES.items():
            self.assertIn(workflow_name, gate.RELEASE_GATE_WORKFLOWS, "a waiver for an unknown workflow is dead code")
            self.assertNotIn(workflow_name, gate.REQUIRED_WORKFLOWS)
            for field in ("reason", "restore_condition", "evidence_gap"):
                self.assertTrue(str(record.get(field) or "").strip(), f"{workflow_name} waiver is missing {field}")

    def test_a_waived_gate_is_reported_next_to_the_green_ones(self) -> None:
        result = gate.check_release_ci_gates(
            repository="FoxsterDev/xuunity-mcp",
            sha="deadbeef",
            token="",
            required_workflows=gate.REQUIRED_WORKFLOWS,
            wait_seconds=0.0,
            poll_interval_seconds=30.0,
            fetcher=lambda repository, sha, token: [make_run(name) for name in gate.REQUIRED_WORKFLOWS],
        )

        self.assertEqual(result["status"], "ok_with_waived_gates")
        waived = {record["workflow"] for record in result["waived_gates"]}
        self.assertEqual(waived, set(gate.WAIVED_GATES))
        self.assertFalse(waived & {record["workflow"] for record in result["gates"]})

    def test_a_waiver_never_reports_a_suspended_gate_as_passed(self) -> None:
        result = gate.check_release_ci_gates(
            repository="FoxsterDev/xuunity-mcp",
            sha="deadbeef",
            token="",
            required_workflows=gate.REQUIRED_WORKFLOWS,
            wait_seconds=0.0,
            poll_interval_seconds=30.0,
            fetcher=lambda repository, sha, token: [make_run(name) for name in gate.REQUIRED_WORKFLOWS],
        )

        self.assertNotEqual(result["status"], "ok", "a run with waived gates must not claim a clean release gate")
        self.assertEqual([record["verdict"] for record in result["waived_gates"]], ["waived"] * len(gate.WAIVED_GATES))

    def test_requiring_a_waived_gate_explicitly_re_arms_it(self) -> None:
        for workflow_name in gate.WAIVED_GATES:
            result = gate.check_release_ci_gates(
                repository="FoxsterDev/xuunity-mcp",
                sha="deadbeef",
                token="",
                required_workflows=(workflow_name,),
                wait_seconds=0.0,
                poll_interval_seconds=30.0,
                fetcher=lambda repository, sha, token: [],
            )

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["waived_gates"], [])

    def test_main_still_exits_zero_under_a_waiver(self) -> None:
        exit_code = gate.main(
            ["--sha", "deadbeef"],
            fetcher=lambda repository, sha, token: [make_run(name) for name in gate.REQUIRED_WORKFLOWS],
        )
        self.assertEqual(exit_code, 0)


class RequestBuildingTests(unittest.TestCase):
    def test_runs_url_targets_the_head_sha_endpoint(self) -> None:
        url = gate.build_runs_url("FoxsterDev/xuunity-mcp", "deadbeef")
        self.assertEqual(
            url,
            "https://api.github.com/repos/FoxsterDev/xuunity-mcp/actions/runs?head_sha=deadbeef&per_page=100",
        )

    def test_token_becomes_a_bearer_authorization_header(self) -> None:
        self.assertNotIn("Authorization", gate.build_request_headers(""))
        self.assertEqual(gate.build_request_headers("abc")["Authorization"], "Bearer abc")


if __name__ == "__main__":
    unittest.main()
