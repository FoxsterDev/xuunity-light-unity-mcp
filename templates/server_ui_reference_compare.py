from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from server_artifact_registry import resolve_workspace_root
from server_core import ToolInvocationError
from server_ui_reference_manifest import (
    DEFAULT_REFERENCE_CATEGORY,
    DEFAULT_TOLERANCE_PROFILE,
    Rect,
    UI_REFERENCE_SCHEMA_VERSION,
    clip_rect,
    derive_orientation,
    manifest_rects,
    resolve_tolerances,
    utc_now,
)
from server_ui_reference_artifacts import (
    COMPARISON_SCHEMA_VERSION,
    emit_comparison_artifacts,
)
from server_ui_reference_verdict import finalize_comparison, score_visual_verdict
from server_ui_reference_policy import validate_manifest
from server_ui_reference_png import RgbaImage, read_png
from server_ui_reference_registry import load_ui_reference, recommended_capture_resolutions
from server_ui_reference_similarity import (
    build_cell_grid,
    cluster_mismatch_cells,
    compare_layout,
    compare_region,
    grid_rect,
    measure_pixel_lane,
)



def compare_ui_reference(
    *,
    project_root: Path,
    actual_image: str,
    reference_id: str = "",
    manifest_path: str = "",
    stability_image: str = "",
    require_capture_stability: bool = True,
    emit_artifacts: bool = True,
    include_expected_copy: bool = False,
    comparison_id: str = "",
    fixture_evidence: dict[str, Any] | None = None,
    tolerance_profile: str = "",
    category: str = DEFAULT_REFERENCE_CATEGORY,
    workspace_root: str = "",
    register_in_artifact_registry: bool = True,
) -> dict[str, Any]:
    workspace = resolve_workspace_root(project_root, workspace_root)
    loaded = load_ui_reference(
        project_root=project_root,
        reference_id=reference_id,
        manifest_path=manifest_path,
        category=category,
        workspace_root=str(workspace),
    )
    manifest = loaded["manifest"]
    if tolerance_profile.strip():
        manifest = dict(manifest)
        manifest["tolerance_profile"] = tolerance_profile.strip().lower()
    reference_dir = Path(loaded["reference_dir"])
    validation = validate_manifest(manifest, reference_dir=reference_dir)

    result = _new_result(
        manifest=manifest,
        manifest_path=loaded["manifest_path"],
        comparison_id=comparison_id,
        fixture_evidence=fixture_evidence,
    )
    result["manifest_validation"] = {
        "valid": validation["valid"],
        "errors": validation["errors"],
        "warnings": validation["warnings"],
    }
    result["mask_audit"] = validation["mask_audit"]

    if not validation["valid"]:
        return finalize_comparison(
            result,
            project_root=project_root,
            workspace=workspace,
            reference_dir=reference_dir,
            manifest=manifest,
            blocked_reason="reference_manifest_invalid",
            blocked_message="The reference manifest failed validation, so no comparison score was computed.",
            register_in_artifact_registry=register_in_artifact_registry,
            emit_artifacts=emit_artifacts,
        )

    actual_path = _resolve_input_path(actual_image, workspace, "actualImage")
    expected_path = reference_dir / str(
        (manifest.get("expected_image") or {}).get("file_name") or "expected.png"
    )
    expected = read_png(expected_path, source="expected")
    actual = read_png(actual_path, source="actual")
    result["actual_image"] = _image_record(actual_path, actual)
    result["expected_image"] = _image_record(expected_path, expected)

    tolerances = resolve_tolerances(manifest)
    result["tolerance_profile"] = str(manifest.get("tolerance_profile") or DEFAULT_TOLERANCE_PROFILE)
    result["tolerances"] = tolerances

    viewport = manifest.get("viewport") or {}
    scale_policy = str(manifest.get("scale_policy") or "aspect_scale").strip().lower()
    comparability = _check_comparability(
        expected=expected,
        actual=actual,
        viewport=viewport,
        scale_policy=scale_policy,
        aspect_tolerance=float(tolerances["aspect_tolerance"]),
    )
    result["comparability"] = comparability
    if not comparability["comparable"]:
        result["recommended_capture_resolutions"] = recommended_capture_resolutions(viewport)
        return finalize_comparison(
            result,
            project_root=project_root,
            workspace=workspace,
            reference_dir=reference_dir,
            manifest=manifest,
            blocked_reason="comparison_not_comparable",
            blocked_message=comparability["message"],
            register_in_artifact_registry=register_in_artifact_registry,
            emit_artifacts=emit_artifacts,
        )

    regions, masks = manifest_rects(manifest)
    reference_width = int(viewport.get("width") or expected.width)
    reference_height = int(viewport.get("height") or expected.height)
    columns = max(8, min(512, int(tolerances["comparison_grid_width"]), reference_width))
    rows = max(8, min(round(columns * reference_height / max(1, reference_width)), reference_height))

    expected_grid = build_cell_grid(expected, columns=columns, rows=rows)
    actual_grid = build_cell_grid(actual, columns=columns, rows=rows)
    result["comparison_space"] = {
        **expected_grid.describe(),
        "mode": "resolution_independent_cell_grid",
        "reference_pixels_per_cell_x": round(reference_width / columns, 2),
        "reference_pixels_per_cell_y": round(reference_height / rows, 2),
        "actual_pixels_per_cell_x": round(actual.width / columns, 2),
        "actual_pixels_per_cell_y": round(actual.height / rows, 2),
    }

    mask_cells = [
        grid_rect(
            clip_rect(mask, Rect(0, 0, reference_width, reference_height)),
            reference_width=reference_width,
            reference_height=reference_height,
            columns=columns,
            rows=rows,
        )
        for mask in masks
        if clip_rect(mask, Rect(0, 0, reference_width, reference_height)).area > 0
    ]

    stability = _evaluate_stability(
        actual=actual,
        actual_grid=actual_grid,
        stability_image=stability_image,
        workspace=workspace,
        columns=columns,
        rows=rows,
        mask_cells=mask_cells,
        tolerances=tolerances,
        require_capture_stability=require_capture_stability,
    )
    result["capture_stability"] = stability

    full_rect = Rect(0, 0, columns, rows)
    global_metrics = compare_region(
        expected_grid,
        actual_grid,
        rect=full_rect,
        mask_rects=mask_cells,
        tolerances=tolerances,
    )
    global_metrics.pop("mismatch_cells", None)
    global_metrics["threshold"] = float(tolerances["global_min_similarity"])
    global_metrics["passed"] = (
        global_metrics["comparable"]
        and float(global_metrics["similarity_score"]) >= float(tolerances["global_min_similarity"])
    )
    result["global"] = global_metrics

    region_results: list[dict[str, Any]] = []
    mismatch_cells: set[tuple[int, int]] = set()
    for region_id, rect, required, weight in regions:
        clipped = clip_rect(rect, Rect(0, 0, reference_width, reference_height))
        cell_rect = grid_rect(
            clipped,
            reference_width=reference_width,
            reference_height=reference_height,
            columns=columns,
            rows=rows,
        )
        metrics = compare_region(
            expected_grid,
            actual_grid,
            rect=cell_rect,
            mask_rects=mask_cells,
            tolerances=tolerances,
        )
        cells = metrics.pop("mismatch_cells", [])
        mismatch_cells.update(cells)
        layout = compare_layout(
            expected_grid,
            actual_grid,
            rect=cell_rect,
            mask_rects=mask_cells,
            tolerances=tolerances,
        )
        metrics.update(
            {
                "region_id": region_id,
                "rect": clipped.to_mapping(),
                "cell_rect": cell_rect.to_mapping(),
                "required": required,
                "weight": weight,
                "threshold": float(tolerances["region_min_similarity"]),
                "layout": layout,
            }
        )
        region_results.append(metrics)

    result["regions"] = region_results
    result["mismatch_clusters"] = cluster_mismatch_cells(
        mismatch_cells,
        regions=region_results,
        grid_columns=columns,
        grid_rows=rows,
        reference_width=reference_width,
        reference_height=reference_height,
    )

    if (expected.width, expected.height) == (actual.width, actual.height):
        result["pixel_diagnostics"] = {
            "available": True,
            "note": "Supporting evidence only; acceptance is decided on the comparison grid.",
            **measure_pixel_lane(
                expected=expected,
                actual=actual,
                bounds=Rect(0, 0, expected.width, expected.height),
                masks=[clip_rect(mask, Rect(0, 0, expected.width, expected.height)) for mask in masks],
                max_channel_delta=int(tolerances["max_channel_delta"]),
            ),
        }
    else:
        result["pixel_diagnostics"] = {
            "available": False,
            "reason": "capture_resolution_differs_from_reference",
        }

    visual_verdict, failure_reasons, first_failed_region = score_visual_verdict(
        global_metrics=global_metrics,
        regions=region_results,
        tolerances=tolerances,
    )
    if stability["status"] == "unstable":
        visual_verdict = "blocked"
        failure_reasons.insert(0, stability["message"])
    elif stability["status"] == "unproven" and visual_verdict == "passed":
        visual_verdict = "blocked"
        failure_reasons.insert(0, stability["message"])

    result["visual_verdict"] = visual_verdict
    result["failure_reasons"] = failure_reasons
    result["first_failed_region"] = first_failed_region

    if emit_artifacts:
        result["artifacts"] = emit_comparison_artifacts(
            reference_dir=reference_dir,
            workspace=workspace,
            comparison_id=str(result["comparison_id"]),
            expected=expected,
            expected_source=expected_path,
            actual=actual,
            actual_source=actual_path,
            expected_grid=expected_grid,
            actual_grid=actual_grid,
            mismatch_cells=mismatch_cells,
            mask_cells=mask_cells,
            regions=region_results,
            comparison_space=result["comparison_space"],
            global_metrics=global_metrics,
            clusters=result["mismatch_clusters"],
            include_expected_copy=include_expected_copy,
        )
    else:
        result["artifacts"] = []
        result["artifacts_omitted"] = True

    return finalize_comparison(
        result,
        project_root=project_root,
        workspace=workspace,
        reference_dir=reference_dir,
        manifest=manifest,
        blocked_reason="",
        blocked_message="",
        register_in_artifact_registry=register_in_artifact_registry,
        emit_artifacts=emit_artifacts,
    )


