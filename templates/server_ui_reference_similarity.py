from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate
from typing import Any

from server_ui_reference_manifest import Rect, clip_rect, union_area
from server_ui_reference_png import RgbaImage

CLUSTER_CELL_SIZE = 32
MAX_REPORTED_CLUSTERS = 8
CHUNK_PIXELS = 64


@dataclass(frozen=True)
class CellGrid:
    """Resolution-independent comparison grid.

    Each cell holds the exact mean colour of its screen area plus the local contrast against
    its neighbours, so two captures of different resolutions become directly comparable and
    sub-cell antialiasing or resampling noise cannot decide a verdict.
    """

    columns: int
    rows: int
    red: list[int]
    green: list[int]
    blue: list[int]
    luma: list[int]
    contrast: list[int]
    source_width: int
    source_height: int

    @property
    def cell_count(self) -> int:
        return self.columns * self.rows

    def describe(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "cell_count": self.cell_count,
            "cell_statistic": "exact_box_average_plus_local_contrast",
            "source_width": self.source_width,
            "source_height": self.source_height,
        }


def build_cell_grid(image: RgbaImage, *, columns: int, rows: int) -> CellGrid:
    """Exact per-cell box average plus a local-contrast signal.

    Averaging every pixel of a cell is what makes two captures of different resolutions
    comparable: the same screen area yields the same cell mean whether it was rendered at
    1440x3200 or 1080x2400. The contrast signal is derived from neighbouring cell means,
    so it is resolution independent for the same reason.
    """

    pixels = image.pixels
    width = image.width
    height = image.height
    columns = max(1, min(columns, width))
    rows = max(1, min(rows, height))

    # Area weights in exact integer arithmetic. A cell spans source x from c*width/columns to
    # (c+1)*width/columns; scaling by `columns` makes both the cell edges and the pixel edges
    # integers, so a pixel straddling a cell boundary contributes to both cells in proportion to
    # the overlap instead of landing wholly in one of them. Without this the cell means are phase
    # dependent and the identical design captured at 2x scores as a mismatch.
    column_spans = _axis_spans(width, columns)
    row_spans = _axis_spans(height, rows)

    cell_count = columns * rows
    sum_r = [0] * cell_count
    sum_g = [0] * cell_count
    sum_b = [0] * cell_count
    stride = width * 4

    row_touch: list[list[tuple[int, int]]] = [[] for _ in range(height)]
    for row_index, (first, last, weights) in enumerate(row_spans):
        for offset, weight in enumerate(weights):
            row_touch[first + offset].append((row_index, weight))

    for y in range(height):
        touched = row_touch[y]
        if not touched:
            continue
        row = pixels[y * stride : (y + 1) * stride]
        prefix_r = list(accumulate(row[0::4], initial=0))
        prefix_g = list(accumulate(row[1::4], initial=0))
        prefix_b = list(accumulate(row[2::4], initial=0))
        line_r = [0] * columns
        line_g = [0] * columns
        line_b = [0] * columns
        for column, (first, last, weights) in enumerate(column_spans):
            total_r = 0
            total_g = 0
            total_b = 0
            for offset, weight in enumerate(weights):
                x = first + offset
                if weight == columns:
                    continue
                total_r += weight * row[x * 4]
                total_g += weight * row[x * 4 + 1]
                total_b += weight * row[x * 4 + 2]
            full_start = first + (1 if weights[0] != columns else 0)
            full_end = last + 1 - (1 if len(weights) > 1 and weights[-1] != columns else 0)
            if full_end > full_start:
                total_r += columns * (prefix_r[full_end] - prefix_r[full_start])
                total_g += columns * (prefix_g[full_end] - prefix_g[full_start])
                total_b += columns * (prefix_b[full_end] - prefix_b[full_start])
            line_r[column] = total_r
            line_g[column] = total_g
            line_b[column] = total_b
        for row_index, row_weight in touched:
            base = row_index * columns
            for column in range(columns):
                index = base + column
                sum_r[index] += row_weight * line_r[column]
                sum_g[index] += row_weight * line_g[column]
                sum_b[index] += row_weight * line_b[column]

    red = [0] * cell_count
    green = [0] * cell_count
    blue = [0] * cell_count
    luma = [0] * cell_count
    # Column weights sum to `width` per cell and row weights to `height`, so the total weight
    # behind every cell mean is exactly width*height regardless of where the cell edges fall.
    denominator = max(1, width * height)
    for index in range(cell_count):
        mean_r = sum_r[index] // denominator
        mean_g = sum_g[index] // denominator
        mean_b = sum_b[index] // denominator
        red[index] = mean_r
        green[index] = mean_g
        blue[index] = mean_b
        luma[index] = (mean_r * 299 + mean_g * 587 + mean_b * 114) // 1000

    contrast = [0] * cell_count
    for row_index in range(rows):
        base = row_index * columns
        for column in range(columns):
            index = base + column
            value = luma[index]
            right = luma[index + 1] if column + 1 < columns else value
            below = luma[index + columns] if row_index + 1 < rows else value
            contrast[index] = min(255, abs(value - right) + abs(value - below))

    return CellGrid(
        columns=columns,
        rows=rows,
        red=red,
        green=green,
        blue=blue,
        luma=luma,
        contrast=contrast,
        source_width=width,
        source_height=height,
    )


