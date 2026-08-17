#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from server_bridge_constants import COMPILE_RED_FAIL_FAST_OPERATIONS
from server_core import ToolInvocationError

COMPILE_GATED_PLAYMODE_ACTIONS = frozenset({"enter"})

COMPILER_DIAGNOSTICS_TRUST_CONFIRMED = "confirmed"
COMPILER_DIAGNOSTICS_TRUST_DEFERRED_DURING_PLAYMODE = "deferred_during_playmode"
COMPILER_DIAGNOSTICS_TRUST_FLAG_ONLY = "flag_only_not_verdict"

PLAYMODE_STATES_WITH_DEFERRED_RELOAD = frozenset({"playing", "paused", "transitioning"})

FLAG_ONLY_DIAGNOSTICS_NOTE = (
    "script_compilation_failed is a flag, not a verdict; the authoritative verdict is "
    "unity_project_refresh post_settle_compile."
)
DEFERRED_DIAGNOSTICS_NOTE = (
    "diagnostics were captured before the script reload that Play Mode defers, so the disk may "
    "already differ; exit Play Mode and run unity_project_refresh for the authoritative "
    "post_settle_compile."
)


def compiler_diagnostics_trust_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    effective = state or {}
    if not bool(effective.get("script_compilation_failed")) and int(effective.get("compiler_error_count") or 0) <= 0:
        return {}

    source = str(effective.get("compiler_diagnostics_source") or "")
    playmode_state = str(effective.get("playmode_state") or "")
    if source != "compilation_pipeline":
        return {
            "compiler_diagnostics_trust_class": COMPILER_DIAGNOSTICS_TRUST_FLAG_ONLY,
            "compiler_diagnostics_note": FLAG_ONLY_DIAGNOSTICS_NOTE,
        }
    if playmode_state in PLAYMODE_STATES_WITH_DEFERRED_RELOAD:
        return {
            "compiler_diagnostics_trust_class": COMPILER_DIAGNOSTICS_TRUST_DEFERRED_DURING_PLAYMODE,
            "compiler_diagnostics_note": DEFERRED_DIAGNOSTICS_NOTE,
        }
    return {"compiler_diagnostics_trust_class": COMPILER_DIAGNOSTICS_TRUST_CONFIRMED}


def compiler_diagnostics_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    effective = state or {}
    diagnostics = effective.get("recent_compiler_diagnostics")
    if not isinstance(diagnostics, list):
        diagnostics = []
    result = {
        "script_compilation_failed": bool(effective.get("script_compilation_failed")),
        "compiler_error_count": max(0, int(effective.get("compiler_error_count") or 0)),
        "recent_compiler_diagnostics": diagnostics[:5],
        "compiler_diagnostics_source": str(effective.get("compiler_diagnostics_source") or ""),
    }
    result.update(compiler_diagnostics_trust_from_state(effective))
    return result


def fail_if_compile_broken_for_operation(
    project_root: Path,
    operation: str,
    state: dict[str, Any] | None,
    arguments: dict[str, Any] | None = None,
) -> None:
    if operation not in COMPILE_RED_FAIL_FAST_OPERATIONS:
        return

    if operation == "unity.playmode.set":
        action = str((arguments or {}).get("action") or "").strip().lower()
        if action not in COMPILE_GATED_PLAYMODE_ACTIONS:
            return

    diagnostics = compiler_diagnostics_from_state(state)
    if not diagnostics["script_compilation_failed"] and diagnostics["compiler_error_count"] <= 0:
        return

    raise ToolInvocationError(
        "compile_broken",
        f"Unity has compilation errors; refusing to start {operation} before they are fixed.",
        {
            "project_root": str(project_root),
            "operation": operation,
            **diagnostics,
            "recommended_next_action": "run_compile_gate_and_fix_errors",
        },
    )
