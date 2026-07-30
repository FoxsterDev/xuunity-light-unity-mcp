from __future__ import annotations

from typing import Any

from server_ui_reference_png import RgbaImage

PANEL_GUTTER = 16
HEADER_HEIGHT = 22
BORDER = 2
GLYPH_WIDTH = 5
GLYPH_HEIGHT = 7
GLYPH_SCALE = 2
GLYPH_SPACING = 1
DEFAULT_MAX_PANEL_HEIGHT = 1024
MIN_PANEL_HEIGHT = 64

SHEET_BACKGROUND = (24, 24, 28, 255)
HEADER_BACKGROUND = (44, 44, 52, 255)
HEADER_TEXT = (236, 236, 240, 255)
REFERENCE_BORDER = (86, 156, 214, 255)
CANDIDATE_BORDER = (206, 145, 120, 255)
MARKER_COLOR = (255, 214, 0, 255)

# 5x7 glyphs, rows top to bottom. Only the characters the sheet labels can contain.
GLYPHS: dict[str, str] = {
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "B": "11110/10001/10001/11110/10001/10001/11110",
    "C": "01110/10001/10000/10000/10000/10001/01110",
    "D": "11110/10001/10001/10001/10001/10001/11110",
    "E": "11111/10000/10000/11110/10000/10000/11111",
    "F": "11111/10000/10000/11110/10000/10000/10000",
    "G": "01110/10001/10000/10111/10001/10001/01111",
    "H": "10001/10001/10001/11111/10001/10001/10001",
    "I": "01110/00100/00100/00100/00100/00100/01110",
    "J": "00111/00010/00010/00010/00010/10010/01100",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "L": "10000/10000/10000/10000/10000/10000/11111",
    "M": "10001/11011/10101/10101/10001/10001/10001",
    "N": "10001/11001/10101/10011/10001/10001/10001",
    "O": "01110/10001/10001/10001/10001/10001/01110",
    "P": "11110/10001/10001/11110/10000/10000/10000",
    "Q": "01110/10001/10001/10001/10101/10010/01101",
    "R": "11110/10001/10001/11110/10100/10010/10001",
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "T": "11111/00100/00100/00100/00100/00100/00100",
    "U": "10001/10001/10001/10001/10001/10001/01110",
    "V": "10001/10001/10001/10001/10001/01010/00100",
    "W": "10001/10001/10001/10101/10101/11011/10001",
    "X": "10001/10001/01010/00100/01010/10001/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "Z": "11111/00001/00010/00100/01000/10000/11111",
    "0": "01110/10001/10011/10101/11001/10001/01110",
    "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111",
    "3": "11111/00010/00100/00010/00001/10001/01110",
    "4": "00010/00110/01010/10010/11111/00010/00010",
    "5": "11111/10000/11110/00001/00001/10001/01110",
    "6": "00110/01000/10000/11110/10001/10001/01110",
    "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110",
    "9": "01110/10001/10001/01111/00001/00010/01100",
    "-": "00000/00000/00000/11111/00000/00000/00000",
    ".": "00000/00000/00000/00000/00000/01100/01100",
    ":": "00000/01100/01100/00000/01100/01100/00000",
    "/": "00001/00010/00010/00100/01000/01000/10000",
    "#": "01010/01010/11111/01010/11111/01010/01010",
    " ": "00000/00000/00000/00000/00000/00000/00000",
}


