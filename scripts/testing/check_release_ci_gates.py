#!/usr/bin/env python3
"""Block release/tag preparation until the required CI gates are green.

Queries the GitHub Actions runs recorded for a commit and verifies that every
required workflow has a completed, successful run for that exact SHA. A gate
that is failing, still running, or missing blocks the release: exit code 1.

Only `push` and `workflow_dispatch` runs count as gate evidence. Pull-request
runs are excluded because fork PRs skip license-dependent jobs, which GitHub
still reports as a successful workflow run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPOSITORY = "FoxsterDev/xuunity-mcp"
RELEASE_GATE_WORKFLOWS = (
    "Integration Tests",
    "Unity Package CI",
    "Discovery Checks",
)

# A gate the maintainer has temporarily suspended because it cannot run at all, not because it passed.
# Every entry must name why and what retires it, the gate output must carry it, and the release notes for
# any release cut under a waiver must say so: a suspended Unity gate that quietly disappears from the
# required set reads exactly like a green one, which is the failure this whole gate exists to prevent.
WAIVED_GATES = {
    "Unity Package CI": {
        "reason": "no Unity license secrets are configured for the runners, so the workflow cannot produce a run",
        "restore_condition": (
            "set UNITY_LICENSE (or UNITY_EMAIL + UNITY_PASSWORD + UNITY_SERIAL), restore the workflow's "
            "push/pull_request triggers, and drop this entry — see docs/operations/UNITY_PACKAGE_CI.md"
        ),
        "evidence_gap": "the shipped package carries no CI-recorded EditMode/PlayMode proof for the release SHA",
    },
}

REQUIRED_WORKFLOWS = tuple(name for name in RELEASE_GATE_WORKFLOWS if name not in WAIVED_GATES)
ACCEPTED_EVENTS = ("push", "workflow_dispatch")
API_TIMEOUT_SECONDS = 30

REMEDIATION_BY_VERDICT = {
    "failed": "Fix the workflow failure and push a corrected commit; do not tag this SHA.",
    "pending": "Wait for the run to finish (or rerun with --wait-seconds), then re-check before tagging.",
    "missing": (
        "No push/workflow_dispatch run exists for this SHA. Push the commit to master first, "
        "or trigger the workflow manually with workflow_dispatch, then re-check."
    ),
    "cannot_verify": "Gate status could not be verified; do not tag until the check succeeds.",
}


class GateQueryError(Exception):
    pass


def build_runs_url(repository: str, sha: str) -> str:
    return f"https://api.github.com/repos/{repository}/actions/runs?head_sha={sha}&per_page=100"


def build_request_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "xuunity-mcp-release-gate",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def default_fetcher(repository: str, sha: str, token: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(build_runs_url(repository, sha), headers=build_request_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        hint = " (rate-limited or forbidden; set GITHUB_TOKEN)" if error.code in (403, 429) else ""
        raise GateQueryError(f"GitHub API returned HTTP {error.code} for {repository}@{sha}{hint}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GateQueryError(f"GitHub API request failed for {repository}@{sha}: {error}") from error
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise GateQueryError(f"GitHub API returned invalid JSON for {repository}@{sha}: {error}") from error
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise GateQueryError(f"GitHub API response is missing workflow_runs for {repository}@{sha}")
    return runs


def latest_accepted_run(runs: list[dict[str, Any]], workflow_name: str) -> dict[str, Any] | None:
    candidates = [
        run
        for run in runs
        if isinstance(run, dict)
        and str(run.get("name") or "") == workflow_name
        and str(run.get("event") or "") in ACCEPTED_EVENTS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda run: int(run.get("run_number") or 0))


def gate_verdict(run: dict[str, Any] | None) -> str:
    if run is None:
        return "missing"
    if str(run.get("status") or "") != "completed":
        return "pending"
    if str(run.get("conclusion") or "") == "success":
        return "pass"
    return "failed"


def evaluate_gates(runs: list[dict[str, Any]], required_workflows: tuple[str, ...]) -> list[dict[str, Any]]:
    gates = []
    for workflow_name in required_workflows:
        run = latest_accepted_run(runs, workflow_name)
        verdict = gate_verdict(run)
        gate: dict[str, Any] = {"workflow": workflow_name, "verdict": verdict}
        if run is not None:
            gate["run_number"] = int(run.get("run_number") or 0)
            gate["event"] = str(run.get("event") or "")
            gate["status"] = str(run.get("status") or "")
            gate["conclusion"] = str(run.get("conclusion") or "")
            gate["run_url"] = str(run.get("html_url") or "")
        if verdict != "pass":
            gate["remediation"] = REMEDIATION_BY_VERDICT[verdict]
        gates.append(gate)
    return gates


def gates_blocked(gates: list[dict[str, Any]]) -> bool:
    return any(gate["verdict"] != "pass" for gate in gates)


def gates_retryable(gates: list[dict[str, Any]]) -> bool:
    return any(gate["verdict"] in ("pending", "missing") for gate in gates)


def resolve_head_sha() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    sha = (result.stdout or "").strip()
    if result.returncode != 0 or not sha:
        raise SystemExit("could not resolve HEAD; pass --sha explicitly")
    return sha


def waived_gate_records(required_workflows: tuple[str, ...]) -> list[dict[str, Any]]:
    """Suspended gates, as data the caller cannot miss.

    A waived gate is unproven, not passed. It is reported next to the evaluated gates so a green run and the
    release notes derived from it both still carry the evidence gap.
    """
    return [
        {"workflow": workflow_name, "verdict": "waived", **WAIVED_GATES[workflow_name]}
        for workflow_name in RELEASE_GATE_WORKFLOWS
        if workflow_name in WAIVED_GATES and workflow_name not in required_workflows
    ]


def check_release_ci_gates(
    repository: str,
    sha: str,
    token: str,
    required_workflows: tuple[str, ...],
    wait_seconds: float,
    poll_interval_seconds: float,
    fetcher: Callable[[str, str, str], list[dict[str, Any]]] = default_fetcher,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    deadline = clock() + max(wait_seconds, 0.0)
    waived = waived_gate_records(required_workflows)
    while True:
        try:
            runs = fetcher(repository, sha, token)
        except GateQueryError as error:
            return {
                "status": "blocked",
                "repository": repository,
                "sha": sha,
                "gates": [
                    {
                        "workflow": workflow_name,
                        "verdict": "cannot_verify",
                        "remediation": REMEDIATION_BY_VERDICT["cannot_verify"],
                    }
                    for workflow_name in required_workflows
                ],
                "waived_gates": waived,
                "error": str(error),
            }
        gates = evaluate_gates(runs, required_workflows)
        if not gates_blocked(gates):
            status = "ok_with_waived_gates" if waived else "ok"
            return {"status": status, "repository": repository, "sha": sha, "gates": gates, "waived_gates": waived}
        if not gates_retryable(gates) or clock() >= deadline:
            return {"status": "blocked", "repository": repository, "sha": sha, "gates": gates, "waived_gates": waived}
        sleeper(poll_interval_seconds)


def main(
    argv: list[str] | None = None,
    fetcher: Callable[[str, str, str], list[dict[str, Any]]] = default_fetcher,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--sha", default="", help="Commit SHA to verify. Defaults to the repo HEAD.")
    parser.add_argument(
        "--require",
        action="append",
        default=None,
        metavar="WORKFLOW_NAME",
        help="Required workflow name. Repeatable; replaces the default required set.",
    )
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    sha = args.sha or resolve_head_sha()
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    required_workflows = tuple(args.require) if args.require else REQUIRED_WORKFLOWS

    result = check_release_ci_gates(
        repository=args.repository,
        sha=sha,
        token=token,
        required_workflows=required_workflows,
        wait_seconds=args.wait_seconds,
        poll_interval_seconds=max(args.poll_interval_seconds, 1.0),
        fetcher=fetcher,
        sleeper=sleeper,
        clock=clock,
    )

    for gate in result["gates"]:
        detail = gate.get("run_url") or gate.get("remediation") or ""
        print(f"[{gate['verdict']}] {gate['workflow']} {detail}".rstrip())
    for gate in result.get("waived_gates") or []:
        print(f"[waived] {gate['workflow']} — {gate['reason']}", file=sys.stderr)
        print(f"[waived] {gate['workflow']} evidence gap: {gate['evidence_gap']}", file=sys.stderr)
        print(f"[waived] {gate['workflow']} restore: {gate['restore_condition']}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    if result["status"] == "blocked":
        print("release gate: blocked — do not push the release tag for this SHA.", file=sys.stderr)
        return 1
    if result["status"] == "ok_with_waived_gates":
        waived_names = ", ".join(gate["workflow"] for gate in result["waived_gates"])
        print(f"release gate: required workflows are green for {sha}; waived (unproven): {waived_names}.")
        return 0
    print(f"release gate: all required workflows are green for {sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
