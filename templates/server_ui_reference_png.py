from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server_core import ToolInvocationError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DEFAULT_MAX_IMAGE_PIXELS = 16_000_000
CHANNELS_BY_COLOR_TYPE = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
SUPPORTED_COLOR_TYPES = tuple(sorted(CHANNELS_BY_COLOR_TYPE))


@dataclass(frozen=True)
class RgbaImage:
    width: int
    height: int
    pixels: bytes

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    def describe(self) -> dict[str, Any]:
        return {"width": self.width, "height": self.height, "pixel_count": self.pixel_count}


def read_png(path: Path, *, max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS, source: str = "") -> RgbaImage:
    label = source or str(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ToolInvocationError(
            "ui_reference_image_unreadable",
            f"Could not read image '{label}': {exc}",
            {"path": str(path), "source": label},
        ) from exc
    return decode_png(data, max_pixels=max_pixels, source=label)


def write_png(path: Path, image: RgbaImage) -> int:
    data = encode_png(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return len(data)


def decode_png(data: bytes, *, max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS, source: str = "image") -> RgbaImage:
    if not data.startswith(PNG_SIGNATURE):
        raise ToolInvocationError(
            "ui_reference_image_format_unsupported",
            (
                f"'{source}' is not a PNG file. ui-reference.v1 accepts PNG captures only so that "
                "comparison never depends on lossy re-encoding."
            ),
            {"source": source},
        )

    header: dict[str, int] | None = None
    palette = b""
    transparency = b""
    idat = bytearray()
    offset = len(PNG_SIGNATURE)
    total = len(data)

    while offset + 8 <= total:
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > total:
            raise _corrupt(source, "a PNG chunk extends past the end of the file")
        payload = data[start:end]
        offset = end + 4
        if chunk_type == b"IHDR":
            header = _parse_ihdr(payload, source)
        elif chunk_type == b"PLTE":
            palette = payload
        elif chunk_type == b"tRNS":
            transparency = payload
        elif chunk_type == b"IDAT":
            idat += payload
        elif chunk_type == b"IEND":
            break

    if header is None:
        raise _corrupt(source, "the PNG has no IHDR chunk")
    if not idat:
        raise _corrupt(source, "the PNG has no IDAT image data")

    width = header["width"]
    height = header["height"]
    if width * height > max_pixels:
        raise ToolInvocationError(
            "ui_reference_image_too_large",
            (
                f"'{source}' is {width}x{height} ({width * height} pixels) which exceeds the "
                f"{max_pixels}-pixel comparison budget."
            ),
            {"source": source, "width": width, "height": height, "max_pixels": max_pixels},
        )

    bit_depth = header["bit_depth"]
    color_type = header["color_type"]
    channels = CHANNELS_BY_COLOR_TYPE[color_type]
    sample_bytes = bit_depth // 8
    bytes_per_pixel = channels * sample_bytes
    stride = width * bytes_per_pixel

    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise _corrupt(source, f"the PNG image data could not be decompressed: {exc}") from exc

    if len(raw) < (stride + 1) * height:
        raise _corrupt(source, "the PNG image data is shorter than the declared image size")

    samples = _unfilter(raw, width=width, height=height, stride=stride, bytes_per_pixel=bytes_per_pixel)
    if sample_bytes == 2:
        samples = samples[0::2]

    pixels = _to_rgba(
        samples,
        width=width,
        height=height,
        color_type=color_type,
        palette=palette,
        transparency=transparency,
        source=source,
    )
    return RgbaImage(width=width, height=height, pixels=bytes(pixels))


def encode_png(image: RgbaImage) -> bytes:
    stride = image.width * 4
    raw = bytearray()
    pixels = image.pixels
    for row in range(image.height):
        raw.append(0)
        raw += pixels[row * stride : (row + 1) * stride]

    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    parts = [
        PNG_SIGNATURE,
        _chunk(b"IHDR", header),
        _chunk(b"IDAT", zlib.compress(bytes(raw), 6)),
        _chunk(b"IEND", b""),
    ]
    return b"".join(parts)


def probe_png_dimensions(data: bytes, *, source: str = "image") -> tuple[int, int]:
    if not data.startswith(PNG_SIGNATURE) or len(data) < 33:
        raise ToolInvocationError(
            "ui_reference_image_format_unsupported",
            f"'{source}' is not a PNG file.",
            {"source": source},
        )
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _parse_ihdr(payload: bytes, source: str) -> dict[str, int]:
    if len(payload) != 13:
        raise _corrupt(source, "the PNG IHDR chunk has an unexpected size")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", payload
    )
    if width <= 0 or height <= 0:
        raise _corrupt(source, "the PNG declares a zero-sized image")
    if compression != 0 or filter_method != 0:
        raise _unsupported(source, "non-standard PNG compression or filter methods are not supported")
    if interlace != 0:
        raise _unsupported(source, "interlaced (Adam7) PNGs are not supported; save a non-interlaced capture")
    if color_type not in CHANNELS_BY_COLOR_TYPE:
        raise _unsupported(source, f"PNG color type {color_type} is not supported")
    if color_type == 3 and bit_depth != 8:
        raise _unsupported(source, "palette PNGs are supported at 8-bit depth only")
    if color_type != 3 and bit_depth not in (8, 16):
        raise _unsupported(source, f"PNG bit depth {bit_depth} is not supported; use 8-bit or 16-bit")
    return {
        "width": int(width),
        "height": int(height),
        "bit_depth": int(bit_depth),
        "color_type": int(color_type),
    }


def _unfilter(raw: bytes, *, width: int, height: int, stride: int, bytes_per_pixel: int) -> bytearray:
    out = bytearray(stride * height)
    position = 0
    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = raw[position : position + stride]
        position += stride
        row_start = row * stride
        prior_start = row_start - stride

        if filter_type == 0:
            out[row_start : row_start + stride] = line
            continue
        if filter_type == 1:
            for index in range(stride):
                left = out[row_start + index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                out[row_start + index] = (line[index] + left) & 0xFF
            continue
        if filter_type == 2:
            if row == 0:
                out[row_start : row_start + stride] = line
                continue
            for index in range(stride):
                out[row_start + index] = (line[index] + out[prior_start + index]) & 0xFF
            continue
        if filter_type == 3:
            for index in range(stride):
                left = out[row_start + index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                up = out[prior_start + index] if row > 0 else 0
                out[row_start + index] = (line[index] + ((left + up) >> 1)) & 0xFF
            continue
        if filter_type == 4:
            for index in range(stride):
                left = out[row_start + index - bytes_per_pixel] if index >= bytes_per_pixel else 0
                up = out[prior_start + index] if row > 0 else 0
                up_left = (
                    out[prior_start + index - bytes_per_pixel]
                    if row > 0 and index >= bytes_per_pixel
                    else 0
                )
                out[row_start + index] = (line[index] + _paeth(left, up, up_left)) & 0xFF
            continue
        raise _corrupt("image", f"unknown PNG row filter {filter_type}")
    return out


def _paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    distance_left = abs(estimate - left)
    distance_up = abs(estimate - up)
    distance_up_left = abs(estimate - up_left)
    if distance_left <= distance_up and distance_left <= distance_up_left:
        return left
    if distance_up <= distance_up_left:
        return up
    return up_left


def _to_rgba(
    samples: bytearray,
    *,
    width: int,
    height: int,
    color_type: int,
    palette: bytes,
    transparency: bytes,
    source: str,
) -> bytearray:
    pixel_count = width * height
    rgba = bytearray(b"\xff" * (pixel_count * 4))

    if color_type == 6:
        return bytearray(samples[: pixel_count * 4])
    if color_type == 2:
        rgba[0::4] = samples[0::3]
        rgba[1::4] = samples[1::3]
        rgba[2::4] = samples[2::3]
        return rgba
    if color_type == 0:
        rgba[0::4] = samples
        rgba[1::4] = samples
        rgba[2::4] = samples
        return rgba
    if color_type == 4:
        gray = samples[0::2]
        rgba[0::4] = gray
        rgba[1::4] = gray
        rgba[2::4] = gray
        rgba[3::4] = samples[1::2]
        return rgba

    if len(palette) < 3:
        raise _corrupt(source, "the palette PNG has no usable PLTE chunk")
    entries = len(palette) // 3
    red_table = bytearray(256)
    green_table = bytearray(256)
    blue_table = bytearray(256)
    alpha_table = bytearray(b"\xff" * 256)
    for index in range(min(entries, 256)):
        red_table[index] = palette[index * 3]
        green_table[index] = palette[index * 3 + 1]
        blue_table[index] = palette[index * 3 + 2]
    for index in range(min(len(transparency), 256)):
        alpha_table[index] = transparency[index]

    indices = bytes(samples[:pixel_count])
    rgba[0::4] = indices.translate(bytes(red_table))
    rgba[1::4] = indices.translate(bytes(green_table))
    rgba[2::4] = indices.translate(bytes(blue_table))
    rgba[3::4] = indices.translate(bytes(alpha_table))
    return rgba


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return b"".join(
        [
            struct.pack(">I", len(payload)),
            chunk_type,
            payload,
            struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF),
        ]
    )


def _corrupt(source: str, detail: str) -> ToolInvocationError:
    return ToolInvocationError(
        "ui_reference_image_corrupt",
        f"'{source}' could not be decoded: {detail}.",
        {"source": source, "detail": detail},
    )


def _unsupported(source: str, detail: str) -> ToolInvocationError:
    return ToolInvocationError(
        "ui_reference_image_unsupported",
        f"'{source}' cannot be compared: {detail}.",
        {"source": source, "detail": detail},
    )