def _axis_spans(length: int, cells: int) -> list[tuple[int, int, list[int]]]:
    """Per-cell source range and exact overlap weights, in units of 1/`cells` of a pixel.

    Weights for one cell sum to `length`; a pixel wholly inside a cell weighs `cells`."""

    spans: list[tuple[int, int, list[int]]] = []
    for index in range(cells):
        low = index * length
        high = (index + 1) * length
        first = low // cells
        last = (high - 1) // cells
        weights = [
            max(0, min(high, (pixel + 1) * cells) - max(low, pixel * cells))
            for pixel in range(first, last + 1)
        ]
        spans.append((first, last, weights))
    return spans


def build_coarse_grid(grid: CellGrid, factor: int) -> CellGrid | None:
    """Block-average the fine grid so a mismatch must survive a coarser scale too.

    High-frequency content (body text, dithered art) lands on different cell boundaries when the
    capture resolution differs from the reference. The local average over a block is stable under
    that phase shift, while a genuinely different colour, sprite, or missing element is not."""

    if factor <= 1:
        return None
    columns = -(-grid.columns // factor)
    rows = -(-grid.rows // factor)
    count = columns * rows
    sum_r = [0] * count
    sum_g = [0] * count
    sum_b = [0] * count
    sum_contrast = [0] * count
    totals = [0] * count

    for cell_y in range(grid.rows):
        block_base = (cell_y // factor) * columns
        row_base = cell_y * grid.columns
        for cell_x in range(grid.columns):
            index = row_base + cell_x
            block = block_base + cell_x // factor
            sum_r[block] += grid.red[index]
            sum_g[block] += grid.green[index]
            sum_b[block] += grid.blue[index]
            sum_contrast[block] += grid.contrast[index]
            totals[block] += 1

    red = [sum_r[index] // max(1, totals[index]) for index in range(count)]
    green = [sum_g[index] // max(1, totals[index]) for index in range(count)]
    blue = [sum_b[index] // max(1, totals[index]) for index in range(count)]
    contrast = [sum_contrast[index] // max(1, totals[index]) for index in range(count)]
    luma = [(red[index] * 299 + green[index] * 587 + blue[index] * 114) // 1000 for index in range(count)]
    return CellGrid(
        columns=columns,
        rows=rows,
        red=red,
        green=green,
        blue=blue,
        luma=luma,
        contrast=contrast,
        source_width=grid.source_width,
        source_height=grid.source_height,
    )


def grid_rect(rect: Rect, *, reference_width: int, reference_height: int, columns: int, rows: int) -> Rect:
    x0 = (rect.x * columns) // max(1, reference_width)
    y0 = (rect.y * rows) // max(1, reference_height)
    x1 = -(-rect.right * columns // max(1, reference_width))
    y1 = -(-rect.bottom * rows // max(1, reference_height))
    x0 = max(0, min(columns - 1, x0))
    y0 = max(0, min(rows - 1, y0))
    x1 = max(x0 + 1, min(columns, x1))
    y1 = max(y0 + 1, min(rows, y1))
    return Rect(x=x0, y=y0, width=x1 - x0, height=y1 - y0)


def compare_region(
    expected: CellGrid,
    actual: CellGrid,
    *,
    rect: Rect,
    mask_rects: list[Rect],
    tolerances: dict[str, float],
) -> dict[str, Any]:
    """Score one region on two independent, explainable lanes: cell colour and cell detail.

    A cell counts as matching when it matches its reference cell or any reference cell within
    `cell_match_radius`. That tolerates sub-cell layout jitter and the sampling phase shift that
    a different capture resolution necessarily introduces, without hiding real differences: a
    moved or resized element is caught by the separate layout lane.
    """

    color_tolerance = float(tolerances["cell_color_tolerance"])
    structure_tolerance = float(tolerances["cell_structure_tolerance"])
    structure_relative = float(tolerances.get("cell_structure_relative_tolerance", 0.5))
    radius = int(tolerances.get("cell_match_radius", 1))
    coarse_factor = int(tolerances.get("cell_coarse_factor", 2))
    coarse_expected = build_coarse_grid(expected, coarse_factor)
    coarse_actual = build_coarse_grid(actual, coarse_factor)

    color_deltas: list[int] = []
    structure_deltas: list[int] = []
    color_mismatch_cells: list[tuple[int, int]] = []
    structure_mismatch_cells: list[tuple[int, int]] = []
    masked_cells = 0

    columns = expected.columns
    rows = expected.rows

    for cell_y in range(rect.y, rect.bottom):
        for cell_x in range(rect.x, rect.right):
            if _cell_in_any(cell_x, cell_y, mask_rects):
                masked_cells += 1
                continue

            index = cell_y * columns + cell_x
            actual_r = actual.red[index]
            actual_g = actual.green[index]
            actual_b = actual.blue[index]
            actual_contrast = actual.contrast[index]

            color_delta = _color_delta(expected, index, actual_r, actual_g, actual_b)
            structure_delta = abs(expected.contrast[index] - actual_contrast)

            if radius > 0 and color_delta > color_tolerance:
                color_delta = min(
                    color_delta,
                    min(
                        (
                            _color_delta(expected, neighbour, actual_r, actual_g, actual_b)
                            for neighbour in _neighbours(cell_x, cell_y, radius, columns, rows)
                        ),
                        default=color_delta,
                    ),
                )
            if radius > 0 and _structure_mismatch(
                structure_delta, expected.contrast[index], actual_contrast, structure_tolerance, structure_relative
            ):
                for neighbour in _neighbours(cell_x, cell_y, radius, columns, rows):
                    candidate = abs(expected.contrast[neighbour] - actual_contrast)
                    if candidate < structure_delta:
                        structure_delta = candidate
                        if not _structure_mismatch(
                            structure_delta,
                            expected.contrast[neighbour],
                            actual_contrast,
                            structure_tolerance,
                            structure_relative,
                        ):
                            break

            color_mismatch = color_delta > color_tolerance
            structure_mismatch = _structure_mismatch(
                structure_delta,
                expected.contrast[index],
                actual_contrast,
                structure_tolerance,
                structure_relative,
            )

            if (color_mismatch or structure_mismatch) and coarse_expected is not None:
                block = (cell_y // coarse_factor) * coarse_expected.columns + cell_x // coarse_factor
                if color_mismatch:
                    coarse_color_delta = _color_delta(
                        coarse_expected,
                        block,
                        coarse_actual.red[block],
                        coarse_actual.green[block],
                        coarse_actual.blue[block],
                    )
                    if coarse_color_delta <= color_tolerance:
                        color_mismatch = False
                        color_delta = min(color_delta, coarse_color_delta)
                if structure_mismatch:
                    coarse_structure_delta = abs(
                        coarse_expected.contrast[block] - coarse_actual.contrast[block]
                    )
                    if not _structure_mismatch(
                        coarse_structure_delta,
                        coarse_expected.contrast[block],
                        coarse_actual.contrast[block],
                        structure_tolerance,
                        structure_relative,
                    ):
                        structure_mismatch = False
                        structure_delta = min(structure_delta, coarse_structure_delta)

            color_deltas.append(color_delta)
            structure_deltas.append(structure_delta)
            if color_mismatch:
                color_mismatch_cells.append((cell_x, cell_y))
            if structure_mismatch:
                structure_mismatch_cells.append((cell_x, cell_y))

    compared = len(color_deltas)
    if compared == 0:
        return {
            "comparable": False,
            "cells_total": rect.area,
            "cells_masked": masked_cells,
            "cells_compared": 0,
            "color_score": None,
            "structure_score": None,
            "similarity_score": None,
            "mismatch_cells": [],
        }

    color_score = 1.0 - len(color_mismatch_cells) / compared
    structure_score = 1.0 - len(structure_mismatch_cells) / compared
    return {
        "comparable": True,
        "cells_total": rect.area,
        "cells_masked": masked_cells,
        "cells_compared": compared,
        "color_mismatch_cells": len(color_mismatch_cells),
        "structure_mismatch_cells": len(structure_mismatch_cells),
        "color_score": round(color_score, 6),
        "structure_score": round(structure_score, 6),
        "similarity_score": round(min(color_score, structure_score), 6),
        "mean_color_delta": round(sum(color_deltas) / compared, 3),
        "p95_color_delta": _percentile(color_deltas, 95),
        "max_color_delta": max(color_deltas),
        "mean_structure_delta": round(sum(structure_deltas) / compared, 3),
        "max_structure_delta": max(structure_deltas),
        "mismatch_cells": sorted(set(color_mismatch_cells) | set(structure_mismatch_cells)),
    }


def _color_delta(expected: CellGrid, index: int, red: int, green: int, blue: int) -> int:
    return max(
        abs(expected.red[index] - red),
        abs(expected.green[index] - green),
        abs(expected.blue[index] - blue),
    )


def _structure_mismatch(
    delta: int,
    expected_contrast: int,
    actual_contrast: int,
    tolerance: float,
    relative_tolerance: float,
) -> bool:
    """Detail differs when the absolute gap exceeds the tolerance AND it is a large share of the
    busier cell. Busy-versus-busy cells may differ in edge intensity; busy-versus-flat may not."""

    if delta <= tolerance:
        return False
    busiest = max(expected_contrast, actual_contrast, 1)
    return delta > relative_tolerance * busiest


def _neighbours(cell_x: int, cell_y: int, radius: int, columns: int, rows: int):
    for offset_y in range(-radius, radius + 1):
        neighbour_y = cell_y + offset_y
        if not 0 <= neighbour_y < rows:
            continue
        for offset_x in range(-radius, radius + 1):
            neighbour_x = cell_x + offset_x
            if (offset_x == 0 and offset_y == 0) or not 0 <= neighbour_x < columns:
                continue
            yield neighbour_y * columns + neighbour_x


def compare_layout(
    expected: CellGrid,
    actual: CellGrid,
    *,
    rect: Rect,
    mask_rects: list[Rect],
    tolerances: dict[str, float],
) -> dict[str, Any]:
    content_tolerance = float(tolerances["layout_content_tolerance"])
    offset_tolerance = float(tolerances["layout_offset_tolerance"])
    size_tolerance = float(tolerances["layout_size_tolerance"])

    expected_box = _content_box(expected, rect=rect, mask_rects=mask_rects, content_tolerance=content_tolerance)
    actual_box = _content_box(actual, rect=rect, mask_rects=mask_rects, content_tolerance=content_tolerance)

    if expected_box is None and actual_box is None:
        return {
            "evaluated": False,
            "passed": True,
            "reason": "region_has_no_distinct_content_in_either_capture",
        }
    if expected_box is None:
        return {
            "evaluated": True,
            "passed": False,
            "reason": "unexpected_content",
            "message": "The capture shows content in a region the reference leaves empty.",
        }
    if actual_box is None:
        return {
            "evaluated": True,
            "passed": False,
            "reason": "content_missing",
            "message": "The reference shows content in this region but the capture renders none.",
        }

    offset_x = (actual_box.x - expected_box.x) / rect.width
    offset_y = (actual_box.y - expected_box.y) / rect.height
    width_ratio = actual_box.width / expected_box.width
    height_ratio = actual_box.height / expected_box.height

    passed = (
        abs(offset_x) <= offset_tolerance
        and abs(offset_y) <= offset_tolerance
        and abs(width_ratio - 1.0) <= size_tolerance
        and abs(height_ratio - 1.0) <= size_tolerance
    )
    return {
        "evaluated": True,
        "passed": passed,
        "reason": "" if passed else "content_moved_or_resized",
        "offset_x_ratio": round(offset_x, 4),
        "offset_y_ratio": round(offset_y, 4),
        "width_ratio": round(width_ratio, 4),
        "height_ratio": round(height_ratio, 4),
        "offset_tolerance": offset_tolerance,
        "size_tolerance": size_tolerance,
        "expected_content_box": expected_box.to_mapping(),
        "actual_content_box": actual_box.to_mapping(),
    }


def _content_box(
    grid: CellGrid,
    *,
    rect: Rect,
    mask_rects: list[Rect],
    content_tolerance: float,
) -> Rect | None:
    background = _background_colour(grid, rect=rect, mask_rects=mask_rects)
    if background is None:
        return None

    min_x = min_y = None
    max_x = max_y = None
    for cell_y in range(rect.y, rect.bottom):
        for cell_x in range(rect.x, rect.right):
            if _cell_in_any(cell_x, cell_y, mask_rects):
                continue
            index = cell_y * grid.columns + cell_x
            distance = max(
                abs(grid.red[index] - background[0]),
                abs(grid.green[index] - background[1]),
                abs(grid.blue[index] - background[2]),
            )
            if distance <= content_tolerance:
                continue
            min_x = cell_x if min_x is None else min(min_x, cell_x)
            max_x = cell_x if max_x is None else max(max_x, cell_x)
            min_y = cell_y if min_y is None else min(min_y, cell_y)
            max_y = cell_y if max_y is None else max(max_y, cell_y)

    if min_x is None:
        return None
    return Rect(x=min_x, y=min_y, width=max_x - min_x + 1, height=max_y - min_y + 1)


def content_coverage(
    expected: CellGrid,
    actual: CellGrid,
    *,
    rect: Rect,
    mask_rects: list[Rect],
    content_tolerance: float,
) -> dict[str, Any]:
    """How much of the reference's content the capture still renders, counted in cells.

    Deliberately independent of area. A mismatched-cell fraction dilutes a missing element by the
    share of the screen it occupied, so a whole missing button or body paragraph can sit inside a
    coarse region and still score above the similarity floor. Counting content cells does not
    dilute: content that is absent is absent whatever fraction of the screen it covered."""

    background = _background_colour(expected, rect=rect, mask_rects=mask_rects)
    if background is None:
        return {"evaluated": False, "reason": "region_has_no_comparable_cells"}

    expected_cells: list[tuple[int, int]] = []
    actual_content: set[tuple[int, int]] = set()
    for cell_y in range(rect.y, rect.bottom):
        for cell_x in range(rect.x, rect.right):
            if _cell_in_any(cell_x, cell_y, mask_rects):
                continue
            index = cell_y * expected.columns + cell_x
            if _colour_distance(expected, index, background) > content_tolerance:
                expected_cells.append((cell_x, cell_y))
            if _colour_distance(actual, index, background) > content_tolerance:
                actual_content.add((cell_x, cell_y))

    if not expected_cells:
        return {"evaluated": False, "reason": "reference_region_has_no_distinct_content"}

    # One cell of slop, matching the neighbourhood tolerance the colour lane already grants, so a
    # sub-cell shift is not read as deleted content.
    covered = 0
    for cell_x, cell_y in expected_cells:
        if any(
            (cell_x + dx, cell_y + dy) in actual_content
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
        ):
            covered += 1

    ratio = covered / len(expected_cells)
    return {
        "evaluated": True,
        "expected_content_cells": len(expected_cells),
        "rendered_content_cells": covered,
        "coverage_ratio": round(ratio, 6),
    }


def _background_colour(
    grid: CellGrid,
    *,
    rect: Rect,
    mask_rects: list[Rect],
) -> tuple[int, int, int] | None:
    """The dominant colour of the region, as a colour that actually occurs in it.

    Taking an independent median per channel invents a colour the image never contains — the red
    of one element with the green of another — against which every real cell reads as content."""

    buckets: dict[tuple[int, int, int], list[int]] = {}
    for cell_y in range(rect.y, rect.bottom):
        for cell_x in range(rect.x, rect.right):
            if _cell_in_any(cell_x, cell_y, mask_rects):
                continue
            index = cell_y * grid.columns + cell_x
            red = grid.red[index]
            green = grid.green[index]
            blue = grid.blue[index]
            key = (red >> 4, green >> 4, blue >> 4)
            entry = buckets.get(key)
            if entry is None:
                buckets[key] = [1, red, green, blue]
            else:
                entry[0] += 1
                entry[1] += red
                entry[2] += green
                entry[3] += blue
    if not buckets:
        return None
    dominant = max(buckets.values(), key=lambda entry: entry[0])
    count = max(1, dominant[0])
    return (dominant[1] // count, dominant[2] // count, dominant[3] // count)


def _colour_distance(grid: CellGrid, index: int, background: tuple[int, int, int]) -> int:
    return max(
        abs(grid.red[index] - background[0]),
        abs(grid.green[index] - background[1]),
        abs(grid.blue[index] - background[2]),
    )


def cluster_mismatch_cells(
    cells: set[tuple[int, int]],
    *,
    regions: list[dict[str, Any]],
    grid_columns: int,
    grid_rows: int,
    reference_width: int,
    reference_height: int,
) -> list[dict[str, Any]]:
    remaining = set(cells)
    clusters: list[dict[str, Any]] = []

    while remaining:
        seed = next(iter(remaining))
        stack = [seed]
        members: list[tuple[int, int]] = []
        while stack:
            key = stack.pop()
            if key not in remaining:
                continue
            remaining.discard(key)
            members.append(key)
            cell_x, cell_y = key
            for neighbour in (
                (cell_x + 1, cell_y),
                (cell_x - 1, cell_y),
                (cell_x, cell_y + 1),
                (cell_x, cell_y - 1),
            ):
                if neighbour in remaining:
                    stack.append(neighbour)

        min_x = min(member[0] for member in members)
        max_x = max(member[0] for member in members)
        min_y = min(member[1] for member in members)
        max_y = max(member[1] for member in members)
        pixel_rect = {
            "x": min_x * reference_width // grid_columns,
            "y": min_y * reference_height // grid_rows,
            "width": max(1, ((max_x + 1) - min_x) * reference_width // grid_columns),
            "height": max(1, ((max_y + 1) - min_y) * reference_height // grid_rows),
        }
        clusters.append(
            {
                "cell_rect": {"x": min_x, "y": min_y, "width": max_x - min_x + 1, "height": max_y - min_y + 1},
                "reference_rect": pixel_rect,
                "cell_count": len(members),
                "region_ids": [
                    str(region["region_id"])
                    for region in regions
                    if _rects_overlap(pixel_rect, region.get("rect") or {})
                ],
            }
        )

    clusters.sort(key=lambda item: int(item["cell_count"]), reverse=True)
    reported = clusters[:MAX_REPORTED_CLUSTERS]
    for cluster in reported:
        cluster["additional_cluster_count"] = max(0, len(clusters) - len(reported))
    return reported


def measure_pixel_lane(
    *,
    expected: RgbaImage,
    actual: RgbaImage,
    bounds: Rect,
    masks: list[Rect],
    max_channel_delta: int,
) -> dict[str, Any]:
    """Exact per-pixel diagnostics. Only meaningful when both captures share a resolution;
    reported as supporting evidence and never used as the acceptance verdict."""

    width = expected.width
    expected_pixels = expected.pixels
    actual_pixels = actual.pixels
    masked_total = union_area([clip_rect(mask, bounds) for mask in masks])

    mismatched = 0
    delta_sum = 0
    max_delta = 0

    for y in range(expected.height):
        row_start = y * width * 4
        row_end = row_start + width * 4
        if expected_pixels[row_start:row_end] == actual_pixels[row_start:row_end]:
            continue
        xs, deltas = _row_mismatches(
            expected_pixels,
            actual_pixels,
            row_start=row_start,
            width=width,
            threshold=max_channel_delta,
            masked_spans=_row_masked_spans(masks, y),
        )
        if not xs:
            continue
        mismatched += len(xs)
        delta_sum += sum(deltas)
        row_max = max(deltas)
        if row_max > max_delta:
            max_delta = row_max

    compared = max(0, bounds.area - masked_total)
    ratio = (mismatched / compared) if compared > 0 else 0.0
    return {
        "compared_pixels": compared,
        "masked_pixels": masked_total,
        "mismatched_pixels": mismatched,
        "mismatched_ratio": round(ratio, 6),
        "identical_ratio": round(1.0 - ratio, 6),
        "mean_abs_channel_delta": round(delta_sum / mismatched, 3) if mismatched else 0.0,
        "max_channel_delta": max_delta,
        "max_channel_delta_tolerance": max_channel_delta,
    }


def _row_mismatches(
    expected: bytes,
    actual: bytes,
    *,
    row_start: int,
    width: int,
    threshold: int,
    masked_spans: list[tuple[int, int]],
) -> tuple[list[int], list[int]]:
    xs: list[int] = []
    deltas: list[int] = []
    span_starts = [span[0] for span in masked_spans]

    for chunk_start in range(0, width, CHUNK_PIXELS):
        chunk_end = min(width, chunk_start + CHUNK_PIXELS)
        byte_start = row_start + chunk_start * 4
        byte_end = row_start + chunk_end * 4
        if expected[byte_start:byte_end] == actual[byte_start:byte_end]:
            continue
        for x in range(chunk_start, chunk_end):
            if masked_spans and _is_masked(x, masked_spans, span_starts):
                continue
            offset = row_start + x * 4
            delta = abs(expected[offset] - actual[offset])
            second = abs(expected[offset + 1] - actual[offset + 1])
            if second > delta:
                delta = second
            third = abs(expected[offset + 2] - actual[offset + 2])
            if third > delta:
                delta = third
            if delta > threshold:
                xs.append(x)
                deltas.append(delta)
    return xs, deltas


def _is_masked(x: int, spans: list[tuple[int, int]], span_starts: list[int]) -> bool:
    index = bisect_right(span_starts, x) - 1
    if index < 0:
        return False
    start, end = spans[index]
    return start <= x < end


def _row_masked_spans(masks: list[Rect], y: int) -> list[tuple[int, int]]:
    spans = sorted((mask.x, mask.right) for mask in masks if mask.area > 0 and mask.y <= y < mask.bottom)
    if not spans:
        return []
    merged: list[tuple[int, int]] = []
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start > current_end:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    merged.append((current_start, current_end))
    return merged


def _cell_in_any(cell_x: int, cell_y: int, rects: list[Rect]) -> bool:
    for rect in rects:
        if rect.x <= cell_x < rect.right and rect.y <= cell_y < rect.bottom:
            return True
    return False


def _rects_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if not first or not second:
        return False
    return not (
        int(first["x"]) >= int(second["x"]) + int(second["width"])
        or int(second["x"]) >= int(first["x"]) + int(first["width"])
        or int(first["y"]) >= int(second["y"]) + int(second["height"])
        or int(second["y"]) >= int(first["y"]) + int(first["height"])
    )


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, (percentile * len(ordered)) // 100))
    return ordered[index]
