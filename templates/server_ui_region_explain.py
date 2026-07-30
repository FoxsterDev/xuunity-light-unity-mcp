from __future__ import annotations

from pathlib import Path
from typing import Any

from server_core import ToolInvocationError, read_json
from server_ui_reference_manifest import Rect


UI_SNAPSHOT_SCHEMA_VERSION = "xuunity.ui.read.v1"

SUSPICION_MESSAGES = {
    "missing_script_component": "the node carries a component whose script no longer resolves",
    "font_unresolved": "its font asset did not resolve",
    "material_unresolved": "its render material did not resolve",
    "empty_text": "it is a text node with an empty string",
    "inactive": "it is inactive in the hierarchy",
    "alpha_zero": "its effective alpha is 0",
    "fully_clipped": "it is fully clipped by a RectMask2D",
    "partially_clipped": "it is partially clipped by a RectMask2D",
    "not_interactable": "it is not interactable",
}

SUSPICION_PRIORITY = (
    "missing_script_component",
    "font_unresolved",
    "material_unresolved",
    "empty_text",
    "inactive",
    "alpha_zero",
    "fully_clipped",
    "partially_clipped",
    "not_interactable",
)


def load_ui_snapshot(snapshot_path: str, workspace: Path) -> dict[str, Any]:
    path = Path(str(snapshot_path).strip()).expanduser()
    if not path.is_absolute():
        path = (workspace / path).resolve()
    if not path.is_file():
        raise ToolInvocationError(
            "ui_snapshot_not_found",
            f"UI snapshot '{path}' was not found.",
            {"snapshot_path": str(path)},
        )

    try:
        payload = read_json(path)
    except Exception as exc:
        raise ToolInvocationError(
            "ui_snapshot_unreadable",
            f"UI snapshot '{path}' could not be read as JSON: {exc}",
            {"snapshot_path": str(path)},
        ) from exc

    if not isinstance(payload, dict):
        raise ToolInvocationError(
            "ui_snapshot_unreadable",
            f"UI snapshot '{path}' is not a JSON object.",
            {"snapshot_path": str(path)},
        )

    schema_version = str(payload.get("schema_version") or payload.get("schemaVersion") or "")
    if schema_version != UI_SNAPSHOT_SCHEMA_VERSION:
        raise ToolInvocationError(
            "ui_snapshot_schema_unsupported",
            f"UI snapshot declares schema '{schema_version}'. Expected '{UI_SNAPSHOT_SCHEMA_VERSION}'.",
            {"snapshot_path": str(path), "schema_version": schema_version},
        )

    payload["snapshot_path"] = str(path)
    return payload


def snapshot_viewport(snapshot: dict[str, Any]) -> dict[str, int]:
    target = dict(snapshot.get("target") or {})
    width = _positive_int(target.get("capture_width"))
    height = _positive_int(target.get("capture_height"))
    if width and height:
        return {"width": width, "height": height}
    return {}


def explain_regions(
    *,
    snapshot: dict[str, Any],
    regions: list[dict[str, Any]],
    reference_viewport: dict[str, Any],
    actual_viewport: dict[str, int],
    max_nodes_per_region: int = 5,
) -> dict[str, Any]:
    reference_width = _positive_int(reference_viewport.get("width"))
    reference_height = _positive_int(reference_viewport.get("height"))
    warnings: list[dict[str, str]] = []

    declared = snapshot_viewport(snapshot)
    if declared:
        source_viewport = declared
        viewport_source = "snapshot_capture_viewport"
        if actual_viewport and (
            declared["width"] != actual_viewport.get("width")
            or declared["height"] != actual_viewport.get("height")
        ):
            warnings.append(
                {
                    "code": "ui_snapshot_viewport_differs_from_capture",
                    "message": (
                        f"The snapshot was taken at {declared['width']}x{declared['height']} but the capture is "
                        f"{actual_viewport.get('width')}x{actual_viewport.get('height')}; node geometry is mapped "
                        "from the snapshot's own viewport and may not describe this capture."
                    ),
                }
            )
    elif actual_viewport:
        source_viewport = dict(actual_viewport)
        viewport_source = "actual_capture_dimensions"
        warnings.append(
            {
                "code": "ui_snapshot_viewport_assumed",
                "message": (
                    "The snapshot does not record its capture viewport; node geometry is mapped assuming it "
                    "matches the compared capture."
                ),
            }
        )
    else:
        return {
            "available": False,
            "reason": "no_viewport_to_map_node_bounds_from",
            "warnings": warnings,
            "regions": {},
        }

    nodes = _mappable_nodes(snapshot)
    if not nodes:
        return {
            "available": False,
            "reason": "snapshot_has_no_nodes_with_screen_bounds",
            "warnings": warnings,
            "regions": {},
        }

    transform = {
        "snapshot_viewport": source_viewport,
        "viewport_source": viewport_source,
        "reference_viewport": {"width": reference_width, "height": reference_height},
        "scale_x": round(reference_width / source_viewport["width"], 6),
        "scale_y": round(reference_height / source_viewport["height"], 6),
        "origin_conversion": "snapshot_bottom_left_to_reference_top_left",
    }

    mapped = [
        (node, _to_reference_rect(node, source_viewport, reference_width, reference_height))
        for node in nodes
    ]

    explanations: dict[str, Any] = {}
    for region in regions:
        if region.get("passed") is not False:
            continue
        rect = Rect(
            int(region["rect"]["x"]),
            int(region["rect"]["y"]),
            int(region["rect"]["width"]),
            int(region["rect"]["height"]),
        )
        explanations[str(region["region_id"])] = _explain_region(
            rect,
            mapped,
            max_nodes=max_nodes_per_region,
        )

    return {
        "available": True,
        "snapshot_path": str(snapshot.get("snapshot_path") or ""),
        "snapshot_proof_class": str(snapshot.get("proof_class") or ""),
        "component_detail_backends": list(snapshot.get("component_detail_backends") or []),
        "mapped_node_count": len(mapped),
        "coordinate_transform": transform,
        "warnings": warnings,
        "regions": explanations,
    }