def render_review_sheet(
    *,
    expected: RgbaImage,
    actual: RgbaImage,
    reference_label: str = "REFERENCE",
    candidate_label: str = "CANDIDATE",
    marked_regions: list[dict[str, Any]] | None = None,
    reference_viewport: dict[str, int] | None = None,
    max_panel_height: int = DEFAULT_MAX_PANEL_HEIGHT,
) -> tuple[RgbaImage, dict[str, Any]]:
    """Two panels at a shared height so a judge compares shape, not scale."""

    budget = max(MIN_PANEL_HEIGHT, int(max_panel_height))
    panel_height = min(budget, max(expected.height, actual.height))
    reference_panel = _fit(expected, panel_height)
    candidate_panel = _fit(actual, panel_height)

    body_top = HEADER_HEIGHT
    panel_top = body_top + BORDER
    left_x = BORDER
    right_x = left_x + reference_panel.width + BORDER * 2 + PANEL_GUTTER
    width = right_x + candidate_panel.width + BORDER
    height = panel_top + panel_height + BORDER

    buffer = bytearray(bytes(SHEET_BACKGROUND) * (width * height))
    _fill_rect(buffer, width, height, 0, 0, width, HEADER_HEIGHT, HEADER_BACKGROUND)

    _blit(buffer, width, height, reference_panel, left_x, panel_top)
    _blit(buffer, width, height, candidate_panel, right_x, panel_top)
    _outline(
        buffer, width, height,
        left_x - BORDER, panel_top - BORDER,
        reference_panel.width + BORDER * 2, panel_height + BORDER * 2,
        REFERENCE_BORDER, BORDER,
    )
    _outline(
        buffer, width, height,
        right_x - BORDER, panel_top - BORDER,
        candidate_panel.width + BORDER * 2, panel_height + BORDER * 2,
        CANDIDATE_BORDER, BORDER,
    )

    _draw_text(buffer, width, height, reference_label.upper(), left_x, 4, HEADER_TEXT)
    _draw_text(buffer, width, height, candidate_label.upper(), right_x, 4, HEADER_TEXT)

    source_viewport = dict(reference_viewport or {"width": expected.width, "height": expected.height})
    markers = _draw_markers(
        buffer,
        width,
        height,
        marked_regions or [],
        source_viewport=source_viewport,
        panels=(
            (left_x, panel_top, reference_panel.width, panel_height),
            (right_x, panel_top, candidate_panel.width, panel_height),
        ),
    )

    layout = {
        "sheet": {"width": width, "height": height},
        "panel_height": panel_height,
        "reference_panel": {
            "x": left_x, "y": panel_top,
            "width": reference_panel.width, "height": panel_height,
            "source": {"width": expected.width, "height": expected.height},
            "scale": round(panel_height / expected.height, 5),
        },
        "candidate_panel": {
            "x": right_x, "y": panel_top,
            "width": candidate_panel.width, "height": panel_height,
            "source": {"width": actual.width, "height": actual.height},
            "scale": round(panel_height / actual.height, 5),
        },
        "reading_order": "left_panel_is_the_reference_right_panel_is_the_candidate",
        "markers": markers,
    }
    return RgbaImage(width=width, height=height, pixels=bytes(buffer)), layout


def _fit(image: RgbaImage, panel_height: int) -> RgbaImage:
    if image.height == panel_height:
        return image
    width = max(1, round(image.width * panel_height / image.height))
    return _resize_nearest(image, width, panel_height)


