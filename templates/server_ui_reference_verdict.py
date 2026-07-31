from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from server_artifact_registry import register_artifact, repo_relative_path
from server_core import write_json
from server_ui_device_lane import device_lane_state, device_lane_warnings
from server_ui_fixture import fixture_next_actions
from server_ui_interaction import interaction_next_actions
from server_ui_reference_artifacts import COMPARISON_SCHEMA_VERSION
from server_ui_vision_review import analyze_lane_disagreement, vision_next_actions


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
            # False, not None: a region that could not be compared has not passed, and a None
            # reads as a pass to any caller testing `is not False`.
            region["passed"] = False
            region["not_comparable"] = True
            failures.append(
                f"Region '{region_id}' has no comparable cells after masking, so it carries no evidence."
                if not region["required"]
                else f"Required region '{region_id}' has no comparable cells after masking."
            )
            first_failed = first_failed or region_id
            continue

        similarity_passed = float(region["similarity_score"]) >= region_minimum
        layout = region.get("layout") or {}
        layout_passed = bool(layout.get("passed", True))
        coverage = region.get("content_coverage") or {}
        coverage_passed = bool(coverage.get("passed", True))
        region["passed"] = similarity_passed and layout_passed and coverage_passed
        if region["passed"] or not region["required"]:
            continue

        first_failed = first_failed or region_id
        if not coverage_passed:
            failures.append(
                f"Required region '{region_id}' renders only "
                f"{float(coverage['coverage_ratio']):.1%} of the content the reference shows there "
                f"(minimum {float(coverage['threshold']):.0%}): "
                f"{int(coverage['rendered_content_cells'])} of "
                f"{int(coverage['expected_content_cells'])} content cells. An element the reference "
                "shows is missing or blank, which a whole-screen similarity score dilutes away."
            )
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
    semantic = dict(result.get("semantic_lane") or {})
    capture_lane = str(result.get("capture_lane") or "game_view")
    device_context = dict(result.get("device_context") or {})
    lanes = {
        "visual": {
            "requirement": str(acceptance_policy.get("visual") or "required"),
            "status": visual_verdict,
            "evidence": "resolution_independent_similarity_comparison",
            "capture_lane": capture_lane,
        },
        "semantic": {
            "requirement": str(acceptance_policy.get("semantic") or "required"),
            "status": str(semantic.get("status") or "not_evaluated"),
            "evidence": str(semantic.get("evidence") or "no_semantic_ui_tree_supplied"),
            "checked": int(semantic.get("checked") or 0),
            "failures": list(semantic.get("failures") or []),
        },
        "interaction": _lane_with_requirement(
            result.get("interaction_lane"),
            requirement=str(acceptance_policy.get("interaction") or "required"),
            fallback_evidence="no_interaction_evidence_supplied",
        ),
        "vision": _lane_with_requirement(
            result.get("vision_lane"),
            requirement=str(acceptance_policy.get("vision") or "optional"),
            fallback_evidence="no_vision_review_supplied",
        ),
        "device": device_lane_state(
            capture_lane=capture_lane,
            acceptance_policy=acceptance_policy,
            device_context=device_context,
            capture_size=dict(result.get("actual_image") or {}),
        ),
    }
    result["acceptance_lanes"] = lanes

    owner = str(result.get("owner") or "agent")
    pending_lanes = [
        lane
        for lane, state in lanes.items()
        if lane != "visual" and state["requirement"] == "required" and state["status"] == "not_evaluated"
    ]
    # An optional lane may be skipped, but a lane that was actually run and failed is a real
    # failure; only not_required opts out of the verdict entirely.
    failed_lanes = [
        lane
        for lane, state in lanes.items()
        if lane != "visual" and state["requirement"] != "not_required" and state["status"] == "failed"
    ]
    blocked_lanes = [
        lane
        for lane, state in lanes.items()
        if lane != "visual" and state["requirement"] != "not_required" and state["status"] == "blocked"
    ]

    result["lane_disagreement"] = analyze_lane_disagreement(
        visual_verdict=visual_verdict,
        vision_lane=lanes["vision"],
        global_metrics=dict(result.get("global") or {}),
        tolerances=dict(result.get("tolerances") or {}),
    )

    if visual_verdict == "blocked":
        acceptance = "blocked"
    elif visual_verdict == "failed" or failed_lanes:
        acceptance = "failed"
    elif blocked_lanes:
        acceptance = "blocked"
        result["blocked_reason"] = result.get("blocked_reason") or "required_lane_blocked"
    elif owner == "human":
        acceptance = "pending_manual_style"
    elif pending_lanes:
        acceptance = "pending_lanes"
    else:
        acceptance = "passed"

    result["failed_lanes"] = failed_lanes
    result["blocked_lanes"] = blocked_lanes
    if failed_lanes and visual_verdict != "failed":
        result["failure_reasons"].extend(_lane_failure_reasons(lanes, failed_lanes))
    if blocked_lanes:
        for lane in blocked_lanes:
            result["failure_reasons"].append(
                f"The {lane} lane could not decide: {lanes[lane].get('blocked_reason') or 'blocked'}."
            )
    result["warnings"].extend(
        device_lane_warnings(capture_lane=capture_lane, device_context=device_context)
    )
    result["warnings"].extend(_vision_warnings(lanes["vision"], result["lane_disagreement"]))

    result["reference_acceptance"] = acceptance
    result["pending_lanes"] = pending_lanes

    readiness_gaps: list[str] = []
    stability_status = str((result.get("capture_stability") or {}).get("status") or "unproven")
    if stability_status != "proven":
        readiness_gaps.append(f"capture_stability_{stability_status}")
    fixture = dict(result.get("fixture") or {})
    if not str(fixture.get("declared_fixture") or ""):
        readiness_gaps.append("fixture_undeclared")
    readiness_gaps.extend(f"fixture_{code}" for code in list(fixture.get("determinism_gaps") or []))
    if visual_verdict == "blocked":
        readiness_gaps.append("visual_lane_blocked")
    readiness_gaps.extend(f"{lane}_lane_blocked" for lane in blocked_lanes)
    if lanes["vision"].get("self_reviewed_only"):
        readiness_gaps.append("vision_self_reviewed_only")
    result["decision_ready"] = not readiness_gaps
    result["decision_readiness_gaps"] = readiness_gaps
    if fixture.get("visual_determinism") == "unproven":
        result["warnings"].append(
            {
                "code": "visual_determinism_unproven",
                "message": (
                    "The captured UI state is not proven reproducible: "
                    + "; ".join(str(item) for item in list(fixture.get("messages") or [])[:3])
                ),
            }
        )

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


