from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from server_ui_reference_manifest import (
    CHANNEL_THRESHOLD_KEYS,
    DEFAULT_THRESHOLDS,
    DEFAULT_TOLERANCE_PROFILE,
    EXPECTED_IMAGE_FILE_NAME,
    LANE_REQUIREMENTS,
    LANES,
    MASK_POLICY,
    ORIENTATIONS,
    OWNERS,
    RATIO_THRESHOLD_KEYS,
    RELATIVE_THRESHOLD_KEYS,
    Rect,
    SCALE_POLICIES,
    SCORE_THRESHOLD_KEYS,
    TOLERANCE_PROFILES,
    UI_REFERENCE_SCHEMA_VERSION,
    cell_footprint,
    clip_rect,
    comparison_grid_dimensions,
    derive_orientation,
    issue,
    positive_int,
    rect_from_mapping,
    resolve_tolerances,
    union_area,
)


def validate_manifest(manifest: dict[str, Any], *, reference_dir: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    schema_version = str(manifest.get("schema_version") or "")
    if schema_version != UI_REFERENCE_SCHEMA_VERSION:
        errors.append(
            issue(
                "ui_reference_schema_unsupported",
                f"Manifest schema '{schema_version or 'missing'}' is not {UI_REFERENCE_SCHEMA_VERSION}.",
                {"schema_version": schema_version},
            )
        )

    viewport = manifest.get("viewport") if isinstance(manifest.get("viewport"), dict) else {}
    width = positive_int(viewport.get("width"))
    height = positive_int(viewport.get("height"))
    if width <= 0 or height <= 0:
        errors.append(
            issue(
                "ui_reference_viewport_invalid",
                "Manifest viewport must declare a positive width and height.",
                {"viewport": dict(viewport)},
            )
        )

    orientation = str(viewport.get("orientation") or "")
    if orientation and orientation not in ORIENTATIONS:
        errors.append(
            issue(
                "ui_reference_orientation_invalid",
                f"Viewport orientation '{orientation}' must be one of: {', '.join(ORIENTATIONS)}.",
                {"orientation": orientation},
            )
        )
    elif orientation and width > 0 and height > 0 and orientation != derive_orientation(width, height):
        errors.append(
            issue(
                "ui_reference_orientation_inconsistent",
                (
                    f"Viewport orientation '{orientation}' does not match the declared "
                    f"{width}x{height} viewport."
                ),
                {"orientation": orientation, "width": width, "height": height},
            )
        )

    expected_image = manifest.get("expected_image") if isinstance(manifest.get("expected_image"), dict) else {}
    expected_path = reference_dir / str(expected_image.get("file_name") or EXPECTED_IMAGE_FILE_NAME)
    if not expected_path.is_file():
        errors.append(
            issue(
                "ui_reference_expected_image_missing",
                f"Expected image '{expected_path}' is missing from the reference bundle.",
                {"expected_image_path": str(expected_path)},
            )
        )
    else:
        actual_hash = hashlib.sha256(expected_path.read_bytes()).hexdigest()
        declared_hash = str(expected_image.get("sha256") or "")
        if declared_hash and actual_hash != declared_hash:
            errors.append(
                issue(
                    "ui_reference_expected_image_hash_mismatch",
                    (
                        "The expected image no longer matches the hash recorded at registration; the "
                        "reference was modified after intake."
                    ),
                    {"declared_sha256": declared_hash, "actual_sha256": actual_hash},
                )
            )
        declared_width = positive_int(expected_image.get("width"))
        declared_height = positive_int(expected_image.get("height"))
        if width > 0 and height > 0 and declared_width > 0 and declared_height > 0:
            if (declared_width, declared_height) != (width, height):
                errors.append(
                    issue(
                        "ui_reference_viewport_mismatch",
                        (
                            f"Expected image is {declared_width}x{declared_height} but the manifest declares "
                            f"a {width}x{height} viewport."
                        ),
                        {
                            "image_width": declared_width,
                            "image_height": declared_height,
                            "viewport_width": width,
                            "viewport_height": height,
                        },
                    )
                )

    bounds = Rect(0, 0, max(0, width), max(0, height))
    regions = manifest.get("regions") if isinstance(manifest.get("regions"), list) else []
    if not regions:
        errors.append(
            issue(
                "ui_reference_regions_missing",
                "At least one comparison region is required.",
                {},
            )
        )

    seen_ids: set[str] = set()
    region_rects: dict[str, Rect] = {}
    required_region_ids: list[str] = []
    for entry in regions:
        if not isinstance(entry, dict):
            errors.append(issue("ui_reference_region_invalid", "Region entries must be objects.", {}))
            continue
        region_id = str(entry.get("id") or "").strip()
        if not region_id:
            errors.append(issue("ui_reference_region_invalid", "Every region needs a non-empty id.", {}))
            continue
        if region_id in seen_ids:
            errors.append(
                issue(
                    "ui_reference_region_duplicate",
                    f"Region id '{region_id}' is declared more than once.",
                    {"region_id": region_id},
                )
            )
            continue
        seen_ids.add(region_id)
        rect = rect_from_mapping(entry.get("rect"))
        if rect is None or rect.area <= 0:
            errors.append(
                issue(
                    "ui_reference_region_invalid",
                    f"Region '{region_id}' must declare a rect with positive width and height.",
                    {"region_id": region_id, "rect": entry.get("rect")},
                )
            )
            continue
        if bounds.area > 0 and clip_rect(rect, bounds) != rect:
            errors.append(
                issue(
                    "ui_reference_region_out_of_bounds",
                    f"Region '{region_id}' extends outside the declared viewport.",
                    {"region_id": region_id, "rect": rect.to_mapping(), "viewport": bounds.to_mapping()},
                )
            )
            continue
        region_rects[region_id] = rect
        if bool(entry.get("required", True)):
            required_region_ids.append(region_id)
        weight = entry.get("weight", 1)
        if not isinstance(weight, (int, float)) or float(weight) <= 0:
            errors.append(
                issue(
                    "ui_reference_region_invalid",
                    f"Region '{region_id}' weight must be a positive number.",
                    {"region_id": region_id, "weight": weight},
                )
            )

    if len(regions) == 1 and bounds.area > 0:
        only_rect = region_rects.get(str(regions[0].get("id") or "")) if isinstance(regions[0], dict) else None
        if only_rect is not None and only_rect.area >= bounds.area:
            # A single full-screen region reduces acceptance to one whole-screen average, where a
            # missing element is diluted by the share of the screen it occupied: a missing button
            # or body paragraph scores above the similarity floor and passes. Localised regions are
            # what make the verdict mean anything, so this is a refusal, not a note.
            errors.append(
                issue(
                    "ui_reference_regions_coarse",
                    (
                        "Only one full-screen region is declared, so a mismatch cannot be localized "
                        "and a missing element is averaged away by the rest of the screen. Declare a "
                        "region per meaningful UI area (card, illustration, title, body, cta)."
                    ),
                    {"region_id": str(regions[0].get("id") or "")},
                )
            )

    masks = manifest.get("dynamic_masks") if isinstance(manifest.get("dynamic_masks"), list) else []
    mask_rects: list[Rect] = []
    for entry in masks:
        if not isinstance(entry, dict):
            errors.append(issue("ui_reference_mask_invalid", "Mask entries must be objects.", {}))
            continue
        mask_id = str(entry.get("id") or "").strip()
        rect = rect_from_mapping(entry.get("rect"))
        if not mask_id or rect is None or rect.area <= 0:
            errors.append(
                issue(
                    "ui_reference_mask_invalid",
                    "Every mask needs an id and a rect with positive width and height.",
                    {"mask_id": mask_id, "rect": entry.get("rect")},
                )
            )
            continue
        if not str(entry.get("reason") or "").strip():
            errors.append(
                issue(
                    "ui_reference_mask_reason_required",
                    f"Mask '{mask_id}' must declare why the region is excluded from comparison.",
                    {"mask_id": mask_id},
                )
            )
            continue
        clipped = clip_rect(rect, bounds) if bounds.area > 0 else rect
        if clipped.area <= 0:
            errors.append(
                issue(
                    "ui_reference_mask_invalid",
                    f"Mask '{mask_id}' lies entirely outside the declared viewport.",
                    {"mask_id": mask_id, "rect": rect.to_mapping()},
                )
            )
            continue
        mask_rects.append(clipped)
        warnings.append(
            issue(
                "ui_reference_mask_declared",
                f"Mask '{mask_id}' excludes {clipped.area} pixels: {entry.get('reason')}",
                {"mask_id": mask_id, "rect": clipped.to_mapping(), "reason": str(entry.get("reason"))},
            )
        )

    mask_columns, mask_rows = comparison_grid_dimensions(
        manifest.get("viewport") if isinstance(manifest.get("viewport"), dict) else {},
        resolve_tolerances(manifest),
    )
    mask_audit = build_mask_audit(
        mask_rects,
        bounds,
        region_rects,
        required_region_ids,
        columns=mask_columns,
        rows=mask_rows,
    )
    for violation in mask_audit["violations"]:
        errors.append(
            issue(
                "ui_reference_mask_policy_failed",
                violation["message"],
                {key: value for key, value in violation.items() if key != "message"},
            )
        )

    profile_name = str(manifest.get("tolerance_profile") or DEFAULT_TOLERANCE_PROFILE).strip().lower()
    if profile_name not in TOLERANCE_PROFILES:
        errors.append(
            issue(
                "ui_reference_tolerance_profile_invalid",
                f"Tolerance profile '{profile_name}' must be one of: {', '.join(sorted(TOLERANCE_PROFILES))}.",
                {"tolerance_profile": profile_name},
            )
        )

    scale_policy = str(manifest.get("scale_policy") or "aspect_scale").strip().lower()
    if scale_policy not in SCALE_POLICIES:
        errors.append(
            issue(
                "ui_reference_scale_policy_invalid",
                f"Scale policy '{scale_policy}' must be one of: {', '.join(SCALE_POLICIES)}.",
                {"scale_policy": scale_policy},
            )
        )
    elif scale_policy == "stretch":
        warnings.append(
            issue(
                "ui_reference_scale_policy_stretch",
                (
                    "Scale policy 'stretch' compares captures whose aspect ratio differs from the "
                    "reference; layout and size findings from this reference are weakened."
                ),
                {"scale_policy": scale_policy},
            )
        )

    overrides = manifest.get("thresholds") if isinstance(manifest.get("thresholds"), dict) else {}
    for key, value in overrides.items():
        name = str(key)
        if name not in DEFAULT_THRESHOLDS:
            warnings.append(
                issue(
                    "ui_reference_threshold_unknown",
                    f"Threshold override '{name}' is not a known tolerance and will be ignored.",
                    {"threshold": name},
                )
            )
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    f"Threshold '{name}' must be a number.",
                    {"threshold": name, "value": value},
                )
            )
            continue
        number = float(value)
        if name in SCORE_THRESHOLD_KEYS and not 0.0 < number <= 1.0:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    f"Threshold '{name}' must be a similarity score above 0 and at most 1.",
                    {"threshold": name, "value": value},
                )
            )
        elif name in RATIO_THRESHOLD_KEYS and not 0.0 <= number <= 1.0:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    f"Threshold '{name}' must be a ratio between 0 and 1.",
                    {"threshold": name, "value": value},
                )
            )
        elif name in CHANNEL_THRESHOLD_KEYS and not 0.0 <= number <= 255.0:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    f"Threshold '{name}' must be a channel delta between 0 and 255.",
                    {"threshold": name, "value": value},
                )
            )
        elif name in RELATIVE_THRESHOLD_KEYS and not 0.0 <= number <= 1.0:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    f"Threshold '{name}' must be a ratio between 0 and 1.",
                    {"threshold": name, "value": value},
                )
            )
        elif name == "cell_coarse_factor" and not 1 <= number <= 8:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    "Threshold 'cell_coarse_factor' must be between 1 and 8.",
                    {"value": value},
                )
            )
        elif name == "cell_match_radius" and not 0 <= number <= 4:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    "Threshold 'cell_match_radius' must be between 0 and 4 cells.",
                    {"value": value},
                )
            )
        elif name == "comparison_grid_width" and not 16 <= number <= 512:
            errors.append(
                issue(
                    "ui_reference_threshold_invalid",
                    "Threshold 'comparison_grid_width' must be between 16 and 512 cells.",
                    {"value": value},
                )
            )

    for entry in manifest.get("required_ui") or []:
        if not isinstance(entry, dict) or not str(entry.get("selector") or "").strip():
            errors.append(
                issue(
                    "ui_reference_required_ui_invalid",
                    "Every required_ui entry must declare a selector.",
                    {"entry": entry},
                )
            )

    owner = str(manifest.get("owner") or "")
    if owner not in OWNERS:
        errors.append(
            issue(
                "ui_reference_owner_invalid",
                f"Manifest owner '{owner}' must be one of: {', '.join(OWNERS)}.",
                {"owner": owner},
            )
        )

    acceptance = manifest.get("acceptance") if isinstance(manifest.get("acceptance"), dict) else {}
    for lane in LANES:
        # An absent lane takes its documented default, so a manifest registered before a lane
        # existed stays valid. Only a lane that is present with a bad value is an error.
        if lane not in acceptance:
            continue
        requirement = str(acceptance.get(lane) or "")
        if requirement not in LANE_REQUIREMENTS:
            errors.append(
                issue(
                    "ui_reference_acceptance_invalid",
                    f"Acceptance lane '{lane}' must be one of: {', '.join(LANE_REQUIREMENTS)}.",
                    {"lane": lane, "value": requirement},
                )
            )

    errors.extend(_vision_policy_errors(manifest, issue))
    warnings.extend(_vision_policy_warnings(manifest, issue))

    if not str(manifest.get("fixture") or "").strip():
        warnings.append(
            issue(
                "ui_reference_fixture_undeclared",
                (
                    "No canonical UI fixture is declared, so repeated captures are not proven "
                    "deterministic and a passing comparison is not durable evidence."
                ),
                {},
            )
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "mask_audit": mask_audit,
        "region_count": len(region_rects),
        "required_region_ids": required_region_ids,
    }