def _resize_nearest(image: RgbaImage, width: int, height: int) -> RgbaImage:
    source = image.pixels
    source_stride = image.width * 4
    columns = [(x * image.width // width) * 4 for x in range(width)]
    out = bytearray(width * height * 4)
    stride = width * 4
    previous_source_row = -1
    row_bytes = b""
    for y in range(height):
        source_row = y * image.height // height
        if source_row != previous_source_row:
            base = source_row * source_stride
            row_bytes = b"".join([source[base + offset : base + offset + 4] for offset in columns])
            previous_source_row = source_row
        out[y * stride : (y + 1) * stride] = row_bytes
    return RgbaImage(width=width, height=height, pixels=bytes(out))


def _blit(buffer: bytearray, width: int, height: int, image: RgbaImage, x: int, y: int) -> None:
    source_stride = image.width * 4
    span = min(image.width, width - x) * 4
    if span <= 0:
        return
    opaque = b"\xff" * (span // 4)
    for row in range(image.height):
        target_y = y + row
        if target_y < 0 or target_y >= height:
            continue
        start = (target_y * width + x) * 4
        source_start = row * source_stride
        buffer[start : start + span] = image.pixels[source_start : source_start + span]
        buffer[start + 3 : start + span : 4] = opaque


def _fill_rect(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int, int],
) -> None:
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(width, x + rect_width)
    y1 = min(height, y + rect_height)
    if x1 <= x0 or y1 <= y0:
        return
    row = bytes(color) * (x1 - x0)
    for row_y in range(y0, y1):
        start = (row_y * width + x0) * 4
        buffer[start : start + len(row)] = row


def _outline(
    buffer: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    rect_width: int,
    rect_height: int,
    color: tuple[int, int, int, int],
    thickness: int,
) -> None:
    for offset in range(max(1, thickness)):
        top = y + offset
        bottom = y + rect_height - 1 - offset
        _fill_rect(buffer, width, height, x + offset, top, rect_width - offset * 2, 1, color)
        _fill_rect(buffer, width, height, x + offset, bottom, rect_width - offset * 2, 1, color)
        _fill_rect(buffer, width, height, x + offset, y + offset, 1, rect_height - offset * 2, color)
        _fill_rect(
            buffer, width, height,
            x + rect_width - 1 - offset, y + offset, 1, rect_height - offset * 2, color,
        )


def _draw_text(
    buffer: bytearray,
    width: int,
    height: int,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int, int],
    scale: int = GLYPH_SCALE,
) -> int:
    cursor = x
    advance = (GLYPH_WIDTH + GLYPH_SPACING) * scale
    for character in text:
        glyph = GLYPHS.get(character)
        if glyph is None:
            cursor += advance
            continue
        for row_index, row in enumerate(glyph.split("/")):
            for column_index, bit in enumerate(row):
                if bit != "1":
                    continue
                _fill_rect(
                    buffer, width, height,
                    cursor + column_index * scale,
                    y + row_index * scale,
                    scale, scale, color,
                )
        cursor += advance
    return cursor - x


def _draw_markers(
    buffer: bytearray,
    width: int,
    height: int,
    regions: list[dict[str, Any]],
    *,
    source_viewport: dict[str, int],
    panels: tuple[tuple[int, int, int, int], tuple[int, int, int, int]],
) -> list[dict[str, Any]]:
    viewport_width = max(1, int(source_viewport.get("width") or 1))
    viewport_height = max(1, int(source_viewport.get("height") or 1))
    markers: list[dict[str, Any]] = []

    for index, region in enumerate(regions, start=1):
        rect = dict(region.get("rect") or {})
        if not rect:
            continue
        label = f"#{index}"
        placements: list[dict[str, int]] = []
        for panel_x, panel_y, panel_width, panel_height in panels:
            scale_x = panel_width / viewport_width
            scale_y = panel_height / viewport_height
            marker_x = panel_x + int(round(int(rect.get("x", 0)) * scale_x))
            marker_y = panel_y + int(round(int(rect.get("y", 0)) * scale_y))
            marker_width = max(2, int(round(int(rect.get("width", 0)) * scale_x)))
            marker_height = max(2, int(round(int(rect.get("height", 0)) * scale_y)))
            _outline(buffer, width, height, marker_x, marker_y, marker_width, marker_height, MARKER_COLOR, 2)
            _draw_text(
                buffer, width, height, label,
                marker_x + 3, max(0, marker_y - GLYPH_HEIGHT - 2),
                MARKER_COLOR, scale=1,
            )
            placements.append(
                {"x": marker_x, "y": marker_y, "width": marker_width, "height": marker_height}
            )
        markers.append(
            {
                "label": label,
                "region_id": str(region.get("region_id") or ""),
                "reference_rect": rect,
                "drawn_on_reference_panel": placements[0],
                "drawn_on_candidate_panel": placements[1],
            }
        )
    return markers
