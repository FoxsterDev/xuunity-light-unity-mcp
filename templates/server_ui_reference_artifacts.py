from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from server_artifact_registry import repo_relative_path
from server_core import ToolInvocationError, write_json
from server_ui_reference_manifest import Rect
from server_ui_reference_png import RgbaImage, encode_png
from server_ui_reference_similarity import CellGrid

COMPARISON_SCHEMA_VERSION = "xuunity.ui-reference-comparison.v1"
DIFF_BASE_DIM_PERCENT = 35
GRID_OVERLAY_CELL_PIXELS = 6


def emit_comparison_artifacts(
    *,
    reference_dir: Path,
    workspace: Path,
    comparison_id: str,
    expected: RgbaImage,
    expected_source: Path,
    actual: RgbaImage,
    actual_source: Path,
    expected_grid: CellGrid,
    actual_grid: CellGrid,
    mismatch_cells: set[tuple[int, int]],
    mask_cells: list[Rect],
    regions: list[dict[str, Any]],
    comparison_space: dict[str, Any],
    global_metrics: dict[str, Any],
    clusters: list[dict[str, Any]],
    include_expected_copy: bool,
) -> list[dict[str, Any]]:
    output_dir = reference_dir / "comparisons" / comparison_id
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = [
        write_artifact_record(output_dir / "actual.png", actual_source.read_bytes(), workspace, "actual")
    ]

    if include_expected_copy:
        artifacts.append(
            write_artifact_record(output_dir / "expected.png", expected_source.read_bytes(), workspace, "expected")
        )

    if (expected.width, expected.height) == (actual.width, actual.height):
        overlay = RgbaImage(
            width=expected.width,
            height=expected.height,
            pixels=_overlay_pixels(expected.pixels, actual.pixels, expected.width * expected.height),
        )
        overlay_space = "pixel"
    else:
        overlay = _render_grid_overlay(expected_grid, actual_grid)
        overlay_space = "comparison_grid"
    overlay_artifact = write_artifact_record(output_dir / "overlay.png", encode_png(overlay), workspace, "overlay")
    overlay_artifact["render_space"] = overlay_space
    artifacts.append(overlay_artifact)

    diff = _render_diff_image(
        actual=actual,
        mismatch_cells=mismatch_cells,
        mask_cells=mask_cells,
        regions=regions,
        columns=int(comparison_space["columns"]),
        rows=int(comparison_space["rows"]),
    )
    artifacts.append(write_artifact_record(output_dir / "diff.png", encode_png(diff), workspace, "diff"))

    metrics_path = output_dir / "metrics.json"
    write_json(
        metrics_path,
        {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "comparison_id": comparison_id,
            "comparison_space": comparison_space,
            "global": global_metrics,
            "regions": regions,
            "mismatch_clusters": clusters,
        },
    )
    artifacts.append(
        write_artifact_record(metrics_path, metrics_path.read_bytes(), workspace, "metrics", already_written=True)
    )
    return artifacts