def _lane_with_requirement(
    lane: dict[str, Any] | None,
    *,
    requirement: str,
    fallback_evidence: str,
) -> dict[str, Any]:
    if not lane:
        return {"requirement": requirement, "status": "not_evaluated", "evidence": fallback_evidence}
    return {**lane, "requirement": requirement}


def _lane_failure_reasons(lanes: dict[str, Any], failed_lanes: list[str]) -> list[str]:
    reasons: list[str] = []
    if "semantic" in failed_lanes:
        for failure in lanes["semantic"].get("failures") or []:
            reasons.append(
                f"Required UI '{failure.get('id')}' failed the semantic lane as {failure.get('code')}."
            )
    if "interaction" in failed_lanes:
        for failure in lanes["interaction"].get("failures") or []:
            reasons.append(
                f"Required interaction '{failure.get('id')}' failed: {failure.get('message')}"
            )
    if "vision" in failed_lanes:
        for entry in list(lanes["vision"].get("worst_criteria") or [])[:3]:
            reasons.append(
                f"The review scored {entry.get('criterion')} as {entry.get('name')}: {entry.get('observation')}"
            )
    return reasons


def _vision_warnings(lane: dict[str, Any], disagreement: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if lane.get("status") in ("passed", "failed") and lane.get("self_reviewed_only"):
        warnings.append(
            {
                "code": "vision_review_self_reviewed_only",
                "message": (
                    "Every vision judgement came from the agent that authored the UI. It is recorded "
                    "as an attested judgement, never as independent proof."
                ),
            }
        )
    if lane.get("status") in ("passed", "failed") and not lane.get("unanimous", True):
        warnings.append(
            {
                "code": "vision_judges_disagreed",
                "message": "Judges disagreed on whether this is recognisably the same screen.",
            }
        )
    if disagreement.get("disagree"):
        warnings.append(
            {"code": str(disagreement["code"]), "message": str(disagreement["message"])}
        )
    return warnings


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
        actions.extend(_semantic_explanation_actions(result, first_failed))
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

    disagreement = dict(result.get("lane_disagreement") or {})
    if disagreement.get("disagree"):
        actions.append(str(disagreement.get("message") or ""))
        suggestion = dict(disagreement.get("suggestion") or {})
        if suggestion.get("would_pass_global"):
            actions.append(
                f"If the review is right, the '{suggestion['tolerance_profile']}' profile "
                f"({float(suggestion['candidate_global_min_similarity']):.0%} global minimum) matches the "
                f"observed {float(suggestion['observed_global_similarity']):.1%}; change it on the "
                "reference deliberately rather than per comparison."
            )

    lanes = dict(result.get("acceptance_lanes") or {})
    actions.extend(interaction_next_actions(dict(lanes.get("interaction") or {})))
    actions.extend(vision_next_actions(dict(lanes.get("vision") or {})))
    actions.extend(fixture_next_actions(dict(result.get("fixture") or {})))
    return [action for action in actions if action]


def _semantic_explanation_actions(result: dict[str, Any], first_failed: str) -> list[str]:
    explanations = dict(result.get("semantic_explanations") or {})
    if not explanations.get("available"):
        return [
            "A similarity score cannot say why a region failed; pass uiSnapshotPath from "
            "unity_ui_tree_snapshot so failed regions are mapped to the nodes that cover them."
        ]

    per_region = dict(explanations.get("regions") or {})
    explanation = per_region.get(first_failed) or next(iter(per_region.values()), {})
    summary = str(explanation.get("summary") or "")
    actions: list[str] = []
    if summary:
        actions.append(summary)
    likely_node = str(explanation.get("likely_cause_node") or "")
    if likely_node:
        actions.append(
            f"Inspect '{likely_node}' with unity_ui_query before changing the reference or the tolerance."
        )
    return actions
