from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from server_artifact_registry import register_artifact, repo_relative_path
from server_core import write_json
from server_ui_reference_artifacts import COMPARISON_SCHEMA_VERSION


def score_visual_verdict(
    *,
    global_metrics: dict[str, Any],
    regions: list[dict[str, Any]],
    tolerances: dict[str, float],
) -> tuple[str, list[str], str]:
    region_minimum = float(tolerances["region_min_similarity"])
    failures: list[str] = []
    first_failed = ""

    for region in regions:
        region_id = str(region["region_id"])
        if not region["comparable"]:
            region["passed"] = None
            if region["required"]:
                failures.append(f"Required region '{region_id}' has no comparable cells after masking.")
                first_failed = first_failed or region_id
            continue

        similarity_passed = float(region["similarity_score"]) >= region_minimum
        layout = region.get("layout") or {}
        layout_passed = bool(layout.get("passed", True))
        region["passed"] = similarity_passed and layout_passed
        if region["passed"] or not region["required"]:
            continue

        first_failed = first_failed or region_id
        if not similarity_passed:
            weakest = "colour" if region["color_score"] <= region["structure_score"] else "detail/structure"
            failures.append(
                f"Required region '{region_id}' is {float(region['similarity_score']):.1%} similar "
                f"(minimum {region_minimum:.0%}); the weakest signal is {weakest} "
                f"(colour {float(region['color_score']):.1%}, structure {float(region['structure_score']):.1%})."
            )
        if not layout_passed:
            failures.append(_layout_failure_message(region_id, layout))

    global_minimum = float(tolerances["global_min_similarity"])
    if not global_metrics["passed"]:
        score = global_metrics.get("similarity_score")
        score_text = "unavailable" if score is None else f"{float(score):.1%}"
        failures.append(f"Whole-screen similarity {score_text} is below the {global_minimum:.0%} minimum.")

    weighted = _weighted_region_similarity(regions)
    if weighted is not None:
        global_metrics["weighted_region_similarity"] = weighted

    return ("failed" if failures else "passed"), failures, first_failed


def _layout_failure_message(region_id: str, layout: dict[str, Any]) -> str:
    reason = str(layout.get("reason") or "")
    if reason == "content_missing":
        return f"Required region '{region_id}' renders no content where the reference has content."
    if reason == "unexpected_content":
        return f"Required region '{region_id}' renders content where the reference is empty."
    return (
        f"Required region '{region_id}' content is shifted "
        f"({float(layout.get('offset_x_ratio', 0.0)):+.1%} x, {float(layout.get('offset_y_ratio', 0.0)):+.1%} y) "
        f"and sized {float(layout.get('width_ratio', 1.0)):.2f}x by "
        f"{float(layout.get('height_ratio', 1.0)):.2f}y versus the reference."
    )


def _weighted_region_similarity(regions: list[dict[str, Any]]) -> float | None:
    total_weight = 0.0
    total = 0.0
    for region in regions:
        if not region["comparable"] or region.get("similarity_score") is None:
            continue
        weight = float(region.get("weight") or 1.0)
        total_weight += weight
        total += weight * float(region["similarity_score"])
    if total_weight <= 0:
        return None
    return round(total / total_weight, 6)


