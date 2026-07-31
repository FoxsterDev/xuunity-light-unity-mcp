from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

from server_batch_reporting import BatchProgressReporter, run_subprocess_with_progress
from server_core import ToolInvocationError, read_json
from server_editor_host import (
    build_batch_validation_command,
    clear_stale_bridge_state,
    default_batch_operation_log_path,
    default_batch_operation_result_path,
    detect_unity_app_path_for_project,
    list_live_project_editor_pids,
    process_visibility_summary,
    read_recent_editor_log,
)


PACKAGE_RESTORE_SCHEMA_VERSION = "xuunity.sdk-package-restore.v1"


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_file_hashes(project_root: Path) -> dict[str, str]:
    return {
        "manifest_sha256": _sha256(project_root / "Packages" / "manifest.json"),
        "packages_lock_sha256": _sha256(project_root / "Packages" / "packages-lock.json"),
    }


def _failure(
    *,
    project_root: Path,
    code: str,
    message: str,
    log_path: Path,
    result_path: Path,
    batch_exit_code: int | None = None,
    timed_out: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": PACKAGE_RESTORE_SCHEMA_VERSION,
        "operation": "unity.sdk.package_restore",
        "project_root": str(project_root),
        "outcome": "package_restore_failed",
        "succeeded": False,
        "decision_ready": False,
        "operator_verdict": "failed",
        "trust_class": "package_restore_unproven",
        "error_code": code,
        "top_actionable_error": message,
        "recommended_next_action": "inspect_package_restore_log_and_retry",
        "log_path": str(log_path),
        "result_file": str(result_path),
        "timed_out": bool(timed_out),
    }
    if batch_exit_code is not None:
        payload["batch_exit_code"] = int(batch_exit_code)
    if details:
        payload.update(details)
    return payload