def write_artifact_record(
    path: Path,
    data: bytes,
    workspace: Path,
    role: str,
    *,
    already_written: bool = False,
) -> dict[str, Any]:
    if not already_written:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {
        "role": role,
        "path": str(path),
        "repo_relative_path": repo_relative_path(path, workspace),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _overlay_pixels(expected: bytes, actual: bytes, pixel_count: int) -> bytes:
    blended = bytearray(byte_average(expected, actual))
    blended[3::4] = b"\xff" * pixel_count
    return bytes(blended)


def byte_average(first: bytes, second: bytes) -> bytes:
    length = len(first)
    if length != len(second):
        raise ToolInvocationError(
            "ui_reference_internal_error",
            "Overlay requires two images of identical byte length.",
            {"first_bytes": length, "second_bytes": len(second)},
        )
    mask = int.from_bytes(b"\xfe" * length, "big")
    left = (int.from_bytes(first, "big") & mask) >> 1
    right = (int.from_bytes(second, "big") & mask) >> 1
    return (left + right).to_bytes(length, "big")


def _render_grid_overlay(expected_grid: CellGrid, actual_grid: CellGrid) -> RgbaImage:
    cell = GRID_OVERLAY_CELL_PIXELS
    width = expected_grid.columns * cell
    height = expected_grid.rows * cell
    buffer = bytearray(b"\xff" * (width * height * 4))

    for row in range(expected_grid.rows):
        row_pixels = bytearray()
        for column in range(expected_grid.columns):
            index = row * expected_grid.columns + column
            blended = bytes(
                (
                    (expected_grid.red[index] + actual_grid.red[index]) // 2,
                    (expected_grid.green[index] + actual_grid.green[index]) // 2,
                    (expected_grid.blue[index] + actual_grid.blue[index]) // 2,
                    255,
                )
            )
            row_pixels += blended * cell
        for offset in range(cell):
            start = ((row * cell + offset) * width) * 4
            buffer[start : start + width * 4] = row_pixels

    return RgbaImage(width=width, height=height, pixels=bytes(buffer))


def _render_diff_image(
    *,
    actual: RgbaImage,
    mismatch_cells: set[tuple[int, int]],
    mask_cells: list[Rect],
    regions: list[dict[str, Any]],
    columns: int,
    rows: int,
) -> RgbaImage:
    width = actual.width
    height = actual.height
    dim_table = bytes((value * DIFF_BASE_DIM_PERCENT) // 100 for value in range(256))
    buffer = bytearray(actual.pixels.translate(dim_table))
    buffer[3::4] = b"\xff" * (width * height)

    for cell_x, cell_y in mismatch_cells:
        _paint_cell(buffer, cell_x, cell_y, columns, rows, width, height, channel=0, value=225)
    for mask in mask_cells:
        for cell_y in range(mask.y, mask.bottom):
            for cell_x in range(mask.x, mask.right):
                _paint_cell(buffer, cell_x, cell_y, columns, rows, width, height, channel=2, value=180)

    for region in regions:
        if region.get("passed") is not False:
            continue
        cell_rect = region.get("cell_rect") or {}
        _outline_cells(buffer, cell_rect, columns=columns, rows=rows, width=width, height=height)

    return RgbaImage(width=width, height=height, pixels=bytes(buffer))


def _paint_cell(
    buffer: bytearray,
    cell_x: int,
    cell_y: int,
    columns: int,
    rows: int,
    width: int,
    height: int,
    *,
    channel: int,
    value: int,
) -> None:
    x0 = cell_x * width // columns
    x1 = max(x0 + 1, (cell_x + 1) * width // columns)
    y0 = cell_y * height // rows
    y1 = max(y0 + 1, (cell_y + 1) * height // rows)
    x1 = min(width, x1)
    y1 = min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return
    painted = bytes([value]) * (x1 - x0)
    for y in range(y0, y1):
        start = (y * width + x0) * 4 + channel
        buffer[start : start + (x1 - x0) * 4 : 4] = painted


def _outline_cells(
    buffer: bytearray,
    cell_rect: dict[str, Any],
    *,
    columns: int,
    rows: int,
    width: int,
    height: int,
) -> None:
    x0 = int(cell_rect.get("x", 0)) * width // columns
    y0 = int(cell_rect.get("y", 0)) * height // rows
    x1 = min(width, (int(cell_rect.get("x", 0)) + int(cell_rect.get("width", 0))) * width // columns)
    y1 = min(height, (int(cell_rect.get("y", 0)) + int(cell_rect.get("height", 0))) * height // rows)
    if x1 <= x0 or y1 <= y0:
        return

    span = x1 - x0
    for y in (y0, y1 - 1):
        start = (y * width + x0) * 4
        buffer[start : start + span * 4 : 4] = bytes([255]) * span
        buffer[start + 1 : start + 1 + span * 4 : 4] = bytes([220]) * span
        buffer[start + 2 : start + 2 + span * 4 : 4] = bytes([0]) * span
    for y in range(y0, y1):
        for x in (x0, x1 - 1):
            offset = (y * width + x) * 4
            buffer[offset] = 255
            buffer[offset + 1] = 220
            buffer[offset + 2] = 0