def _explain_region(
    rect: Rect,
    mapped: list[tuple[dict[str, Any], Rect]],
    *,
    max_nodes: int,
) -> dict[str, Any]:
    region_area = max(1, rect.width * rect.height)
    candidates: list[dict[str, Any]] = []

    for node, node_rect in mapped:
        overlap = _intersection_area(rect, node_rect)
        if overlap <= 0:
            continue

        node_area = max(1, node_rect.width * node_rect.height)
        candidates.append(
            {
                "path": str(node.get("path") or ""),
                "name": str(node.get("name") or ""),
                "components": list(node.get("components") or [])[:8],
                "region_coverage": round(overlap / region_area, 4),
                "node_coverage": round(overlap / node_area, 4),
                "reference_rect": node_rect.to_mapping(),
                "visible": bool(node.get("visible", False)),
                "active_in_hierarchy": bool(node.get("active_in_hierarchy", False)),
                "effective_alpha": float(node.get("effective_alpha", 1.0)),
                "interactable": bool(node.get("interactable", True)),
                "has_text": bool(node.get("has_text", False)),
                "text": str(node.get("text") or ""),
                "font_resolved_status": str(node.get("font_resolved_status") or "not_evaluated"),
                "material_resolved_status": str(node.get("material_resolved_status") or "not_evaluated"),
                "clip_state": str(node.get("clip_state") or "not_evaluated"),
                "suspicions": _node_suspicions(node),
            }
        )

    candidates.sort(key=lambda item: (-len(item["suspicions"]), -item["region_coverage"]))
    top = candidates[:max_nodes]
    likely_cause = ""
    likely_node = ""
    for code in SUSPICION_PRIORITY:
        for candidate in top:
            if code in candidate["suspicions"]:
                likely_cause = code
                likely_node = candidate["path"]
                break
        if likely_cause:
            break

    return {
        "candidate_count": len(candidates),
        "nodes": top,
        "likely_cause": likely_cause,
        "likely_cause_node": likely_node,
        "summary": _region_summary(likely_cause, likely_node, candidates),
    }