def build_mask_audit(
    mask_rects: list[Rect],
    bounds: Rect,
    region_rects: dict[str, Rect],
    required_region_ids: Iterable[str],
    *,
    columns: int = 0,
    rows: int = 0,
) -> dict[str, Any]:
    # Charge each mask the area the comparison actually stops looking at, which is its footprint
    # snapped outward to whole cells, not the pixels it declares.
    effective_rects = mask_rects
    if columns > 0 and rows > 0 and bounds.area > 0:
        effective_rects = [
            cell_footprint(
                rect,
                reference_width=bounds.width,
                reference_height=bounds.height,
                columns=columns,
                rows=rows,
            )
            for rect in mask_rects
        ]
        effective_rects = [clip_rect(rect, bounds) for rect in effective_rects]
        effective_rects = [rect for rect in effective_rects if rect.area > 0]

    declared_masked = union_area(mask_rects)
    total_masked = union_area(effective_rects)
    viewport_area = bounds.area
    total_ratio = (total_masked / viewport_area) if viewport_area else 0.0
    violations: list[dict[str, Any]] = []

    if total_ratio > MASK_POLICY["max_total_mask_ratio"]:
        violations.append(
            {
                "message": (
                    f"Declared masks cover {total_ratio:.1%} of the viewport, above the "
                    f"{MASK_POLICY['max_total_mask_ratio']:.0%} policy limit; a broad mask hides the "
                    "very area under review."
                ),
                "masked_ratio": round(total_ratio, 6),
                "limit": MASK_POLICY["max_total_mask_ratio"],
                "scope": "viewport",
            }
        )

    region_masking: list[dict[str, Any]] = []
    required_ids = set(required_region_ids)
    for region_id, rect in region_rects.items():
        clipped = [clip_rect(mask, rect) for mask in effective_rects]
        masked = union_area([entry for entry in clipped if entry.area > 0])
        ratio = (masked / rect.area) if rect.area else 0.0
        region_masking.append(
            {"region_id": region_id, "masked_pixels": masked, "masked_ratio": round(ratio, 6)}
        )
        # The cap holds for every declared region. Gating it on `required` let a full-card mask
        # over a non-required region erase the card and still report a clean pass.
        if ratio > MASK_POLICY["max_region_mask_ratio"]:
            scope = "required region" if region_id in required_ids else "region"
            violations.append(
                {
                    "message": (
                        f"{scope.capitalize()} '{region_id}' is {ratio:.1%} masked, above the "
                        f"{MASK_POLICY['max_region_mask_ratio']:.0%} policy limit."
                    ),
                    "region_id": region_id,
                    "masked_ratio": round(ratio, 6),
                    "limit": MASK_POLICY["max_region_mask_ratio"],
                    "scope": "region",
                }
            )

    return {
        "mask_count": len(mask_rects),
        "masked_pixels": total_masked,
        "declared_masked_pixels": declared_masked,
        "masked_ratio": round(total_ratio, 6),
        "policy": dict(MASK_POLICY),
        "accounting": "comparison_cell_footprint",
        "regions": sorted(region_masking, key=lambda item: str(item["region_id"])),
        "violations": violations,
    }