def run_sdk_package_restore(
    *,
    project_root: Path,
    unity_app: str | Path | None = None,
    timeout_ms: int = 600000,
    stable_idle_ticks: int = 2,
    log_path: str | Path | None = None,
    result_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    project_root = project_root.expanduser().resolve()
    if stable_idle_ticks < 2 or stable_idle_ticks > 10:
        raise ToolInvocationError(
            "sdk_package_restore_stable_ticks_invalid",
            "stableIdleTicks must be between 2 and 10.",
        )
    if timeout_ms < 5000:
        raise ToolInvocationError(
            "sdk_package_restore_timeout_invalid",
            "timeoutMs must be at least 5000.",
        )

    resolved_unity_app = detect_unity_app_path_for_project(
        project_root,
        str(unity_app) if unity_app else None,
    )
    resolved_log_path = (
        Path(log_path).expanduser().resolve()
        if log_path
        else default_batch_operation_log_path(project_root, "sdk_package_restore")
    )
    resolved_result_path = (
        Path(result_path).expanduser().resolve()
        if result_path
        else default_batch_operation_result_path(project_root, "sdk_package_restore")
    )
    run_id = str(uuid.uuid4())
    command = build_batch_validation_command(
        project_root=project_root,
        unity_app=resolved_unity_app,
        log_path=resolved_log_path,
        result_path=resolved_result_path,
        action="package-restore",
        extra_args=[
            "--xuunity-package-stable-idle-ticks",
            str(stable_idle_ticks),
            "--xuunity-package-restore-run-id",
            run_id,
        ],
    )
    before_hashes = _project_file_hashes(project_root)
    base = {
        "schema_version": PACKAGE_RESTORE_SCHEMA_VERSION,
        "operation": "unity.sdk.package_restore",
        "project_root": str(project_root),
        "unity_app": str(resolved_unity_app),
        "log_path": str(resolved_log_path),
        "result_file": str(resolved_result_path),
        "timeout_ms": timeout_ms,
        "stable_idle_ticks": stable_idle_ticks,
        "run_id": run_id,
        "command": command,
        "package_files_before": before_hashes,
    }
    if dry_run:
        return {
            **base,
            "outcome": "package_restore_dry_run",
            "succeeded": False,
            "decision_ready": False,
            "operator_verdict": "not_run",
            "trust_class": "package_restore_not_run",
        }

    visibility = process_visibility_summary()
    if not bool(visibility.get("process_visibility_available")):
        raise ToolInvocationError(
            "process_visibility_restricted",
            "Closed-editor package restore requires host process visibility before launch.",
            {
                **visibility,
                "same_project_editor_closed": False,
                "recommended_next_action": "restore_host_process_visibility",
            },
        )
    live_before = list_live_project_editor_pids(project_root)
    if live_before:
        raise ToolInvocationError(
            "editor_running_package_restore_conflict",
            "Close the same-project Unity editor before running unity.sdk.package_restore.",
            {
                "live_project_editor_pids": live_before,
                "same_project_editor_closed": False,
                "recommended_next_action": "close_same_project_editor_and_retry",
            },
        )

    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_result_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path = resolved_result_path.with_name(f"{resolved_result_path.stem}_progress.jsonl")
    reporter = BatchProgressReporter(
        run_id=resolved_result_path.stem,
        operation="unity.sdk.package_restore",
        log_path=resolved_log_path,
        progress_path=progress_path,
        interval_seconds=30.0,
        stdout=False,
    )
    batch_exit_code, timed_out = run_subprocess_with_progress(
        command,
        reporter=reporter,
        timeout_ms=timeout_ms,
        last_known_output_path=str(resolved_result_path),
    )
    live_after = list_live_project_editor_pids(project_root)
    after_hashes = _project_file_hashes(project_root)
    hash_delta = {
        key.replace("_sha256", "_changed"): before_hashes.get(key) != after_hashes.get(key)
        for key in before_hashes
    }
    common = {
        **base,
        "batch_exit_code": batch_exit_code,
        "timed_out": timed_out,
        "progress_file": str(progress_path),
        "package_files_after": after_hashes,
        "package_file_changes": hash_delta,
        "same_project_editor_closed": not live_after,
        "live_project_editor_pids_after": live_after,
    }

    if timed_out:
        return {
            **_failure(
                project_root=project_root,
                code="sdk_package_restore_timeout",
                message="Unity package restore exceeded its authoritative deadline.",
                log_path=resolved_log_path,
                result_path=resolved_result_path,
                batch_exit_code=batch_exit_code,
                timed_out=True,
            ),
            **common,
        }
    if live_after:
        return {
            **_failure(
                project_root=project_root,
                code="sdk_package_restore_editor_exit_unproven",
                message="Package restore returned but the same-project Unity editor is still running.",
                log_path=resolved_log_path,
                result_path=resolved_result_path,
                batch_exit_code=batch_exit_code,
                details={"live_project_editor_pids_after": live_after},
            ),
            **common,
        }
    if not resolved_result_path.is_file():
        excerpt = "\n".join(read_recent_editor_log(resolved_log_path, 80))
        return {
            **_failure(
                project_root=project_root,
                code="sdk_package_restore_receipt_missing",
                message="Unity exited without publishing the package-restore receipt.",
                log_path=resolved_log_path,
                result_path=resolved_result_path,
                batch_exit_code=batch_exit_code,
                details={"editor_log_excerpt": excerpt[-8000:]},
            ),
            **common,
        }

    try:
        receipt = read_json(resolved_result_path)
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            **_failure(
                project_root=project_root,
                code="sdk_package_restore_receipt_invalid",
                message="Unity published a package-restore receipt that could not be parsed.",
                log_path=resolved_log_path,
                result_path=resolved_result_path,
                batch_exit_code=batch_exit_code,
                details={"receipt_error": str(exc)},
            ),
            **common,
        }
    if not isinstance(receipt, dict):
        return {
            **_failure(
                project_root=project_root,
                code="sdk_package_restore_receipt_invalid",
                message="Unity published a package-restore receipt that is not a JSON object.",
                log_path=resolved_log_path,
                result_path=resolved_result_path,
                batch_exit_code=batch_exit_code,
            ),
            **common,
        }
    receipt_identity = {
        "schema_version": receipt.get("schema_version"),
        "operation": receipt.get("operation"),
        "run_id": receipt.get("run_id"),
        "project_root": receipt.get("project_root"),
    }
    expected_identity = {
        "schema_version": PACKAGE_RESTORE_SCHEMA_VERSION,
        "operation": "unity.sdk.package_restore",
        "run_id": run_id,
        "project_root": str(project_root),
    }
    if receipt_identity != expected_identity:
        return {
            **_failure(
                project_root=project_root,
                code="sdk_package_restore_receipt_identity_mismatch",
                message="Unity's package-restore receipt does not belong to this project and run.",
                log_path=resolved_log_path,
                result_path=resolved_result_path,
                batch_exit_code=batch_exit_code,
                details={
                    "expected_receipt_identity": expected_identity,
                    "observed_receipt_identity": receipt_identity,
                },
            ),
            **common,
        }
    succeeded = bool(receipt.get("succeeded")) and bool(receipt.get("decision_ready"))
    succeeded = succeeded and batch_exit_code == 0
    clear_stale_bridge_state(project_root)
    top_actionable_error = str(receipt.get("top_actionable_error") or "")
    if not succeeded and not top_actionable_error:
        top_actionable_error = "Unity did not publish a decision-ready package restore receipt."
    return {
        **common,
        **receipt,
        "schema_version": PACKAGE_RESTORE_SCHEMA_VERSION,
        "operation": "unity.sdk.package_restore",
        "succeeded": succeeded,
        "decision_ready": succeeded,
        "outcome": "package_restore_completed" if succeeded else "package_restore_failed",
        "operator_verdict": "passed" if succeeded else "failed",
        "trust_class": "package_restore_confirmed" if succeeded else "package_restore_unproven",
        "top_actionable_error": top_actionable_error,
        "recommended_next_action": "none" if succeeded else "inspect_package_restore_log_and_retry",
    }
