from __future__ import annotations

from typing import Any


REQUIRED_DEVICE_FIELDS = ("model", "os", "resolution", "orientation", "build_revision")
CAPTURE_LANES = ("game_view", "device")


def normalize_device_context(device: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(device or {})
    resolution = _resolution(raw.get("resolution"))
    safe_area = _safe_area(raw.get("safe_area") or raw.get("safeArea"))

    context: dict[str, Any] = {
        "model": _text(raw, "model"),
        "os": _text(raw, "os"),
        "os_version": _text(raw, "os_version", "osVersion"),
        "resolution": resolution,
        "screen_scale": _number(raw.get("screen_scale", raw.get("screenScale"))),
        "orientation": _text(raw, "orientation").lower(),
        "safe_area_insets": safe_area,
        "build_revision": _text(raw, "build_revision", "buildRevision"),
        "notes": _text(raw, "notes"),
    }

    missing = [field for field in REQUIRED_DEVICE_FIELDS if not _present(context.get(field))]
    context["missing_fields"] = missing
    context["complete"] = not missing
    context["safe_area_declared"] = bool(safe_area)
    return context


def device_lane_state(
    *,
    capture_lane: str,
    acceptance_policy: dict[str, Any],
    device_context: dict[str, Any],
    capture_size: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requirement = str(acceptance_policy.get("device") or "not_required")
    if capture_lane != "device":
        return {
            "requirement": requirement,
            "status": "not_evaluated",
            "evidence": "comparison_ran_on_the_game_view_lane",
        }

    if not device_context.get("complete"):
        return {
            "requirement": requirement,
            "status": "blocked",
            "evidence": "device_context_incomplete",
            "missing_fields": list(device_context.get("missing_fields") or []),
        }

    device = f"{device_context['model']} / {device_context['os']} {device_context['os_version']}".strip()
    mismatch = _resolution_mismatch(device_context.get("resolution"), capture_size)
    if mismatch:
        return {
            "requirement": requirement,
            "status": "failed",
            "evidence": "declared_device_resolution_does_not_match_the_capture",
            "device": device,
            "failures": [mismatch],
        }

    return {
        "requirement": requirement,
        "status": "passed",
        "evidence": "device_capture_with_declared_device_context",
        "device": device,
    }


def _resolution_mismatch(
    declared: Any,
    capture_size: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(declared, dict) or not declared:
        return {}
    capture = capture_size if isinstance(capture_size, dict) else {}
    width = _positive_int(capture.get("width"))
    height = _positive_int(capture.get("height"))
    if width <= 0 or height <= 0:
        return {}
    if width == declared.get("width") and height == declared.get("height"):
        return {}
    return {
        "code": "device_resolution_mismatch",
        "message": (
            f"The device declares {declared.get('width')}x{declared.get('height')} but the capture is "
            f"{width}x{height}; the result cannot be attributed to the declared device configuration."
        ),
        "declared": dict(declared),
        "capture": {"width": width, "height": height},
    }


def device_lane_warnings(
    *,
    capture_lane: str,
    device_context: dict[str, Any],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if capture_lane != "device":
        return warnings

    if not device_context.get("complete"):
        warnings.append(
            {
                "code": "device_context_incomplete",
                "message": (
                    "A device capture must declare "
                    + ", ".join(REQUIRED_DEVICE_FIELDS)
                    + "; missing: "
                    + ", ".join(device_context.get("missing_fields") or [])
                    + ". Without them the result cannot be attributed to a device configuration."
                ),
            }
        )

    if not device_context.get("safe_area_declared"):
        warnings.append(
            {
                "code": "device_safe_area_undeclared",
                "message": (
                    "No safe-area insets were declared for this device capture, so notch and home-indicator "
                    "differences cannot be distinguished from layout defects."
                ),
            }
        )

    return warnings


def _resolution(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    width = _positive_int(raw.get("width"))
    height = _positive_int(raw.get("height"))
    if width <= 0 or height <= 0:
        return {}
    return {"width": width, "height": height}


def _safe_area(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    insets = {
        side: _positive_int(raw.get(side))
        for side in ("top", "bottom", "left", "right")
        if raw.get(side) is not None
    }
    return insets


def _present(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    return bool(str(value or "").strip())


def _text(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _positive_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))
