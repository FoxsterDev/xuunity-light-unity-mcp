from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from server_artifact_registry import (
    register_artifact,
    repo_relative_path,
    resolve_destination_root,
    resolve_workspace_root,
)
from server_core import ToolInvocationError, read_json, write_json
from server_ui_reference_manifest import (
    DEFAULT_REFERENCE_CATEGORY,
    DEFAULT_TOLERANCE_PROFILE,
    EXPECTED_IMAGE_FILE_NAME,
    MANIFEST_FILE_NAME,
    UI_REFERENCE_SCHEMA_VERSION,
    normalize_acceptance,
    normalize_masks,
    normalize_owner,
    normalize_regions,
    normalize_required_interactions,
    normalize_required_ui,
    normalize_threshold_overrides,
    positive_int,
    resolve_tolerances,
    resolve_viewport,
    utc_now,
)
from server_ui_reference_policy import validate_manifest
from server_ui_reference_png import read_png
from server_ui_vision_review import resolve_vision_policy

REFERENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
COMMON_CAPTURE_SCALES = ((1, 1), (3, 4), (2, 3), (1, 2), (1, 3))


def register_ui_reference(
    *,
    project_root: Path,
    reference_id: str,
    source_image: str,
    viewport: dict[str, Any] | None = None,
    safe_area: str = "full_screen",
    fixture: str = "",
    regions: list[dict[str, Any]] | None = None,
    dynamic_masks: list[dict[str, Any]] | None = None,
    required_ui: list[dict[str, Any]] | None = None,
    required_interactions: list[dict[str, Any]] | None = None,
    vision_policy: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    tolerance_profile: str = DEFAULT_TOLERANCE_PROFILE,
    scale_policy: str = "aspect_scale",
    owner: str = "agent",
    acceptance: dict[str, Any] | None = None,
    notes: str = "",
    category: str = DEFAULT_REFERENCE_CATEGORY,
    workspace_root: str = "",
    overwrite: bool = False,
    register_in_artifact_registry: bool = True,
) -> dict[str, Any]:
    workspace = resolve_workspace_root(project_root, workspace_root)
    normalized_id = normalize_reference_id(reference_id)
    reference_dir = reference_directory(
        project_root=project_root,
        workspace_root=workspace,
        reference_id=normalized_id,
        category=category,
    )
    manifest_path = reference_dir / MANIFEST_FILE_NAME
    if manifest_path.exists() and not overwrite:
        raise ToolInvocationError(
            "ui_reference_already_registered",
            (
                f"Reference '{normalized_id}' is already registered. Pass overwrite=true only when the "
                "supplied design reference itself changed."
            ),
            {"reference_id": normalized_id, "manifest_path": str(manifest_path)},
        )

    source_path = Path(source_image).expanduser()
    if not source_path.is_absolute():
        source_path = (workspace / source_path).resolve()
    if not source_path.is_file():
        raise ToolInvocationError(
            "ui_reference_source_image_missing",
            f"Supplied reference image '{source_image}' was not found.",
            {"source_image": str(source_path)},
        )

    source_bytes = source_path.read_bytes()
    image = read_png(source_path, source=str(source_path))
    resolved_viewport = resolve_viewport(viewport, image.width, image.height)

    expected_path = reference_dir / EXPECTED_IMAGE_FILE_NAME
    expected_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the bytes we are about to replace: validation happens after the write (it re-hashes the
    # published image), so a rejected re-registration has to put the previous one back or it leaves
    # a live reference with a manifest and no image.
    previous_expected = expected_path.read_bytes() if expected_path.is_file() else None
    expected_path.write_bytes(source_bytes)

    manifest = {
        "schema_version": UI_REFERENCE_SCHEMA_VERSION,
        "reference_id": normalized_id,
        "registered_at_utc": utc_now(),
        "expected_image": {
            "file_name": EXPECTED_IMAGE_FILE_NAME,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_bytes": len(source_bytes),
            "width": image.width,
            "height": image.height,
            "source_path": str(source_path),
        },
        "viewport": resolved_viewport,
        "safe_area": str(safe_area or "full_screen"),
        "fixture": str(fixture or ""),
        "regions": normalize_regions(regions, resolved_viewport),
        "dynamic_masks": normalize_masks(dynamic_masks),
        "required_ui": normalize_required_ui(required_ui),
        "required_interactions": normalize_required_interactions(required_interactions),
        "vision_policy": dict(vision_policy or {}),
        "tolerance_profile": str(tolerance_profile or DEFAULT_TOLERANCE_PROFILE).strip().lower(),
        "scale_policy": str(scale_policy or "aspect_scale").strip().lower(),
        "thresholds": normalize_threshold_overrides(thresholds),
        "owner": normalize_owner(owner),
        "acceptance": normalize_acceptance(acceptance),
        "normalization": {"mode": "resolution_independent_cell_grid"},
        "notes": str(notes or ""),
    }

    validation = validate_manifest(manifest, reference_dir=reference_dir)
    if not validation["valid"]:
        if previous_expected is None:
            expected_path.unlink(missing_ok=True)
        else:
            expected_path.write_bytes(previous_expected)
        raise ToolInvocationError(
            "ui_reference_manifest_invalid",
            "The reference manifest failed policy validation and was not registered.",
            {
                "reference_id": normalized_id,
                "errors": validation["errors"],
                "previous_reference_restored": previous_expected is not None,
            },
        )

    write_json(manifest_path, manifest)

    payload: dict[str, Any] = {
        "schema_version": UI_REFERENCE_SCHEMA_VERSION,
        "reference_id": normalized_id,
        "manifest_path": str(manifest_path),
        "manifest_repo_relative_path": repo_relative_path(manifest_path, workspace),
        "reference_dir": str(reference_dir),
        "expected_image_path": str(expected_path),
        "expected_image": dict(manifest["expected_image"]),
        "viewport": dict(resolved_viewport),
        "region_ids": [str(region["id"]) for region in manifest["regions"]],
        "mask_ids": [str(mask["id"]) for mask in manifest["dynamic_masks"]],
        "fixture": manifest["fixture"],
        "owner": manifest["owner"],
        "acceptance": dict(manifest["acceptance"]),
        "required_interaction_ids": [
            str(entry.get("id") or "") for entry in manifest["required_interactions"]
        ],
        "vision_policy": resolve_vision_policy(manifest),
        "tolerance_profile": manifest["tolerance_profile"],
        "scale_policy": manifest["scale_policy"],
        "resolved_tolerances": resolve_tolerances(manifest),
        "recommended_capture_resolutions": recommended_capture_resolutions(resolved_viewport),
        "validation": validation,
    }

    if register_in_artifact_registry:
        record = register_artifact(
            project_root=project_root,
            artifact_path=str(manifest_path),
            destination="repo_artifact",
            kind="ui_reference_manifest",
            producer="xuunity_ui_reference_register",
            artifact_schema_version=UI_REFERENCE_SCHEMA_VERSION,
            metadata={
                "reference_id": normalized_id,
                "fixture": manifest["fixture"],
                "viewport": dict(resolved_viewport),
                "expected_image_sha256": manifest["expected_image"]["sha256"],
            },
            workspace_root=str(workspace),
        )
        payload["artifact_registry_path"] = record.get("registry_path", "")

    return payload


def validate_ui_reference(
    *,
    project_root: Path,
    reference_id: str = "",
    manifest_path: str = "",
    category: str = DEFAULT_REFERENCE_CATEGORY,
    workspace_root: str = "",
) -> dict[str, Any]:
    loaded = load_ui_reference(
        project_root=project_root,
        reference_id=reference_id,
        manifest_path=manifest_path,
        category=category,
        workspace_root=workspace_root,
    )
    validation = validate_manifest(loaded["manifest"], reference_dir=Path(loaded["reference_dir"]))
    return {
        "schema_version": UI_REFERENCE_SCHEMA_VERSION,
        "reference_id": str(loaded["manifest"].get("reference_id") or ""),
        "manifest_path": loaded["manifest_path"],
        "reference_dir": loaded["reference_dir"],
        "viewport": dict(loaded["manifest"].get("viewport") or {}),
        "fixture": str(loaded["manifest"].get("fixture") or ""),
        "owner": str(loaded["manifest"].get("owner") or ""),
        "acceptance": dict(loaded["manifest"].get("acceptance") or {}),
        "tolerance_profile": str(loaded["manifest"].get("tolerance_profile") or DEFAULT_TOLERANCE_PROFILE),
        "scale_policy": str(loaded["manifest"].get("scale_policy") or "aspect_scale"),
        "resolved_tolerances": resolve_tolerances(loaded["manifest"]),
        "recommended_capture_resolutions": recommended_capture_resolutions(
            dict(loaded["manifest"].get("viewport") or {})
        ),
        "validation": validation,
    }


def load_ui_reference(
    *,
    project_root: Path,
    reference_id: str = "",
    manifest_path: str = "",
    category: str = DEFAULT_REFERENCE_CATEGORY,
    workspace_root: str = "",
) -> dict[str, Any]:
    workspace = resolve_workspace_root(project_root, workspace_root)
    if manifest_path.strip():
        resolved = Path(manifest_path).expanduser()
        if not resolved.is_absolute():
            resolved = (workspace / resolved).resolve()
    else:
        normalized_id = normalize_reference_id(reference_id)
        resolved = (
            reference_directory(
                project_root=project_root,
                workspace_root=workspace,
                reference_id=normalized_id,
                category=category,
            )
            / MANIFEST_FILE_NAME
        )

    if not resolved.is_file():
        raise ToolInvocationError(
            "ui_reference_not_registered",
            (
                f"No ui-reference.v1 manifest at '{resolved}'. Register the supplied design reference "
                "before comparing a capture against it."
            ),
            {"manifest_path": str(resolved), "reference_id": reference_id},
        )

    manifest = read_json(resolved)
    if not isinstance(manifest, dict):
        raise ToolInvocationError(
            "ui_reference_manifest_invalid",
            f"Manifest '{resolved}' is not a JSON object.",
            {"manifest_path": str(resolved)},
        )

    return {
        "manifest": manifest,
        "manifest_path": str(resolved),
        "reference_dir": str(resolved.parent),
        "workspace_root": str(workspace),
    }


def reference_directory(
    *,
    project_root: Path,
    workspace_root: Path,
    reference_id: str,
    category: str = DEFAULT_REFERENCE_CATEGORY,
) -> Path:
    root = resolve_destination_root(
        project_root=project_root,
        workspace_root=workspace_root,
        destination="repo_artifact",
        category=category or DEFAULT_REFERENCE_CATEGORY,
    )
    return root / reference_id


def normalize_reference_id(reference_id: str) -> str:
    value = str(reference_id or "").strip()
    if not REFERENCE_ID_PATTERN.match(value):
        raise ToolInvocationError(
            "ui_reference_id_invalid",
            (
                "Reference id must be 1-80 characters of letters, digits, dot, dash, or underscore and "
                "start with a letter or digit."
            ),
            {"reference_id": value},
        )
    return value


def recommended_capture_resolutions(viewport: dict[str, Any]) -> list[dict[str, Any]]:
    """Same-aspect Game View resolutions an operator may capture at instead of the reference size."""

    width = positive_int(viewport.get("width"))
    height = positive_int(viewport.get("height"))
    if width <= 0 or height <= 0:
        return []
    resolutions: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for numerator, denominator in COMMON_CAPTURE_SCALES:
        if (width * numerator) % denominator or (height * numerator) % denominator:
            continue
        scaled = (width * numerator // denominator, height * numerator // denominator)
        if scaled in seen or scaled[0] < 64 or scaled[1] < 64:
            continue
        seen.add(scaled)
        resolutions.append(
            {
                "width": scaled[0],
                "height": scaled[1],
                "scale": round(numerator / denominator, 4),
                "exact_aspect": True,
            }
        )
    return resolutions