VISION_POLICY_KEYS = (
    "min_criterion",
    "min_overall",
    "judges_required",
    "allow_self_review",
    "required_criteria",
)
VISION_POLICY_INT_KEYS = ("min_criterion", "min_overall", "judges_required")


def _vision_policy_errors(manifest: dict[str, Any], issue: Any) -> list[dict[str, Any]]:
    from server_ui_vision_review import CRITERIA, SCALE_MAX

    raw = manifest.get("vision_policy")
    if not isinstance(raw, dict):
        return []

    errors: list[dict[str, Any]] = []
    for key in VISION_POLICY_INT_KEYS:
        if key not in raw:
            continue
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(
                issue(
                    "ui_reference_vision_policy_invalid",
                    f"Vision policy '{key}' must be a number.",
                    {"key": key, "value": value},
                )
            )
            continue
        number = int(value)
        limit = SCALE_MAX if key != "judges_required" else 16
        if not 1 <= number <= limit:
            errors.append(
                issue(
                    "ui_reference_vision_policy_invalid",
                    (
                        f"Vision policy '{key}' must be between 1 and {limit}; a floor of 0 would be "
                        "a bar no review can fail."
                    ),
                    {"key": key, "value": value},
                )
            )

    if "allow_self_review" in raw and not isinstance(raw.get("allow_self_review"), bool):
        errors.append(
            issue(
                "ui_reference_vision_policy_invalid",
                "Vision policy 'allow_self_review' must be a boolean.",
                {"key": "allow_self_review", "value": raw.get("allow_self_review")},
            )
        )

    if "required_criteria" in raw:
        declared = raw.get("required_criteria")
        if not isinstance(declared, list):
            errors.append(
                issue(
                    "ui_reference_vision_policy_invalid",
                    "Vision policy 'required_criteria' must be a list of rubric criteria.",
                    {"key": "required_criteria", "value": declared},
                )
            )
        else:
            unknown = [str(item) for item in declared if str(item) not in CRITERIA]
            if unknown:
                errors.append(
                    issue(
                        "ui_reference_vision_policy_invalid",
                        (
                            "Vision policy 'required_criteria' names criteria that are not in the "
                            f"rubric: {', '.join(unknown)}. Known criteria: {', '.join(CRITERIA)}."
                        ),
                        {"key": "required_criteria", "unknown": unknown},
                    )
                )
            elif not declared:
                errors.append(
                    issue(
                        "ui_reference_vision_policy_invalid",
                        (
                            "Vision policy 'required_criteria' is empty, which waives the whole "
                            "rubric; omit the key to require every criterion."
                        ),
                        {"key": "required_criteria"},
                    )
                )
    return errors


def _vision_policy_warnings(manifest: dict[str, Any], issue: Any) -> list[dict[str, Any]]:
    raw = manifest.get("vision_policy")
    if not isinstance(raw, dict):
        return []

    warnings: list[dict[str, Any]] = []
    for key in raw:
        name = str(key)
        if name in VISION_POLICY_KEYS:
            continue
        snake = _camel_to_snake(name)
        if snake in VISION_POLICY_KEYS:
            warnings.append(
                issue(
                    "ui_reference_vision_policy_key_ignored",
                    (
                        f"Vision policy key '{name}' is ignored; this contract is snake_case, so "
                        f"write '{snake}'. As declared it silently keeps the default."
                    ),
                    {"key": name, "expected": snake},
                )
            )
        else:
            warnings.append(
                issue(
                    "ui_reference_vision_policy_key_unknown",
                    f"Vision policy key '{name}' is not recognised and will be ignored.",
                    {"key": name},
                )
            )
    return warnings


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for char in str(name):
        if char.isupper():
            out.append("_")
            out.append(char.lower())
        else:
            out.append(char)
    return "".join(out)