def finalize_comparison(
    result: dict[str, Any],
    *,
    project_root: Path,
    workspace: Path,
    reference_dir: Path,
    manifest: dict[str, Any],
    blocked_reason: str,
    blocked_message: str,
    register_in_artifact_registry: bool,
    emit_artifacts: bool,
) -> dict[str, Any]:
    if blocked_reason:
        result["visual_verdict"] = "blocked"
        result["blocked_reason"] = blocked_reason
        result["failure_reasons"] = [blocked_message] if blocked_message else []
        result.setdefault("artifacts", [])

    visual_verdict = str(result.get("visual_verdict") or "blocked")
    acceptance_policy = dict(manifest.get("acceptance") or {})
    lanes = {
        "visual": {
            "requirement": str(acceptance_policy.get("visual") or "required"),
            "status": visual_verdict,
            "evidence": "resolution_independent_similarity_comparison",
        },
        "semantic": {
            "requirement": str(acceptance_policy.get("semantic") or "required"),
            "status": "not_evaluated",
            "evidence": "no_semantic_ui_tree_in_this_slice",
        },
        "interaction": {
            "requirement": str(acceptance_policy.get("interaction") or "required"),
            "status": "not_evaluated",
            "evidence": "no_guarded_ui_interaction_in_this_slice",
        },
    }
    result["acceptance_lanes"] = lanes

    owner = str(result.get("owner") or "agent")
    pending_lanes = [
        lane
        for lane, state in lanes.items()
        if lane != "visual" and state["requirement"] == "required" and state["status"] == "not_evaluated"
    ]

    if visual_verdict == "blocked":
        acceptance = "blocked"
    elif visual_verdict == "failed":
        acceptance = "failed"
    elif owner == "human":
        acceptance = "pending_manual_style"
    elif pending_lanes:
        acceptance = "pending_lanes"
    else:
        acceptance = "passed"

    result["reference_acceptance"] = acceptance
    result["pending_lanes"] = pending_lanes

    readiness_gaps: list[str] = []
    stability_status = str((result.get("capture_stability") or {}).get("status") or "unproven")
    if stability_status != "proven":
        readiness_gaps.append(f"capture_stability_{stability_status}")
    if not str((result.get("fixture") or {}).get("declared") or ""):
        readiness_gaps.append("fixture_undeclared")
    elif not bool((result.get("fixture") or {}).get("established")):
        readiness_gaps.append("fixture_establishment_unreported")
    if acceptance == "blocked":
        readiness_gaps.append("visual_lane_blocked")
    result["decision_ready"] = not readiness_gaps
    result["decision_readiness_gaps"] = readiness_gaps

    if owner == "human":
        result["warnings"].append(
            {
                "code": "visual_owner_human",
                "message": (
                    "Visual styling is owned by a human for this reference; a passing similarity "
                    "comparison is a handoff status, never reference acceptance."
                ),
            }
        )
    if stability_status == "waived":
        result["warnings"].append(
            {
                "code": "capture_stability_waived",
                "message": str((result.get("capture_stability") or {}).get("message") or ""),
            }
        )
    comparability = result.get("comparability") or {}
    if comparability.get("comparable") and not comparability.get("same_resolution"):
        result["warnings"].append(
            {
                "code": "capture_rescaled_for_comparison",
                "message": (
                    f"Capture is {comparability['actual_viewport']['width']}x"
                    f"{comparability['actual_viewport']['height']} against a "
                    f"{comparability['declared_viewport']['width']}x"
                    f"{comparability['declared_viewport']['height']} reference; comparison ran on the "
                    "shared cell grid, so fine typography differences are outside its resolving power."
                ),
            }
        )

    result["next_actions"] = _next_actions(result)
    result["succeeded"] = acceptance == "passed"

    if emit_artifacts:
        verdict_path = reference_dir / "comparisons" / str(result["comparison_id"]) / "verdict.json"
        write_json(verdict_path, result)
        result.setdefault("artifacts", []).append(
            {
                "role": "verdict",
                "path": str(verdict_path),
                "repo_relative_path": repo_relative_path(verdict_path, workspace),
                "sha256": hashlib.sha256(verdict_path.read_bytes()).hexdigest(),
                "size_bytes": verdict_path.stat().st_size,
            }
        )
        if register_in_artifact_registry:
            record = register_artifact(
                project_root=project_root,
                artifact_path=str(verdict_path),
                destination="repo_artifact",
                kind="ui_reference_comparison",
                producer="xuunity_ui_reference_compare",
                artifact_schema_version=COMPARISON_SCHEMA_VERSION,
                metadata={
                    "reference_id": result.get("reference_id", ""),
                    "comparison_id": result.get("comparison_id", ""),
                    "reference_acceptance": acceptance,
                    "visual_verdict": visual_verdict,
                    "decision_ready": result["decision_ready"],
                },
                workspace_root=str(workspace),
            )
            result["artifact_registry_path"] = record.get("registry_path", "")

    return result


def _next_actions(result: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    acceptance = str(result.get("reference_acceptance") or "")
    blocked_reason = str(result.get("blocked_reason") or "")
    comparability = result.get("comparability") or {}
    stability_status = str((result.get("capture_stability") or {}).get("status") or "")

    if blocked_reason == "comparison_not_comparable":
        declared = comparability.get("declared_viewport") or {}
        recommended = result.get("recommended_capture_resolutions") or []
        options = ", ".join(f"{item['width']}x{item['height']}" for item in recommended[:4])
        actions.append(
            "Set the Game View to a same-aspect resolution before comparing"
            + (f" (for example {options})." if options else f" ({declared.get('width')}x{declared.get('height')}).")
        )
    if blocked_reason == "reference_manifest_invalid":
        actions.append("Fix the manifest errors and re-register the reference before comparing.")
    if stability_status == "unproven":
        actions.append("Capture the same frozen fixture twice and pass the second capture as stabilityImage.")
    if stability_status == "unstable":
        actions.append(
            "Freeze the clock, timers, and network payload for this UI state; the screen is still moving."
        )
    if acceptance == "failed":
        first_failed = str(result.get("first_failed_region") or "")
        if first_failed:
            actions.append(f"Inspect region '{first_failed}' in diff.png and overlay.png first.")
        actions.append(
            "A similarity score cannot say why a region failed; use semantic UI inspection once available."
        )
        actions.append(
            "If the difference is intended styling latitude, widen the tolerance profile deliberately "
            "instead of ignoring the verdict."
        )
    if acceptance == "pending_lanes":
        actions.append(
            "Visual similarity passed but required semantic/interaction lanes are unevaluated; do not "
            "report the reference as implemented."
        )
    if acceptance == "pending_manual_style":
        actions.append(
            "Record which regions remain human-owned; reference acceptance stays pending manual styling."
        )
    return actions