def _new_result(
    *,
    manifest: dict[str, Any],
    manifest_path: str,
    comparison_id: str,
    fixture_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = dict(fixture_evidence or {})
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "reference_schema_version": UI_REFERENCE_SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "comparison_id": comparison_id.strip() or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "reference_id": str(manifest.get("reference_id") or ""),
        "manifest_path": manifest_path,
        "proof_class": "visual_only",
        "fixture": {
            "declared": str(manifest.get("fixture") or ""),
            "reported": str(evidence.get("fixture") or ""),
            "data_source": str(evidence.get("data_source") or ""),
            "clock_frozen": bool(evidence.get("clock_frozen", False)),
            "locale": str(evidence.get("locale") or ""),
            "established": bool(evidence.get("established", False)),
        },
        "owner": str(manifest.get("owner") or "agent"),
        "acceptance_policy": dict(manifest.get("acceptance") or {}),
        "warnings": [],
    }


def _resolve_input_path(value: str, workspace: Path, argument_name: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ToolInvocationError(
            "ui_reference_actual_capture_missing",
            f"{argument_name} is required.",
            {"argument": argument_name},
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (workspace / path).resolve()
    if not path.is_file():
        raise ToolInvocationError(
            "ui_reference_actual_capture_missing",
            f"Capture '{path}' was not found.",
            {"argument": argument_name, "path": str(path)},
        )
    return path


def _image_record(path: Path, image: RgbaImage) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "width": image.width,
        "height": image.height,
    }


def _check_comparability(
    *,
    expected: RgbaImage,
    actual: RgbaImage,
    viewport: dict[str, Any],
    scale_policy: str,
    aspect_tolerance: float,
) -> dict[str, Any]:
    declared_width = int(viewport.get("width") or expected.width)
    declared_height = int(viewport.get("height") or expected.height)
    declared_orientation = str(viewport.get("orientation") or derive_orientation(declared_width, declared_height))
    actual_orientation = derive_orientation(actual.width, actual.height)
    declared_aspect = declared_width / declared_height
    actual_aspect = actual.width / actual.height
    aspect_drift = abs(actual_aspect - declared_aspect) / declared_aspect
    scale = round(actual.width / declared_width, 4)

    base = {
        "scale_policy": scale_policy,
        "declared_viewport": {"width": declared_width, "height": declared_height},
        "actual_viewport": {"width": actual.width, "height": actual.height},
        "declared_orientation": declared_orientation,
        "actual_orientation": actual_orientation,
        "declared_aspect": round(declared_aspect, 5),
        "actual_aspect": round(actual_aspect, 5),
        "aspect_drift": round(aspect_drift, 5),
        "aspect_tolerance": aspect_tolerance,
        "capture_scale": scale,
        "same_resolution": (actual.width, actual.height) == (declared_width, declared_height),
    }

    if scale_policy == "strict" and not base["same_resolution"]:
        return {
            **base,
            "comparable": False,
            "reason": "resolution_mismatch_under_strict_policy",
            "message": (
                f"Capture is {actual.width}x{actual.height} but the reference declares "
                f"{declared_width}x{declared_height} and its scale policy is 'strict'."
            ),
        }

    if actual_orientation != declared_orientation:
        return {
            **base,
            "comparable": False,
            "reason": "orientation_mismatch",
            "message": (
                f"Capture orientation '{actual_orientation}' does not match the declared "
                f"'{declared_orientation}' orientation."
            ),
        }

    if scale_policy != "stretch" and aspect_drift > aspect_tolerance:
        return {
            **base,
            "comparable": False,
            "reason": "aspect_mismatch",
            "message": (
                f"Capture aspect {actual.width}:{actual.height} differs from the reference aspect "
                f"{declared_width}:{declared_height} by {aspect_drift:.1%}, above the "
                f"{aspect_tolerance:.1%} tolerance. Set the Game View to a same-aspect resolution or "
                "declare scale_policy='stretch' deliberately."
            ),
        }

    return {
        **base,
        "comparable": True,
        "reason": "",
        "message": "",
        "normalization": "resolution_independent_cell_grid",
    }


def _evaluate_stability(
    *,
    actual: RgbaImage,
    actual_grid,
    stability_image: str,
    workspace: Path,
    columns: int,
    rows: int,
    mask_cells: list[Rect],
    tolerances: dict[str, float],
    require_capture_stability: bool,
) -> dict[str, Any]:
    if not str(stability_image or "").strip():
        if require_capture_stability:
            return {
                "status": "unproven",
                "policy": "required",
                "message": (
                    "Capture stability is unproven: no second capture of the same frozen fixture was "
                    "supplied, so a passing comparison cannot be shown to be reproducible."
                ),
            }
        return {
            "status": "waived",
            "policy": "waived_by_caller",
            "message": "Capture stability was not required by the caller; this verdict is not durable evidence.",
        }

    second_path = _resolve_input_path(stability_image, workspace, "stabilityImage")
    second = read_png(second_path, source="stability")
    if (second.width, second.height) != (actual.width, actual.height):
        return {
            "status": "unstable",
            "policy": "required" if require_capture_stability else "waived_by_caller",
            "message": (
                f"Stability capture is {second.width}x{second.height} but the actual capture is "
                f"{actual.width}x{actual.height}; the two captures are not comparable."
            ),
            "stability_capture_path": str(second_path),
        }

    second_grid = build_cell_grid(second, columns=columns, rows=rows)
    metrics = compare_region(
        actual_grid,
        second_grid,
        rect=Rect(0, 0, columns, rows),
        mask_rects=mask_cells,
        tolerances=tolerances,
    )
    drift = 1.0 - float(metrics["similarity_score"] or 0.0)
    limit = float(tolerances["stability_max_mismatch_ratio"])
    stable = drift <= limit
    return {
        "status": "proven" if stable else "unstable",
        "policy": "required" if require_capture_stability else "waived_by_caller",
        "message": (
            ""
            if stable
            else (
                f"Two consecutive captures of the same fixture differ in {drift:.2%} of comparison cells "
                f"(limit {limit:.2%}); the screen is not frozen, so no visual verdict is trustworthy."
            )
        ),
        "cell_drift_ratio": round(drift, 6),
        "limit": limit,
        "stability_capture_path": str(second_path),
    }
