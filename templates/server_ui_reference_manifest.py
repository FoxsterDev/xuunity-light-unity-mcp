from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from server_core import ToolInvocationError

UI_REFERENCE_SCHEMA_VERSION = "xuunity.ui-reference.v1"
DEFAULT_REFERENCE_CATEGORY = "UIReference"
MANIFEST_FILE_NAME = "reference.json"
EXPECTED_IMAGE_FILE_NAME = "expected.png"

ORIENTATIONS = ("portrait", "landscape", "square")
OWNERS = ("agent", "human")
LANES = ("visual", "semantic", "interaction", "vision")
LANE_REQUIREMENTS = ("required", "optional", "not_required")
# The host cannot summon a multimodal judge on its own, so an unreviewed vision lane must not
# block. A review that was actually submitted and failed still fails the comparison.
DEFAULT_LANE_REQUIREMENTS = {
    "visual": "required",
    "semantic": "required",
    "interaction": "required",
    "vision": "optional",
}

SCALE_POLICIES = ("aspect_scale", "strict", "stretch")

# Acceptance is "is this recognisably the same screen", not pixel equality. Tolerances are
# expressed on the resolution-independent comparison grid so a Game View capture at a
# different resolution than the supplied reference is still a valid input.
TOLERANCE_PROFILES: dict[str, dict[str, float]] = {
    "strict": {
        "cell_color_tolerance": 6.0,
        "cell_structure_tolerance": 6.0,
        "region_min_similarity": 0.98,
        "global_min_similarity": 0.98,
        "layout_offset_tolerance": 0.01,
        "layout_size_tolerance": 0.02,
        "layout_content_tolerance": 18.0,
        "cell_match_radius": 0.0,
        "cell_coarse_factor": 1.0,
        "cell_structure_relative_tolerance": 0.35,
    },
    "balanced": {
        "cell_color_tolerance": 14.0,
        "cell_structure_tolerance": 12.0,
        "region_min_similarity": 0.92,
        "global_min_similarity": 0.93,
        "layout_offset_tolerance": 0.03,
        "layout_size_tolerance": 0.05,
        "layout_content_tolerance": 22.0,
    },
    "lenient": {
        "cell_color_tolerance": 24.0,
        "cell_structure_tolerance": 20.0,
        "region_min_similarity": 0.85,
        "global_min_similarity": 0.86,
        "layout_offset_tolerance": 0.06,
        "layout_size_tolerance": 0.10,
        "layout_content_tolerance": 28.0,
    },
}
DEFAULT_TOLERANCE_PROFILE = "balanced"
SHARED_THRESHOLD_DEFAULTS: dict[str, float] = {
    "comparison_grid_width": 128.0,
    "cell_match_radius": 1.0,
    "cell_coarse_factor": 2.0,
    "cell_structure_relative_tolerance": 0.5,
    "aspect_tolerance": 0.02,
    "stability_max_mismatch_ratio": 0.002,
    "max_channel_delta": 8.0,
}
SCORE_THRESHOLD_KEYS = ("region_min_similarity", "global_min_similarity")
RATIO_THRESHOLD_KEYS = (
    "layout_offset_tolerance",
    "layout_size_tolerance",
    "aspect_tolerance",
    "stability_max_mismatch_ratio",
)
RELATIVE_THRESHOLD_KEYS = ("cell_structure_relative_tolerance",)
CHANNEL_THRESHOLD_KEYS = (
    "cell_color_tolerance",
    "cell_structure_tolerance",
    "layout_content_tolerance",
    "max_channel_delta",
)
DEFAULT_THRESHOLDS: dict[str, float] = {
    **TOLERANCE_PROFILES[DEFAULT_TOLERANCE_PROFILE],
    **SHARED_THRESHOLD_DEFAULTS,
}
MASK_POLICY: dict[str, float] = {
    "max_total_mask_ratio": 0.25,
    "max_region_mask_ratio": 0.5,
}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def to_mapping(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def union_area(rects: list[Rect]) -> int:
    usable = [rect for rect in rects if rect.area > 0]
    if not usable:
        return 0

    boundaries = sorted({value for rect in usable for value in (rect.y, rect.bottom)})
    total = 0
    for index in range(len(boundaries) - 1):
        top = boundaries[index]
        bottom = boundaries[index + 1]
        band_height = bottom - top
        if band_height <= 0:
            continue
        spans = sorted(
            (rect.x, rect.right) for rect in usable if rect.y <= top and rect.bottom >= bottom
        )
        merged_width = 0
        current_start = None
        current_end = None
        for start, end in spans:
            if current_end is None:
                current_start, current_end = start, end
                continue
            if start > current_end:
                merged_width += current_end - current_start
                current_start, current_end = start, end
            else:
                current_end = max(current_end, end)
        if current_end is not None:
            merged_width += current_end - current_start
        total += merged_width * band_height
    return total


def manifest_rects(manifest: dict[str, Any]) -> tuple[list[tuple[str, Rect, bool, float]], list[Rect]]:
    regions: list[tuple[str, Rect, bool, float]] = []
    for entry in manifest.get("regions") or []:
        if not isinstance(entry, dict):
            continue
        rect = rect_from_mapping(entry.get("rect"))
        if rect is None:
            continue
        weight = entry.get("weight", 1)
        regions.append(
            (
                str(entry.get("id") or ""),
                rect,
                bool(entry.get("required", True)),
                float(weight) if isinstance(weight, (int, float)) else 1.0,
            )
        )

    masks: list[Rect] = []
    for entry in manifest.get("dynamic_masks") or []:
        if not isinstance(entry, dict):
            continue
        rect = rect_from_mapping(entry.get("rect"))
        if rect is not None and rect.area > 0:
            masks.append(rect)
    return regions, masks


def derive_orientation(width: int, height: int) -> str:
    if width == height:
        return "square"
    return "portrait" if height > width else "landscape"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def resolve_viewport(viewport: dict[str, Any] | None, image_width: int, image_height: int) -> dict[str, Any]:
    source = dict(viewport or {})
    width = positive_int(source.get("width")) or image_width
    height = positive_int(source.get("height")) or image_height
    orientation = str(source.get("orientation") or "") or derive_orientation(width, height)
    resolved: dict[str, Any] = {
        "width": width,
        "height": height,
        "orientation": orientation,
        "dpi_policy": str(source.get("dpi_policy") or "reference_pixels"),
    }
    return resolved


def normalize_regions(regions: list[dict[str, Any]] | None, viewport: dict[str, Any]) -> list[dict[str, Any]]:
    if not regions:
        return [
            {
                "id": "full_screen",
                "rect": {
                    "x": 0,
                    "y": 0,
                    "width": int(viewport["width"]),
                    "height": int(viewport["height"]),
                },
                "required": True,
                "weight": 1,
            }
        ]

    normalized: list[dict[str, Any]] = []
    for entry in regions:
        if not isinstance(entry, dict):
            raise ToolInvocationError(
                "ui_reference_region_invalid",
                "Region entries must be objects with id and rect.",
                {"entry": entry},
            )
        rect = rect_from_mapping(entry.get("rect"))
        normalized.append(
            {
                "id": str(entry.get("id") or "").strip(),
                "rect": rect.to_mapping() if rect is not None else entry.get("rect"),
                "required": bool(entry.get("required", True)),
                "weight": entry.get("weight", 1),
            }
        )
    return normalized


def normalize_masks(masks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for entry in masks or []:
        if not isinstance(entry, dict):
            raise ToolInvocationError(
                "ui_reference_mask_invalid",
                "Mask entries must be objects with id, rect, and reason.",
                {"entry": entry},
            )
        rect = rect_from_mapping(entry.get("rect"))
        normalized.append(
            {
                "id": str(entry.get("id") or "").strip(),
                "rect": rect.to_mapping() if rect is not None else entry.get("rect"),
                "reason": str(entry.get("reason") or "").strip(),
            }
        )
    return normalized


def normalize_required_ui(required_ui: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for entry in required_ui or []:
        if not isinstance(entry, dict):
            raise ToolInvocationError(
                "ui_reference_required_ui_invalid",
                "required_ui entries must be objects with a selector.",
                {"entry": entry},
            )
        normalized.append({key: value for key, value in entry.items()})
    return normalized


def normalize_threshold_overrides(thresholds: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key): value for key, value in (thresholds or {}).items()}


def resolve_tolerances(manifest: dict[str, Any]) -> dict[str, float]:
    """Profile defaults, then explicit per-reference overrides. Never global magic numbers."""

    profile_name = str(manifest.get("tolerance_profile") or DEFAULT_TOLERANCE_PROFILE).strip().lower()
    profile = TOLERANCE_PROFILES.get(profile_name, TOLERANCE_PROFILES[DEFAULT_TOLERANCE_PROFILE])
    resolved: dict[str, float] = {**profile, **SHARED_THRESHOLD_DEFAULTS}
    overrides = manifest.get("thresholds")
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                resolved[str(key)] = float(value)
    resolved["comparison_grid_width"] = float(max(16, min(512, int(resolved["comparison_grid_width"]))))
    resolved["cell_match_radius"] = float(max(0, min(4, int(resolved["cell_match_radius"]))))
    resolved["cell_coarse_factor"] = float(max(1, min(8, int(resolved["cell_coarse_factor"]))))
    return resolved


def normalize_owner(owner: str) -> str:
    value = str(owner or "agent").strip().lower()
    return value


def normalize_acceptance(acceptance: dict[str, Any] | None) -> dict[str, Any]:
    resolved = dict(DEFAULT_LANE_REQUIREMENTS)
    for key, value in (acceptance or {}).items():
        if str(key) in LANES:
            resolved[str(key)] = str(value)
    return resolved


def normalize_required_interactions(required: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for entry in required or []:
        if not isinstance(entry, dict):
            raise ToolInvocationError(
                "ui_reference_required_interaction_invalid",
                "required_interactions entries must be objects with an id and a selector.",
                {"entry": entry},
            )
        normalized.append({key: value for key, value in entry.items()})
    return normalized


def rect_from_mapping(value: Any) -> Rect | None:
    if not isinstance(value, dict):
        return None
    try:
        return Rect(
            x=int(value.get("x", 0)),
            y=int(value.get("y", 0)),
            width=int(value.get("width", 0)),
            height=int(value.get("height", 0)),
        )
    except (TypeError, ValueError):
        return None


def clip_rect(rect: Rect, bounds: Rect) -> Rect:
    x = max(rect.x, bounds.x)
    y = max(rect.y, bounds.y)
    right = min(rect.right, bounds.right)
    bottom = min(rect.bottom, bounds.bottom)
    return Rect(x=x, y=y, width=max(0, right - x), height=max(0, bottom - y))


def positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    number = int(value)
    return number if number > 0 else 0


def issue(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}
