from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from server_artifact_registry import resolve_workspace_root
from server_core import ToolInvocationError, read_json, write_json
from server_ui_reference_artifacts import write_artifact_record
from server_ui_reference_manifest import DEFAULT_REFERENCE_CATEGORY, utc_now
from server_ui_reference_png import encode_png, read_png
from server_ui_reference_registry import load_ui_reference
from server_ui_vision_review import (
    RUBRIC_VERSION,
    UI_VISION_SCHEMA_VERSION,
    canonical_submission,
    evaluate_vision_lane,
    normalize_vision_review,
    packet_hash,
    resolve_vision_policy,
    vision_next_actions,
    vision_rubric,
)
from server_ui_vision_sheet import DEFAULT_MAX_PANEL_HEIGHT, render_review_sheet

PACKET_FILE_NAME = "vision_packet.json"
SHEET_FILE_NAME = "vision_sheet.png"
REVIEW_FILE_PREFIX = "vision_review"


def build_vision_packet(
    *,
    project_root: Path,
    actual_image: str,
    reference_id: str = "",
    manifest_path: str = "",
    comparison_path: str = "",
    comparison_id: str = "",
    include_numeric_evidence: bool = False,
    max_panel_height: int = DEFAULT_MAX_PANEL_HEIGHT,
    category: str = DEFAULT_REFERENCE_CATEGORY,
    workspace_root: str = "",
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
    reference_dir = Path(loaded["reference_dir"])
    policy = resolve_vision_policy(manifest)

    expected_path = reference_dir / str(
        (manifest.get("expected_image") or {}).get("file_name") or "expected.png"
    )
    actual_path = _resolve_existing(actual_image, workspace, "actualImage")
    expected = read_png(expected_path, source="expected")
    actual = read_png(actual_path, source="actual")

    comparison = _load_comparison(comparison_path, workspace)
    marked = _marked_regions(comparison)
    viewport = dict(manifest.get("viewport") or {})
    sheet, layout = render_review_sheet(
        expected=expected,
        actual=actual,
        marked_regions=marked,
        reference_viewport={
            "width": int(viewport.get("width") or expected.width),
            "height": int(viewport.get("height") or expected.height),
        },
        max_panel_height=max_panel_height,
    )

    expected_sha = hashlib.sha256(expected_path.read_bytes()).hexdigest()
    actual_sha = hashlib.sha256(actual_path.read_bytes()).hexdigest()
    digest = packet_hash(
        reference_id=str(manifest.get("reference_id") or ""),
        expected_sha256=expected_sha,
        actual_sha256=actual_sha,
        policy=policy,
    )

    resolved_id = (
        comparison_id.strip()
        or str((comparison or {}).get("comparison_id") or "")
        or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    )
    output_dir = reference_dir / "comparisons" / resolved_id / "vision"
    output_dir.mkdir(parents=True, exist_ok=True)

    sheet_bytes = encode_png(sheet)
    artifacts = [write_artifact_record(output_dir / SHEET_FILE_NAME, sheet_bytes, workspace, "vision_sheet")]

    packet: dict[str, Any] = {
        "action": "unity_ui_vision_packet",
        "schema_version": UI_VISION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "generated_at_utc": utc_now(),
        "project_root": str(project_root),
        "reference_id": str(manifest.get("reference_id") or ""),
        "comparison_id": resolved_id,
        "packet_hash": digest,
        "policy": policy,
        "images": {
            "reference": {"path": str(expected_path), "sha256": expected_sha,
                          "width": expected.width, "height": expected.height},
            "candidate": {"path": str(actual_path), "sha256": actual_sha,
                          "width": actual.width, "height": actual.height},
        },
        "sheet": {
            "path": str(output_dir / SHEET_FILE_NAME),
            "sha256": artifacts[0]["sha256"],
            **layout,
        },
        "attention": {
            "marked_regions": marked,
            "anchoring": (
                "numeric_scores_disclosed"
                if include_numeric_evidence
                else "failed_regions_marked_scores_withheld"
            ),
            "note": (
                "Failed regions are outlined on both panels so a judge knows where to look. "
                "Scores are withheld by default so the judgement is not anchored to the number "
                "the grid already produced."
            ),
        },
        "rubric": vision_rubric(),
        "submit_with": "unity_ui_vision_submit",
    }

    if include_numeric_evidence and comparison:
        packet["numeric_evidence"] = {
            "visual_verdict": comparison.get("visual_verdict", ""),
            "global_similarity": (comparison.get("global") or {}).get("similarity_score"),
            "failed_regions": [
                {"region_id": region.get("region_id"), "similarity_score": region.get("similarity_score")}
                for region in (comparison.get("regions") or [])
                if region.get("passed") is False
            ],
        }

    packet_path = output_dir / PACKET_FILE_NAME
    packet["packet_path"] = str(packet_path)
    write_json(packet_path, packet)
    artifacts.append(
        write_artifact_record(packet_path, packet_path.read_bytes(), workspace, "vision_packet", already_written=True)
    )

    packet["artifacts"] = artifacts
    packet["succeeded"] = True
    packet["next_actions"] = [
        f"Open {output_dir / SHEET_FILE_NAME} and compare the two panels against the rubric.",
        (
            f"Submit the judgement with unity_ui_vision_submit packetPath={packet_path} and a judge "
            "role; use independent_agent or human rather than authoring_agent where you can."
        ),
    ]
    return packet


def submit_vision_review(
    *,
    project_root: Path,
    packet_path: str,
    review: dict[str, Any] | None,
    review_path: str = "",
    workspace_root: str = "",
) -> dict[str, Any]:
    workspace = resolve_workspace_root(project_root, workspace_root)
    packet_file = _resolve_existing(packet_path, workspace, "packetPath")
    packet = read_json(packet_file)
    if not isinstance(packet, dict) or str(packet.get("schema_version") or "") != UI_VISION_SCHEMA_VERSION:
        raise ToolInvocationError(
            "ui_vision_packet_invalid",
            f"'{packet_file}' is not a {UI_VISION_SCHEMA_VERSION} packet.",
            {"packet_path": str(packet_file)},
        )

    policy = dict(packet.get("policy") or {})
    submitted: Any = review
    if not submitted and str(review_path or "").strip():
        payload = read_json(_resolve_existing(review_path, workspace, "reviewPath"))
        submitted = payload.get("vision_review") if isinstance(payload, dict) and "vision_review" in payload else payload
    if isinstance(submitted, dict) and "vision_review" in submitted:
        submitted = submitted.get("vision_review")

    record = normalize_vision_review(
        submitted,
        policy=policy,
        expected_packet_hash=str(packet.get("packet_hash") or ""),
    )

    output_dir = packet_file.parent
    judge_id = str((record.get("judge") or {}).get("id") or "unattributed")
    safe_judge = "".join(character if character.isalnum() or character in "-_" else "_" for character in judge_id)
    stored_path = output_dir / f"{REVIEW_FILE_PREFIX}.{safe_judge}.json"

    # A review the normalizer has already rejected must not reach the store: once written it is
    # auto-collected by glob and blocks the comparison with no way to retract it.
    if not record["valid"]:
        raise ToolInvocationError(
            "ui_vision_review_invalid",
            (
                f"The submitted review is not a valid {UI_VISION_SCHEMA_VERSION} judgement and was "
                f"not stored: {', '.join(str(code) for code in record['errors'])}."
            ),
            {
                "packet_path": str(packet_file),
                "errors": list(record["errors"]),
                "judge_id": judge_id,
            },
        )

    # Overwriting would erase a prior verdict without trace; a re-judgement is a new file.
    if stored_path.exists():
        raise ToolInvocationError(
            "ui_vision_review_already_submitted",
            (
                f"Judge '{judge_id}' has already submitted a review for this packet at "
                f"'{stored_path}'. Delete that file to retract the judgement, or submit under a "
                "distinct judge id; a silent overwrite would destroy the earlier verdict."
            ),
            {"packet_path": str(packet_file), "stored_review_path": str(stored_path)},
        )

    write_json(
        stored_path,
        {
            "schema_version": UI_VISION_SCHEMA_VERSION,
            "vision_review": canonical_submission(record),
        },
    )

    reviews = _load_sibling_reviews(output_dir, policy, str(packet.get("packet_hash") or ""))
    lane = evaluate_vision_lane(reviews=reviews, policy=policy, requirement="required")

    return {
        "action": "unity_ui_vision_submit",
        "schema_version": UI_VISION_SCHEMA_VERSION,
        "project_root": str(project_root),
        "packet_path": str(packet_file),
        "packet_hash": str(packet.get("packet_hash") or ""),
        "reference_id": str(packet.get("reference_id") or ""),
        "comparison_id": str(packet.get("comparison_id") or ""),
        "review": record,
        "stored_review_path": str(stored_path),
        "vision_lane": lane,
        "succeeded": record["valid"] and record["verdict"] == "passed",
        "next_actions": vision_next_actions(lane),
    }


def collect_vision_reviews(
    *,
    reference_dir: Path,
    comparison_id: str,
    policy: dict[str, Any],
    expected_hash: str,
) -> list[dict[str, Any]]:
    directory = reference_dir / "comparisons" / comparison_id / "vision"
    if not directory.is_dir():
        return []
    return _load_sibling_reviews(directory, policy, expected_hash)


def _load_sibling_reviews(directory: Path, policy: dict[str, Any], expected_hash: str) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for path in sorted(directory.glob(f"{REVIEW_FILE_PREFIX}.*.json")):
        try:
            payload = read_json(path)
        except Exception as exc:
            # Skipping silently would make an unreadable review indistinguishable from no review.
            reviews.append(
                {
                    "contract_version": UI_VISION_SCHEMA_VERSION,
                    "reported": True,
                    "valid": False,
                    "verdict": "blocked",
                    "errors": ["vision_review_unreadable"],
                    "warnings": [],
                    "messages": [f"'{path.name}' could not be read as JSON: {exc}"],
                    "judge": {},
                    "criteria": {},
                    "overall_reported": None,
                    "overall_effective": None,
                    "defects": [],
                    "packet_hash": "",
                    "source_path": str(path),
                }
            )
            continue
        block = payload.get("vision_review") if isinstance(payload, dict) else None
        record = normalize_vision_review(
            block if isinstance(block, dict) else payload,
            policy=policy,
            expected_packet_hash=expected_hash,
        )
        record["source_path"] = str(path)
        reviews.append(record)
    return reviews


def _load_comparison(comparison_path: str, workspace: Path) -> dict[str, Any]:
    text = str(comparison_path or "").strip()
    if not text:
        return {}
    resolved = _resolve_existing(text, workspace, "comparisonPath")
    payload = read_json(resolved)
    return payload if isinstance(payload, dict) else {}


def _marked_regions(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for region in comparison.get("regions") or []:
        if not isinstance(region, dict) or region.get("passed") is not False:
            continue
        rect = region.get("rect")
        if isinstance(rect, dict):
            marked.append({"region_id": str(region.get("region_id") or ""), "rect": rect})
    return marked


def _resolve_existing(value: str, workspace: Path, argument: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ToolInvocationError(
            "ui_vision_argument_missing",
            f"{argument} is required.",
            {"argument": argument},
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (workspace / path).resolve()
    if not path.is_file():
        raise ToolInvocationError(
            "ui_vision_path_not_found",
            f"'{path}' was not found.",
            {"argument": argument, "path": str(path)},
        )
    return path