def _region_summary(likely_cause: str, likely_node: str, candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return (
            "No UI node in the snapshot overlaps this region, which itself is a finding: the screen "
            "renders nothing where the reference expects content."
        )
    if not likely_cause:
        return (
            f"{len(candidates)} node(s) cover this region and none reports a semantic defect; the difference "
            "is visual (wrong sprite, colour, or layout), not a broken binding."
        )
    return f"'{likely_node}' overlaps this region and {SUSPICION_MESSAGES[likely_cause]}."


def _node_suspicions(node: dict[str, Any]) -> list[str]:
    suspicions: list[str] = []
    components = [str(item) for item in (node.get("components") or [])]
    if "<missing script>" in components:
        suspicions.append("missing_script_component")
    if str(node.get("font_resolved_status") or "") == "unresolved":
        suspicions.append("font_unresolved")
    material_status = str(node.get("material_resolved_status") or "")
    if material_status in ("unresolved", "font_without_material", "target_graphic_missing"):
        suspicions.append("material_unresolved")
    if bool(node.get("has_text", False)) and not str(node.get("text") or "").strip():
        suspicions.append("empty_text")
    if not bool(node.get("active_in_hierarchy", True)):
        suspicions.append("inactive")
    if float(node.get("effective_alpha", 1.0)) <= 0.0:
        suspicions.append("alpha_zero")
    clip_state = str(node.get("clip_state") or "")
    if clip_state == "fully_clipped":
        suspicions.append("fully_clipped")
    elif clip_state == "partially_clipped":
        suspicions.append("partially_clipped")
    return suspicions


def evaluate_semantic_lane(
    *,
    snapshot: dict[str, Any] | None,
    required_ui: list[dict[str, Any]],
) -> dict[str, Any]:
    if snapshot is None:
        return {
            "status": "not_evaluated",
            "evidence": "no_ui_snapshot_supplied",
            "checked": 0,
            "failures": [],
        }

    if not required_ui:
        return {
            "status": "not_evaluated",
            "evidence": "reference_declares_no_required_ui_selectors",
            "checked": 0,
            "failures": [],
        }

    nodes = list(_snapshot_nodes(snapshot))
    failures: list[dict[str, Any]] = []
    for entry in required_ui:
        selector = dict(entry.get("selector") or entry)
        matches = [node for node in nodes if _matches_selector(node, selector)]
        failure = _required_ui_failure(entry, selector, matches)
        if failure:
            failures.append(failure)

    return {
        "status": "failed" if failures else "passed",
        "evidence": "semantic_ui_tree_selector_check",
        "checked": len(required_ui),
        "failures": failures,
    }


def _required_ui_failure(
    entry: dict[str, Any],
    selector: dict[str, Any],
    matches: list[dict[str, Any]],
) -> dict[str, Any] | None:
    label = str(entry.get("id") or selector.get("name") or selector.get("path") or "selector")
    if not matches:
        return {"id": label, "code": "ui_node_not_found", "selector": selector}
    if len(matches) > 1 and not bool(entry.get("allowMany")):
        return {
            "id": label,
            "code": "selector_ambiguous",
            "selector": selector,
            "match_count": len(matches),
        }

    node = matches[0]
    expected_text = entry.get("text")
    if isinstance(expected_text, str) and str(node.get("text") or "") != expected_text:
        return {
            "id": label,
            "code": "ui_text_mismatch",
            "selector": selector,
            "expected": expected_text,
            "observed": str(node.get("text") or ""),
        }

    if entry.get("interactable") is True and not bool(node.get("interactable", True)):
        return {"id": label, "code": "ui_node_not_interactable", "selector": selector}

    if entry.get("visible") is not False and not bool(node.get("visible", False)):
        return {
            "id": label,
            "code": "ui_node_not_visible",
            "selector": selector,
            "effective_alpha": float(node.get("effective_alpha", 1.0)),
        }

    return None


def _matches_selector(node: dict[str, Any], selector: dict[str, Any]) -> bool:
    name = str(selector.get("name") or "").strip()
    if name and str(node.get("name") or "") != name:
        return False

    path = str(selector.get("path") or "").strip()
    if path and str(node.get("path") or "") != path:
        return False

    path_contains = str(selector.get("pathContains") or selector.get("path_contains") or "").strip()
    if path_contains and path_contains not in str(node.get("path") or ""):
        return False

    node_type = str(selector.get("type") or "").strip()
    if node_type and node_type not in [str(item) for item in (node.get("components") or [])]:
        return False

    return True


def _snapshot_nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in (snapshot.get("nodes") or []) if isinstance(node, dict)]


def _mappable_nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for node in _snapshot_nodes(snapshot):
        if not bool(node.get("has_bounds")):
            continue
        if str(node.get("bounds_space") or "") not in ("screen_pixels", "world_projected_pixels"):
            continue
        nodes.append(node)
    return nodes


def _to_reference_rect(
    node: dict[str, Any],
    source_viewport: dict[str, int],
    reference_width: int,
    reference_height: int,
) -> Rect:
    bounds = dict(node.get("bounds") or {})
    scale_x = reference_width / source_viewport["width"]
    scale_y = reference_height / source_viewport["height"]
    width = float(bounds.get("width") or 0.0)
    height = float(bounds.get("height") or 0.0)
    left = float(bounds.get("x") or 0.0)
    bottom = float(bounds.get("y") or 0.0)
    top_down_y = source_viewport["height"] - (bottom + height)
    return Rect(
        int(round(left * scale_x)),
        int(round(top_down_y * scale_y)),
        max(0, int(round(width * scale_x))),
        max(0, int(round(height * scale_y))),
    )


def _intersection_area(first: Rect, second: Rect) -> int:
    overlap_x = min(first.right, second.right) - max(first.x, second.x)
    overlap_y = min(first.bottom, second.bottom) - max(first.y, second.y)
    if overlap_x <= 0 or overlap_y <= 0:
        return 0
    return overlap_x * overlap_y


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))
