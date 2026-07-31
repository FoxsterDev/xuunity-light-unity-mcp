from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
if str(TEMPLATES_DIR) not in sys.path:
    sys.path.insert(0, str(TEMPLATES_DIR))

import server
import server_batch_orchestrator
import server_ui_reference_png as png
from server_core import ToolInvocationError
from server_summary_scenario import build_project_defined_hook_summary
from server_ui_fixture import UI_FIXTURE_SCHEMA_VERSION, validate_ui_fixture
from server_ui_reference_compare import compare_ui_reference
from server_ui_reference_manifest import (
    Rect,
    TOLERANCE_PROFILES,
    UI_REFERENCE_SCHEMA_VERSION,
    union_area,
)
from server_ui_reference_registry import register_ui_reference, validate_ui_reference
from server_ui_reference_verdict import score_visual_verdict
from server_bridge_paths import scenario_results_dir

VISUAL_ONLY_ACCEPTANCE = {"visual": "required", "semantic": "not_required", "interaction": "not_required"}


def fixture_block(**overrides) -> dict:
    block = {
        "schema_version": UI_FIXTURE_SCHEMA_VERSION,
        "fixture_id": "popup.available",
        "state_id": "available_with_timer",
        "data_source": "fixture",
        "clock": {"frozen": True, "value_utc": "2026-01-01T00:00:00Z"},
        "locale": {"id": "en", "pinned": True},
        "viewport": {"width": 240, "height": 480},
        "safe_area": "full_screen",
        "ready": {"predicate": "popup_visible_and_idle", "satisfied": True, "waited_ms": 120, "timeout_ms": 5000},
    }
    block.update(overrides)
    return block


def solid_image(width: int, height: int, color: tuple[int, int, int, int]) -> png.RgbaImage:
    return png.RgbaImage(width=width, height=height, pixels=bytes(color) * (width * height))


def with_rect(
    image: png.RgbaImage,
    rect: Rect,
    color: tuple[int, int, int, int],
) -> png.RgbaImage:
    pixels = bytearray(image.pixels)
    for y in range(rect.y, min(image.height, rect.bottom)):
        for x in range(rect.x, min(image.width, rect.right)):
            offset = (y * image.width + x) * 4
            pixels[offset : offset + 4] = bytes(color)
    return png.RgbaImage(width=image.width, height=image.height, pixels=bytes(pixels))


def write_image(path: Path, image: png.RgbaImage) -> Path:
    png.write_png(path, image)
    return path


ILLUSTRATION_REGION = Rect(30, 70, 180, 180)
BODY_REGION = Rect(30, 255, 180, 140)
CTA_REGION = Rect(30, 400, 180, 60)
ILLUSTRATION_CONTENT = Rect(50, 90, 140, 140)
CTA_CONTENT = Rect(45, 410, 150, 40)


def screen_image() -> png.RgbaImage:
    """A small stand-in for a mobile popup screen: card, illustration, body copy, CTA."""

    image = solid_image(240, 480, (12, 14, 26, 255))
    image = with_rect(image, Rect(20, 60, 200, 410), (245, 245, 250, 255))
    image = with_rect(image, ILLUSTRATION_CONTENT, (255, 205, 60, 255))
    for index in range(6):
        image = with_rect(image, Rect(48, 266 + index * 18, 140 - index * 6, 8), (40, 40, 60, 255))
    image = with_rect(image, CTA_CONTENT, (40, 120, 220, 255))
    return image


def default_regions(image: png.RgbaImage) -> list[dict]:
    """Two stacked regions covering the image, so registration satisfies the granularity policy."""

    half = max(1, image.height // 2)
    return [
        {"id": "upper", "rect": {"x": 0, "y": 0, "width": image.width, "height": half}},
        {
            "id": "lower",
            "rect": {"x": 0, "y": half, "width": image.width, "height": image.height - half},
        },
    ]


def screen_image_redrawn(factor: int) -> png.RgbaImage:
    """The same design drawn at `factor` times the resolution.

    Distinct from resize_nearest on purpose: rescaling the reference bitmap lands content on the
    same cell boundaries, so it cannot detect a binning phase error. A redraw can, and this is
    the direction real work uses — a design exported once, captured at the Game View resolution."""

    scale = factor
    image = solid_image(240 * scale, 480 * scale, (12, 14, 26, 255))
    image = with_rect(image, Rect(20 * scale, 60 * scale, 200 * scale, 410 * scale), (245, 245, 250, 255))
    image = with_rect(
        image,
        Rect(
            ILLUSTRATION_CONTENT.x * scale,
            ILLUSTRATION_CONTENT.y * scale,
            ILLUSTRATION_CONTENT.width * scale,
            ILLUSTRATION_CONTENT.height * scale,
        ),
        (255, 205, 60, 255),
    )
    for index in range(6):
        image = with_rect(
            image,
            Rect(48 * scale, (266 + index * 18) * scale, (140 - index * 6) * scale, 8 * scale),
            (40, 40, 60, 255),
        )
    image = with_rect(
        image,
        Rect(
            CTA_CONTENT.x * scale,
            CTA_CONTENT.y * scale,
            CTA_CONTENT.width * scale,
            CTA_CONTENT.height * scale,
        ),
        (40, 120, 220, 255),
    )
    return image


def resize_nearest(image: png.RgbaImage, width: int, height: int) -> png.RgbaImage:
    pixels = bytearray(width * height * 4)
    source = image.pixels
    for y in range(height):
        source_y = min(image.height - 1, y * image.height // height)
        base = source_y * image.width * 4
        for x in range(width):
            source_x = min(image.width - 1, x * image.width // width)
            offset = base + source_x * 4
            target = (y * width + x) * 4
            pixels[target : target + 4] = source[offset : offset + 4]
    return png.RgbaImage(width=width, height=height, pixels=bytes(pixels))


def shift_colors(image: png.RgbaImage, delta: int) -> png.RgbaImage:
    table = bytes(min(255, max(0, value + delta)) for value in range(256))
    shifted = bytearray(image.pixels.translate(table))
    shifted[3::4] = image.pixels[3::4]
    return png.RgbaImage(width=image.width, height=image.height, pixels=bytes(shifted))


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def raw_png(
    width: int,
    height: int,
    samples: bytes,
    *,
    color_type: int,
    bit_depth: int = 8,
    filters: list[int] | None = None,
    palette: bytes = b"",
    transparency: bytes = b"",
) -> bytes:
    """Encode a PNG with explicit per-row filters so the decoder is exercised independently."""

    channels = png.CHANNELS_BY_COLOR_TYPE[color_type]
    sample_bytes = bit_depth // 8
    stride = width * channels * sample_bytes
    bytes_per_pixel = channels * sample_bytes
    chosen = filters or [0] * height

    raw = bytearray()
    for row in range(height):
        filter_type = chosen[row % len(chosen)]
        line = samples[row * stride : (row + 1) * stride]
        prior = samples[(row - 1) * stride : row * stride] if row > 0 else bytes(stride)
        raw.append(filter_type)
        for index in range(stride):
            current = line[index]
            left = line[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = prior[index]
            up_left = prior[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            if filter_type == 0:
                encoded = current
            elif filter_type == 1:
                encoded = current - left
            elif filter_type == 2:
                encoded = current - up
            elif filter_type == 3:
                encoded = current - ((left + up) >> 1)
            else:
                encoded = current - png._paeth(left, up, up_left)
            raw.append(encoded & 0xFF)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    parts = [
        png.PNG_SIGNATURE,
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)),
    ]
    if palette:
        parts.append(chunk(b"PLTE", palette))
    if transparency:
        parts.append(chunk(b"tRNS", transparency))
    parts.append(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
    parts.append(chunk(b"IEND", b""))
    return b"".join(parts)


class UiReferenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.project_root = self.root / "UnityProject"
        (self.project_root / "Assets").mkdir(parents=True)
        (self.project_root / "ProjectSettings").mkdir(parents=True)
        (self.project_root / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 6000.0.58f1\n", encoding="utf-8"
        )
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.captures = self.root / "captures"
        self.captures.mkdir()
        self.addCleanup(self._temp.cleanup)

    def register(self, image: png.RgbaImage, **overrides) -> dict:
        source = write_image(self.captures / f"{overrides.get('reference_id', 'ref')}_source.png", image)
        payload = {
            "project_root": self.project_root,
            "reference_id": "popup-available-v1",
            "source_image": str(source),
            "fixture": "popup.available",
            "acceptance": dict(VISUAL_ONLY_ACCEPTANCE),
            "workspace_root": str(self.workspace),
            "register_in_artifact_registry": False,
            # A single full-screen region is refused by policy, so tests that do not care about
            # region layout still need a localized pair.
            "regions": default_regions(image),
        }
        payload.update(overrides)
        return register_ui_reference(**payload)

    def compare(self, actual: png.RgbaImage, **overrides) -> dict:
        actual_path = write_image(self.captures / f"{overrides.pop('capture_name', 'actual')}.png", actual)
        payload = {
            "project_root": self.project_root,
            "reference_id": "popup-available-v1",
            "actual_image": str(actual_path),
            "workspace_root": str(self.workspace),
            "register_in_artifact_registry": False,
            "comparison_id": "fixed-comparison",
        }
        payload.update(overrides)
        return compare_ui_reference(**payload)

    def stability_capture(self, image: png.RgbaImage, name: str = "stability") -> str:
        return str(write_image(self.captures / f"{name}.png", image))

    def scenario_result(
        self,
        fixture: dict | None,
        *,
        name: str = "scenario-result",
        step_status: str = "passed",
        run_id: str = "run-1",
        scenario_status: str = "passed",
        in_editor_results_dir: bool = True,
        cleanup_phase: bool = False,
    ) -> str:
        """A scenario result on disk.

        By default it lands in the editor's own results directory, which is what makes it count as
        a receipt; `in_editor_results_dir=False` writes it somewhere the caller chose, which the
        host must treat as an assertion instead."""

        payload_json = json.dumps({"outcome": "fixture_established", **({"ui_fixture": fixture} if fixture else {})})
        if in_editor_results_dir:
            directory = scenario_results_dir(self.project_root)
            directory.mkdir(parents=True, exist_ok=True)
        else:
            directory = self.captures
        path = directory / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "scenario_name": "establish_popup_available",
                    "status": scenario_status,
                    "cleanup_start_index": 0 if cleanup_phase else 1,
                    "steps": [
                        {
                            "stepId": "establish_fixture",
                            "kind": "project_defined_hook",
                            "hookName": "example.ui.fixture",
                            "status": step_status,
                            "payload_json": payload_json,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return str(path)


class FixtureProvenanceTest(UiReferenceTestCase):
    """A path argument is not provenance.

    Before this, the only thing separating a receipt from a caller assertion was which argument the
    JSON arrived through, so writing the same dict to a file bought visual_determinism=proven."""

    def validate(self, path: str) -> dict:
        return validate_ui_fixture(
            project_root=self.project_root,
            workspace=self.workspace,
            fixture_result_path=path,
        )

    def test_a_result_in_the_editor_directory_is_a_receipt(self) -> None:
        payload = self.validate(self.scenario_result(fixture_block()))

        self.assertEqual("scenario_result", payload["fixture"]["evidence_source"])
        self.assertEqual([], payload["fixture"]["determinism_gaps"])
        self.assertEqual("proven", payload["visual_determinism"])
        self.assertTrue(payload["succeeded"])

    def test_a_hand_written_file_outside_it_is_only_an_assertion(self) -> None:
        payload = self.validate(
            self.scenario_result(fixture_block(), name="forged", in_editor_results_dir=False)
        )

        self.assertEqual("unverified_result_path", payload["fixture"]["evidence_source"])
        self.assertIn(
            "result_path_outside_editor_results_directory", payload["fixture"]["determinism_gaps"]
        )
        self.assertIn("evidence_not_receipt_backed", payload["fixture"]["determinism_gaps"])
        self.assertEqual("unproven", payload["visual_determinism"])
        self.assertFalse(payload["succeeded"])

    def test_a_failed_scenario_run_does_not_prove_determinism(self) -> None:
        payload = self.validate(
            self.scenario_result(fixture_block(), name="crashed", scenario_status="failed")
        )

        self.assertIn("scenario_run_failed", payload["fixture"]["determinism_gaps"])
        self.assertEqual("unproven", payload["visual_determinism"])
        self.assertFalse(payload["fixture"]["established"])

    def test_a_fixture_reported_by_a_cleanup_step_is_not_credited(self) -> None:
        payload = self.validate(
            self.scenario_result(fixture_block(), name="teardown", cleanup_phase=True)
        )

        self.assertEqual("cleanup", payload["fixture"]["receipt"]["step_phase"])
        self.assertIn("fixture_reported_by_cleanup_step", payload["fixture"]["determinism_gaps"])
        self.assertEqual("unproven", payload["visual_determinism"])

    def test_a_forged_result_cannot_reach_acceptance_end_to_end(self) -> None:
        expected = screen_image()
        self.register(
            expected,
            regions=[
                {"id": "illustration", "rect": ILLUSTRATION_REGION.to_mapping(), "weight": 4},
                {"id": "body", "rect": BODY_REGION.to_mapping(), "weight": 4},
            ],
        )
        forged = self.scenario_result(
            fixture_block(fixture_id="popup.available"),
            name="forged-e2e",
            in_editor_results_dir=False,
        )
        result = self.compare(
            expected,
            stability_image=self.stability_capture(expected),
            fixture_result_path=forged,
            capture_name="forged-e2e",
        )

        self.assertEqual("passed", result["visual_verdict"])
        self.assertEqual("unproven", result["visual_determinism"])
        self.assertFalse(result["decision_ready"])
        self.assertIn(
            "fixture_result_path_outside_editor_results_directory",
            result["decision_readiness_gaps"],
        )


class PngCodecTest(UiReferenceTestCase):
    def test_decodes_every_row_filter_for_rgba(self) -> None:
        width, height = 6, 5
        samples = bytes((x * 7 + y * 13 + channel * 3) % 256 for y in range(height) for x in range(width) for channel in range(4))
        data = raw_png(width, height, samples, color_type=6, filters=[0, 1, 2, 3, 4])
        decoded = png.decode_png(data)
        self.assertEqual((width, height), (decoded.width, decoded.height))
        self.assertEqual(samples, decoded.pixels)

    def test_decodes_rgb_gray_and_palette_sources(self) -> None:
        rgb = raw_png(2, 2, bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120]), color_type=2, filters=[4, 3])
        self.assertEqual(
            bytes([10, 20, 30, 255, 40, 50, 60, 255, 70, 80, 90, 255, 100, 110, 120, 255]),
            png.decode_png(rgb).pixels,
        )

        gray = raw_png(2, 1, bytes([64, 200]), color_type=0, filters=[1])
        self.assertEqual(bytes([64, 64, 64, 255, 200, 200, 200, 255]), png.decode_png(gray).pixels)

        gray_alpha = raw_png(2, 1, bytes([64, 12, 200, 34]), color_type=4, filters=[2])
        self.assertEqual(bytes([64, 64, 64, 12, 200, 200, 200, 34]), png.decode_png(gray_alpha).pixels)

        palette = raw_png(
            2,
            1,
            bytes([0, 1]),
            color_type=3,
            filters=[0],
            palette=bytes([255, 0, 0, 0, 0, 255]),
            transparency=bytes([128]),
        )
        self.assertEqual(bytes([255, 0, 0, 128, 0, 0, 255, 255]), png.decode_png(palette).pixels)

    def test_sixteen_bit_samples_are_reduced_to_high_byte(self) -> None:
        samples = struct.pack(">8H", 0x1234, 0x5678, 0x9ABC, 0xDEF0, 0x0102, 0x0304, 0x0506, 0x0708)
        data = raw_png(2, 1, samples, color_type=6, bit_depth=16, filters=[0])
        self.assertEqual(bytes([0x12, 0x56, 0x9A, 0xDE, 0x01, 0x03, 0x05, 0x07]), png.decode_png(data).pixels)

    def test_round_trip_through_encoder(self) -> None:
        image = with_rect(solid_image(9, 7, (12, 34, 56, 255)), Rect(2, 1, 4, 3), (200, 10, 10, 255))
        self.assertEqual(image.pixels, png.decode_png(png.encode_png(image)).pixels)

    def test_non_png_and_interlaced_inputs_are_refused(self) -> None:
        with self.assertRaises(ToolInvocationError) as jpeg:
            png.decode_png(b"\xff\xd8\xff\xe0 not a png", source="capture.jpg")
        self.assertEqual("ui_reference_image_format_unsupported", jpeg.exception.code)

        interlaced = bytearray(raw_png(2, 1, bytes(8), color_type=6, filters=[0]))
        interlaced[28] = 1
        # The CRC covers the chunk type as well as the payload; the earlier form omitted the type
        # and only passed because chunk CRCs were never verified.
        interlaced[29:33] = struct.pack(">I", zlib.crc32(bytes(interlaced[12:29])) & 0xFFFFFFFF)
        with self.assertRaises(ToolInvocationError) as adam7:
            png.decode_png(bytes(interlaced), source="capture.png")
        self.assertEqual("ui_reference_image_unsupported", adam7.exception.code)

    def test_a_decompression_bomb_is_refused_without_inflating_it(self) -> None:
        """A tiny file declaring a tiny image whose stream expands without bound.

        The pixel budget limits the declared size, which says nothing about the compressed stream,
        so this used to inflate until the host ran out of memory."""

        payload = zlib.compress(b"\x00" * (4 * 1024 * 1024), 9)
        data = (
            png.PNG_SIGNATURE
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + _png_chunk(b"IDAT", payload)
            + _png_chunk(b"IEND", b"")
        )
        self.assertLess(len(data), 64 * 1024)

        with self.assertRaises(ToolInvocationError) as exc:
            png.decode_png(data, source="bomb.png")
        self.assertEqual("ui_reference_image_too_large", exc.exception.code)

    def test_a_tampered_chunk_fails_its_crc_instead_of_changing_the_image(self) -> None:
        good = raw_png(2, 2, bytes([9] * 16), color_type=6, filters=[0, 0])
        self.assertEqual(2, png.decode_png(good, source="ok").height)

        # Flip the declared height and leave the now-stale CRC in place. Undetected, this silently
        # decodes as a 2x1 image and the registry records those dimensions as the reference viewport.
        header_start = len(png.PNG_SIGNATURE) + 8
        tampered = bytearray(good)
        tampered[header_start + 7] = 1
        with self.assertRaises(ToolInvocationError) as exc:
            png.decode_png(bytes(tampered), source="tampered.png")
        self.assertEqual("ui_reference_image_corrupt", exc.exception.code)
        self.assertIn("CRC", str(exc.exception))

    def test_a_palette_index_past_the_palette_is_corrupt_not_black(self) -> None:
        data = raw_png(
            2,
            2,
            bytes([0, 1, 200, 0]),
            color_type=3,
            filters=[0, 0],
            palette=bytes([255, 0, 0, 0, 255, 0]),
        )
        with self.assertRaises(ToolInvocationError) as exc:
            png.decode_png(data, source="palette.png")
        self.assertEqual("ui_reference_image_corrupt", exc.exception.code)

    def test_oversized_images_are_refused_before_decoding(self) -> None:
        data = raw_png(4, 4, bytes(64), color_type=6, filters=[0])
        with self.assertRaises(ToolInvocationError) as exc:
            png.decode_png(data, max_pixels=8, source="huge.png")
        self.assertEqual("ui_reference_image_too_large", exc.exception.code)


class ReferenceRegistrationTest(UiReferenceTestCase):
    def test_registration_publishes_immutable_expected_copy_and_defaults(self) -> None:
        payload = self.register(solid_image(40, 90, (20, 30, 40, 255)))

        self.assertEqual(UI_REFERENCE_SCHEMA_VERSION, payload["schema_version"])
        self.assertEqual({"width": 40, "height": 90, "orientation": "portrait", "dpi_policy": "reference_pixels"}, payload["viewport"])
        self.assertEqual(["upper", "lower"], payload["region_ids"])
        self.assertTrue(payload["validation"]["valid"])

        manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
        expected_bytes = Path(payload["expected_image_path"]).read_bytes()
        self.assertEqual(manifest["expected_image"]["sha256"], payload["expected_image"]["sha256"])
        self.assertEqual(len(expected_bytes), manifest["expected_image"]["size_bytes"])

    def test_a_manifest_registered_before_a_lane_existed_stays_valid(self) -> None:
        """Adding a lane to LANES must not invalidate references already on disk.

        Every test manifest is written through normalize_acceptance, which fills in each known
        lane, so only a stored manifest from an earlier version exercises this."""

        payload = self.register(solid_image(40, 90, (20, 30, 40, 255)))
        manifest_path = Path(payload["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["acceptance"].pop("device", None)
        manifest["acceptance"].pop("vision", None)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        validated = validate_ui_reference(
            project_root=self.project_root,
            reference_id="popup-available-v1",
            workspace_root=str(self.workspace),
        )
        self.assertTrue(validated["validation"]["valid"], validated["validation"]["errors"])

    def test_an_explicit_bad_lane_requirement_is_still_refused(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(
                solid_image(40, 90, (20, 30, 40, 255)),
                acceptance={**VISUAL_ONLY_ACCEPTANCE, "device": "REQUIRED"},
            )
        self.assertEqual("ui_reference_manifest_invalid", exc.exception.code)
        self.assertIn(
            "ui_reference_acceptance_invalid",
            [error["code"] for error in exc.exception.details["errors"]],
        )

    def test_a_single_full_screen_region_is_refused(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(
                solid_image(40, 90, (20, 30, 40, 255)),
                regions=[{"id": "everything", "rect": {"x": 0, "y": 0, "width": 40, "height": 90}}],
            )
        self.assertEqual("ui_reference_manifest_invalid", exc.exception.code)
        self.assertIn(
            "ui_reference_regions_coarse",
            [error["code"] for error in exc.exception.details["errors"]],
        )

    def test_declaring_no_regions_is_refused_rather_than_defaulted(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(solid_image(40, 90, (20, 30, 40, 255)), regions=[])
        self.assertEqual("ui_reference_manifest_invalid", exc.exception.code)

    def test_second_registration_requires_explicit_overwrite(self) -> None:
        self.register(solid_image(10, 20, (1, 2, 3, 255)))
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(solid_image(10, 20, (1, 2, 3, 255)))
        self.assertEqual("ui_reference_already_registered", exc.exception.code)

        payload = self.register(solid_image(10, 20, (9, 9, 9, 255)), overwrite=True)
        self.assertTrue(payload["validation"]["valid"])

    def test_a_rejected_overwrite_leaves_the_previous_reference_intact(self) -> None:
        original = solid_image(40, 90, (20, 30, 40, 255))
        first = self.register(original)
        expected_path = Path(first["expected_image_path"])
        original_bytes = expected_path.read_bytes()

        with self.assertRaises(ToolInvocationError) as exc:
            self.register(
                solid_image(40, 90, (99, 99, 99, 255)),
                overwrite=True,
                regions=[{"id": "outside", "rect": {"x": 0, "y": 0, "width": 400, "height": 900}}],
            )
        self.assertEqual("ui_reference_manifest_invalid", exc.exception.code)
        self.assertTrue(exc.exception.details["previous_reference_restored"])

        # The reference that was already working must still be usable.
        self.assertEqual(original_bytes, expected_path.read_bytes())
        validated = validate_ui_reference(
            project_root=self.project_root,
            reference_id="popup-available-v1",
            workspace_root=str(self.workspace),
        )
        self.assertTrue(validated["validation"]["valid"], validated["validation"]["errors"])

    def test_broad_mask_is_rejected_by_policy(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(
                solid_image(100, 100, (0, 0, 0, 255)),
                dynamic_masks=[{"id": "everything", "rect": {"x": 0, "y": 0, "width": 100, "height": 60}, "reason": "dynamic"}],
            )
        codes = [error["code"] for error in exc.exception.details["errors"]]
        self.assertIn("ui_reference_mask_policy_failed", codes)

    def test_mask_without_reason_is_rejected(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(
                solid_image(100, 100, (0, 0, 0, 255)),
                dynamic_masks=[{"id": "timer", "rect": {"x": 0, "y": 0, "width": 10, "height": 10}}],
            )
        codes = [error["code"] for error in exc.exception.details["errors"]]
        self.assertIn("ui_reference_mask_reason_required", codes)

    def test_region_outside_viewport_is_rejected(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(
                solid_image(50, 50, (0, 0, 0, 255)),
                regions=[{"id": "popup", "rect": {"x": 30, "y": 30, "width": 40, "height": 40}}],
            )
        codes = [error["code"] for error in exc.exception.details["errors"]]
        self.assertIn("ui_reference_region_out_of_bounds", codes)

    def test_missing_fixture_is_a_warning_not_an_error(self) -> None:
        payload = self.register(solid_image(20, 40, (5, 5, 5, 255)), fixture="")
        self.assertTrue(payload["validation"]["valid"])
        self.assertIn(
            "ui_reference_fixture_undeclared",
            [warning["code"] for warning in payload["validation"]["warnings"]],
        )

    def test_non_png_reference_is_refused(self) -> None:
        source = self.captures / "reference.jpg"
        source.write_bytes(b"\xff\xd8\xff\xe0 not a png")
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(solid_image(4, 4, (0, 0, 0, 255)), source_image=str(source))
        self.assertEqual("ui_reference_image_format_unsupported", exc.exception.code)

    def test_tampered_expected_image_fails_validation(self) -> None:
        payload = self.register(solid_image(30, 60, (10, 10, 10, 255)))
        write_image(Path(payload["expected_image_path"]), solid_image(30, 60, (200, 10, 10, 255)))

        validated = validate_ui_reference(
            project_root=self.project_root,
            reference_id="popup-available-v1",
            workspace_root=str(self.workspace),
        )
        codes = [error["code"] for error in validated["validation"]["errors"]]
        self.assertFalse(validated["validation"]["valid"])
        self.assertIn("ui_reference_expected_image_hash_mismatch", codes)

    def test_validate_reports_missing_reference(self) -> None:
        with self.assertRaises(ToolInvocationError) as exc:
            validate_ui_reference(
                project_root=self.project_root,
                reference_id="never-registered",
                workspace_root=str(self.workspace),
            )
        self.assertEqual("ui_reference_not_registered", exc.exception.code)


class ComparisonVerdictTest(UiReferenceTestCase):
    """Acceptance is tolerance-based human similarity, not pixel equality."""

    def build_reference(self, **overrides) -> tuple[png.RgbaImage, dict]:
        expected = screen_image()
        payload = self.register(
            expected,
            regions=[
                {"id": "illustration", "rect": ILLUSTRATION_REGION.to_mapping(), "weight": 4},
                {"id": "body", "rect": BODY_REGION.to_mapping(), "weight": 4},
                {"id": "cta", "rect": CTA_REGION.to_mapping(), "weight": 3},
            ],
            thresholds={"comparison_grid_width": 48},
            **overrides,
        )
        return expected, payload

    def test_identical_capture_with_stability_proof_passes(self) -> None:
        expected, _ = self.build_reference()
        result = self.compare(expected, stability_image=self.stability_capture(expected))

        self.assertEqual("passed", result["visual_verdict"])
        self.assertEqual("passed", result["reference_acceptance"])
        self.assertEqual("proven", result["capture_stability"]["status"])
        self.assertEqual(1.0, result["global"]["similarity_score"])
        self.assertTrue(all(region["passed"] for region in result["regions"]))
        self.assertEqual("visual_only", result["proof_class"])
        self.assertTrue(result["pixel_diagnostics"]["available"])

        roles = {artifact["role"] for artifact in result["artifacts"]}
        self.assertEqual({"actual", "overlay", "diff", "metrics", "verdict"}, roles)
        for artifact in result["artifacts"]:
            self.assertTrue(Path(artifact["path"]).is_file())
            self.assertGreater(artifact["size_bytes"], 0)

    def test_capture_at_half_resolution_still_passes(self) -> None:
        expected, _ = self.build_reference()
        half = resize_nearest(expected, expected.width // 2, expected.height // 2)
        result = self.compare(half, stability_image=self.stability_capture(half), capture_name="half")

        self.assertEqual("passed", result["visual_verdict"], result["failure_reasons"])
        self.assertTrue(result["comparability"]["comparable"])
        self.assertFalse(result["comparability"]["same_resolution"])
        self.assertEqual(0.5, result["comparability"]["capture_scale"])
        self.assertFalse(result["pixel_diagnostics"]["available"])
        self.assertIn(
            "capture_rescaled_for_comparison", [warning["code"] for warning in result["warnings"]]
        )
        overlay = next(item for item in result["artifacts"] if item["role"] == "overlay")
        self.assertEqual("comparison_grid", overlay["render_space"])

    def register_unaligned(self) -> png.RgbaImage:
        """A reference whose cells do not land on whole pixels: 240px over a 128-cell grid is
        1.875 px per cell, so content straddles cell boundaries. An evenly-dividing grid hides
        binning phase errors entirely, which is why the older resolution tests could not see one."""

        expected = screen_image()
        self.register(
            expected,
            regions=[
                {"id": "illustration", "rect": ILLUSTRATION_REGION.to_mapping(), "weight": 4},
                {"id": "body", "rect": BODY_REGION.to_mapping(), "weight": 4},
                {"id": "cta", "rect": CTA_REGION.to_mapping(), "weight": 3},
            ],
        )
        return expected

    def test_the_same_design_redrawn_at_3x_still_passes(self) -> None:
        self.register_unaligned()
        redrawn = screen_image_redrawn(3)
        result = self.compare(
            redrawn, stability_image=self.stability_capture(redrawn), capture_name="redrawn-3x"
        )

        self.assertEqual("passed", result["visual_verdict"], result["failure_reasons"])
        self.assertEqual("passed", result["reference_acceptance"], result["failure_reasons"])
        # An exact proportional redraw is the same screen, so every cell mean must agree exactly.
        self.assertEqual(1.0, result["global"]["similarity_score"])
        for region in result["regions"]:
            self.assertEqual(1.0, region["similarity_score"], region["region_id"])

    def test_an_exact_upscale_of_the_same_pixels_scores_as_identical(self) -> None:
        expected = self.register_unaligned()
        doubled = resize_nearest(expected, expected.width * 2, expected.height * 2)
        result = self.compare(
            doubled, stability_image=self.stability_capture(doubled), capture_name="exact-2x"
        )

        # Area weighting makes an exact pixel-for-pixel upscale indistinguishable from the source.
        self.assertEqual(1.0, result["global"]["similarity_score"])
        self.assertEqual("passed", result["visual_verdict"])

    def test_a_missing_element_fails_even_when_similarity_passes(self) -> None:
        """The defect from the incident this system exists for: copy that does not render.

        A whole-screen similarity score dilutes a missing element by the share of the screen it
        occupied, so the completeness check has to be independent of area."""

        expected = screen_image()
        self.register(
            expected,
            regions=[
                {"id": "card", "rect": {"x": 20, "y": 60, "width": 200, "height": 410}, "weight": 4},
            ],
        )
        blanked = expected
        for index in range(6):
            blanked = with_rect(
                blanked, Rect(48, 266 + index * 18, 140 - index * 6, 8), (245, 245, 250, 255)
            )

        result = self.compare(
            blanked, stability_image=self.stability_capture(blanked), capture_name="no-body"
        )
        card = next(region for region in result["regions"] if region["region_id"] == "card")

        # Colour similarity alone would have passed this capture.
        self.assertGreaterEqual(float(card["similarity_score"]), float(card["threshold"]))
        self.assertFalse(card["content_coverage"]["passed"])
        self.assertLess(float(card["content_coverage"]["coverage_ratio"]), 0.95)
        self.assertFalse(card["passed"])
        self.assertEqual("failed", result["visual_verdict"])
        self.assertEqual("card", result["first_failed_region"])
        self.assertTrue(
            any("content" in reason for reason in result["failure_reasons"]),
            result["failure_reasons"],
        )

    def test_an_uncomparable_region_is_not_a_pass(self) -> None:
        """`passed: None` reads as a pass to any caller testing `is not False`."""

        regions = [
            {
                "region_id": "cta",
                "comparable": False,
                "required": False,
                "similarity_score": None,
                "weight": 1.0,
            }
        ]
        verdict, failures, first_failed = score_visual_verdict(
            global_metrics={"passed": True, "similarity_score": 1.0},
            regions=regions,
            tolerances=dict(TOLERANCE_PROFILES["balanced"]),
        )

        self.assertIs(False, regions[0]["passed"])
        self.assertTrue(regions[0]["not_comparable"])
        self.assertEqual("failed", verdict)
        self.assertEqual("cta", first_failed)
        self.assertTrue(any("no comparable cells" in reason for reason in failures), failures)

    def test_capture_at_higher_resolution_still_passes(self) -> None:
        expected, _ = self.build_reference()
        larger = resize_nearest(expected, expected.width * 3 // 2, expected.height * 3 // 2)
        result = self.compare(larger, stability_image=self.stability_capture(larger), capture_name="larger")

        self.assertEqual("passed", result["visual_verdict"], result["failure_reasons"])
        self.assertEqual(1.5, result["comparability"]["capture_scale"])

    def test_small_style_drift_within_tolerance_passes(self) -> None:
        expected, _ = self.build_reference()
        drifted = shift_colors(expected, 9)
        result = self.compare(drifted, stability_image=self.stability_capture(drifted), capture_name="drift")

        self.assertEqual("passed", result["visual_verdict"], result["failure_reasons"])
        self.assertGreater(result["global"]["mean_color_delta"], 0)

    def test_strict_profile_rejects_what_balanced_accepts(self) -> None:
        expected, _ = self.build_reference()
        drifted = shift_colors(expected, 9)
        stability = self.stability_capture(drifted)

        balanced = self.compare(drifted, stability_image=stability, capture_name="drift")
        strict = self.compare(
            drifted,
            stability_image=stability,
            capture_name="drift",
            tolerance_profile="strict",
            comparison_id="strict-run",
        )

        self.assertEqual("passed", balanced["visual_verdict"])
        self.assertEqual("failed", strict["visual_verdict"])
        self.assertEqual("strict", strict["tolerance_profile"])

    def test_aspect_mismatch_is_not_comparable_and_recommends_resolutions(self) -> None:
        self.build_reference()
        result = self.compare(solid_image(240, 420, (10, 10, 12, 255)), capture_name="wrong-aspect")

        self.assertEqual("blocked", result["visual_verdict"])
        self.assertEqual("comparison_not_comparable", result["blocked_reason"])
        self.assertEqual("aspect_mismatch", result["comparability"]["reason"])
        self.assertNotIn("global", result)
        self.assertNotIn("regions", result)
        self.assertTrue(result["recommended_capture_resolutions"])
        self.assertTrue(any("Game View" in action for action in result["next_actions"]))

    def test_strict_scale_policy_refuses_a_rescaled_capture(self) -> None:
        expected = screen_image()
        self.register(expected, scale_policy="strict", thresholds={"comparison_grid_width": 48})
        half = resize_nearest(expected, expected.width // 2, expected.height // 2)
        result = self.compare(half, capture_name="strict-half")

        self.assertEqual("blocked", result["visual_verdict"])
        self.assertEqual("resolution_mismatch_under_strict_policy", result["comparability"]["reason"])

    def test_recoloured_illustration_fails_and_names_the_region(self) -> None:
        expected, _ = self.build_reference()
        actual = with_rect(expected, ILLUSTRATION_CONTENT, (30, 200, 90, 255))
        result = self.compare(actual, stability_image=self.stability_capture(actual), capture_name="recolour")

        self.assertEqual("failed", result["visual_verdict"])
        self.assertEqual("failed", result["reference_acceptance"])
        self.assertEqual("illustration", result["first_failed_region"])
        by_id = {region["region_id"]: region for region in result["regions"]}
        self.assertFalse(by_id["illustration"]["passed"])
        self.assertTrue(by_id["cta"]["passed"])
        self.assertTrue(result["mismatch_clusters"])
        self.assertIn("illustration", result["mismatch_clusters"][0]["region_ids"])

    def test_unrendered_body_copy_is_reported_as_missing_content(self) -> None:
        expected, _ = self.build_reference()
        actual = with_rect(expected, BODY_REGION, (245, 245, 250, 255))
        result = self.compare(actual, stability_image=self.stability_capture(actual), capture_name="no-body")

        self.assertEqual("failed", result["visual_verdict"])
        self.assertEqual("body", result["first_failed_region"])
        layout = {region["region_id"]: region["layout"] for region in result["regions"]}["body"]
        self.assertFalse(layout["passed"])
        self.assertEqual("content_missing", layout["reason"])
        self.assertTrue(any("renders no content" in reason for reason in result["failure_reasons"]))

    def test_shifted_and_oversized_content_is_reported_with_numbers(self) -> None:
        expected, _ = self.build_reference()
        actual = with_rect(
            with_rect(expected, ILLUSTRATION_REGION, (245, 245, 250, 255)),
            Rect(70, 110, 110, 110),
            (255, 205, 60, 255),
        )
        result = self.compare(actual, stability_image=self.stability_capture(actual), capture_name="shifted")

        layout = {region["region_id"]: region["layout"] for region in result["regions"]}["illustration"]
        self.assertEqual("failed", result["visual_verdict"])
        self.assertFalse(layout["passed"])
        self.assertNotEqual(0.0, layout["offset_x_ratio"])
        self.assertLess(layout["width_ratio"], 1.0)

    def test_declared_mask_absorbs_dynamic_content(self) -> None:
        expected = screen_image()
        self.register(
            expected,
            regions=[{"id": "cta", "rect": CTA_REGION.to_mapping(), "weight": 3}],
            dynamic_masks=[
                {
                    "id": "countdown",
                    "rect": {"x": 30, "y": 400, "width": 70, "height": 60},
                    "reason": "server-driven countdown text changes every second",
                }
            ],
            thresholds={"comparison_grid_width": 48},
        )
        actual = with_rect(expected, Rect(45, 410, 50, 40), (255, 255, 255, 255))
        result = self.compare(actual, stability_image=self.stability_capture(actual), capture_name="masked")

        self.assertEqual("passed", result["visual_verdict"], result["failure_reasons"])
        self.assertGreater(result["global"]["cells_masked"], 0)
        self.assertGreater(
            {region["region_id"]: region for region in result["regions"]}["cta"]["cells_masked"], 0
        )

    def test_undeclared_dynamic_change_outside_mask_still_fails(self) -> None:
        expected = screen_image()
        self.register(
            expected,
            regions=[{"id": "cta", "rect": CTA_REGION.to_mapping(), "weight": 3}],
            dynamic_masks=[
                {
                    "id": "countdown",
                    "rect": {"x": 30, "y": 400, "width": 50, "height": 60},
                    "reason": "server-driven countdown",
                }
            ],
            thresholds={"comparison_grid_width": 48},
        )
        actual = with_rect(expected, Rect(120, 412, 70, 36), (255, 255, 255, 255))
        result = self.compare(actual, stability_image=self.stability_capture(actual), capture_name="unmasked")

        self.assertEqual("failed", result["visual_verdict"])
        self.assertEqual("cta", result["first_failed_region"])

    def test_unstable_capture_blocks_any_verdict(self) -> None:
        expected, _ = self.build_reference()
        drifting = with_rect(expected, Rect(0, 0, 240, 60), (250, 250, 250, 255))
        result = self.compare(expected, stability_image=self.stability_capture(drifting))

        self.assertEqual("blocked", result["visual_verdict"])
        self.assertEqual("blocked", result["reference_acceptance"])
        self.assertEqual("unstable", result["capture_stability"]["status"])
        self.assertFalse(result["decision_ready"])

    def test_missing_stability_capture_blocks_a_pass_but_not_a_failure(self) -> None:
        expected, _ = self.build_reference()

        blocked = self.compare(expected)
        self.assertEqual("blocked", blocked["visual_verdict"])
        self.assertEqual("unproven", blocked["capture_stability"]["status"])

        failing = self.compare(
            with_rect(expected, ILLUSTRATION_CONTENT, (30, 200, 90, 255)),
            comparison_id="failing",
            capture_name="failing-actual",
        )
        self.assertEqual("failed", failing["visual_verdict"])

    def test_waived_stability_allows_a_pass_but_never_decision_readiness(self) -> None:
        expected, _ = self.build_reference()
        result = self.compare(expected, require_capture_stability=False)

        self.assertEqual("passed", result["visual_verdict"])
        self.assertEqual("waived", result["capture_stability"]["status"])
        self.assertFalse(result["decision_ready"])
        self.assertIn("capture_stability_waived", [warning["code"] for warning in result["warnings"]])

    def test_pass_requires_fixture_evidence_for_decision_readiness(self) -> None:
        expected, _ = self.build_reference()
        stability = self.stability_capture(expected)
        without_evidence = self.compare(expected, stability_image=stability)
        self.assertFalse(without_evidence["decision_ready"])
        self.assertIn("fixture_evidence_absent", without_evidence["decision_readiness_gaps"])
        self.assertEqual("not_reported", without_evidence["visual_determinism"])

        caller_asserted = self.compare(
            expected,
            stability_image=stability,
            fixture_evidence=fixture_block(),
            comparison_id="caller-asserted",
        )
        self.assertFalse(caller_asserted["decision_ready"])
        self.assertIn("fixture_evidence_not_receipt_backed", caller_asserted["decision_readiness_gaps"])
        self.assertEqual("unproven", caller_asserted["visual_determinism"])

        receipt_backed = self.compare(
            expected,
            stability_image=stability,
            fixture_result_path=self.scenario_result(fixture_block()),
            comparison_id="receipt-backed",
        )
        self.assertTrue(receipt_backed["decision_ready"])
        self.assertEqual([], receipt_backed["decision_readiness_gaps"])
        self.assertEqual("proven", receipt_backed["visual_determinism"])
        self.assertEqual("scenario_result", receipt_backed["fixture"]["evidence_source"])
        self.assertEqual("run-1", receipt_backed["fixture"]["receipt"]["run_id"])

    def test_required_semantic_lane_keeps_a_visual_pass_pending(self) -> None:
        expected, _ = self.build_reference(
            acceptance={"visual": "required", "semantic": "required", "interaction": "required"}
        )
        result = self.compare(expected, stability_image=self.stability_capture(expected))

        self.assertEqual("passed", result["visual_verdict"])
        self.assertEqual("pending_lanes", result["reference_acceptance"])
        self.assertEqual(["semantic", "interaction"], sorted(result["pending_lanes"], reverse=True))
        self.assertEqual("not_evaluated", result["acceptance_lanes"]["semantic"]["status"])
        self.assertFalse(result["succeeded"])

    def test_human_owned_reference_never_reports_acceptance(self) -> None:
        expected, _ = self.build_reference(owner="human")
        result = self.compare(expected, stability_image=self.stability_capture(expected))

        self.assertEqual("passed", result["visual_verdict"])
        self.assertEqual("pending_manual_style", result["reference_acceptance"])
        self.assertIn("visual_owner_human", [warning["code"] for warning in result["warnings"]])

    def test_invalid_manifest_blocks_before_any_score(self) -> None:
        expected, payload = self.build_reference()
        write_image(Path(payload["expected_image_path"]), solid_image(240, 480, (99, 99, 99, 255)))
        result = self.compare(expected)

        self.assertEqual("blocked", result["reference_acceptance"])
        self.assertEqual("reference_manifest_invalid", result["blocked_reason"])
        self.assertNotIn("global", result)

    def test_missing_capture_is_a_typed_error(self) -> None:
        self.build_reference()
        with self.assertRaises(ToolInvocationError) as exc:
            compare_ui_reference(
                project_root=self.project_root,
                reference_id="popup-available-v1",
                actual_image=str(self.captures / "does-not-exist.png"),
                workspace_root=str(self.workspace),
                register_in_artifact_registry=False,
            )
        self.assertEqual("ui_reference_actual_capture_missing", exc.exception.code)

    def test_artifacts_can_be_skipped_for_a_fast_score_only_pass(self) -> None:
        expected, _ = self.build_reference()
        result = self.compare(expected, emit_artifacts=False, stability_image=self.stability_capture(expected))

        self.assertEqual([], result["artifacts"])
        self.assertTrue(result["artifacts_omitted"])
        self.assertEqual("passed", result["visual_verdict"])

    def test_metrics_artifact_carries_region_layout_and_cluster_evidence(self) -> None:
        expected, _ = self.build_reference()
        actual = with_rect(expected, ILLUSTRATION_CONTENT, (30, 200, 90, 255))
        result = self.compare(actual, stability_image=self.stability_capture(actual), capture_name="recolour")

        metrics_path = next(Path(item["path"]) for item in result["artifacts"] if item["role"] == "metrics")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {"illustration", "body", "cta"}, {region["region_id"] for region in metrics["regions"]}
        )
        self.assertIn("layout", metrics["regions"][0])
        self.assertEqual("resolution_independent_cell_grid", metrics["comparison_space"]["mode"])
        self.assertTrue(metrics["mismatch_clusters"])

        verdict_path = next(Path(item["path"]) for item in result["artifacts"] if item["role"] == "verdict")
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        self.assertEqual("failed", verdict["reference_acceptance"])


class GeometryAndOverlayTest(UiReferenceTestCase):
    def test_union_area_deduplicates_overlapping_rects(self) -> None:
        self.assertEqual(0, union_area([]))
        self.assertEqual(100, union_area([Rect(0, 0, 10, 10)]))
        self.assertEqual(175, union_area([Rect(0, 0, 10, 10), Rect(5, 5, 10, 10)]))
        self.assertEqual(100, union_area([Rect(0, 0, 10, 10), Rect(2, 2, 3, 3)]))

    def test_overlay_average_matches_a_naive_per_byte_blend(self) -> None:
        from server_ui_reference_artifacts import byte_average

        first = bytes(range(256)) * 3
        second = bytes(reversed(range(256))) * 3
        naive = bytes((a >> 1) + (b >> 1) for a, b in zip(first, second))
        self.assertEqual(naive, byte_average(first, second))


class McpToolSurfaceTest(UiReferenceTestCase):
    def call(self, name: str, arguments: dict) -> dict:
        result = server_batch_orchestrator.call_tool(name, arguments)
        return {
            "payload": result.get("structuredContent") or {},
            "is_error": bool(result.get("isError")),
        }

    def test_reference_tools_are_exposed_and_round_trip(self) -> None:
        response = server.handle_json_rpc_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {"initialized": True, "protocolVersion": server.PROTOCOL_VERSION},
        )
        names = [tool["name"] for tool in response["result"]["tools"]]
        for tool in ("unity_ui_reference_register", "unity_ui_reference_validate", "unity_ui_reference_compare"):
            self.assertIn(tool, names)

        expected = with_rect(solid_image(32, 64, (10, 10, 10, 255)), Rect(4, 8, 24, 24), (200, 30, 30, 255))
        source = write_image(self.captures / "tool_source.png", expected)

        registered = self.call(
            "unity_ui_reference_register",
            {
                "projectRoot": str(self.project_root),
                "referenceId": "tool-ref-v1",
                "sourceImage": str(source),
                "fixture": "popup.available",
                "regions": [{"id": "card", "rect": {"x": 4, "y": 8, "width": 24, "height": 24}}],
                "acceptance": dict(VISUAL_ONLY_ACCEPTANCE),
                "workspaceRoot": str(self.workspace),
            },
        )
        self.assertFalse(registered["is_error"])
        self.assertEqual(["card"], registered["payload"]["region_ids"])

        validated = self.call(
            "unity_ui_reference_validate",
            {
                "projectRoot": str(self.project_root),
                "referenceId": "tool-ref-v1",
                "workspaceRoot": str(self.workspace),
            },
        )
        self.assertFalse(validated["is_error"])
        self.assertTrue(validated["payload"]["validation"]["valid"])

        actual = write_image(self.captures / "tool_actual.png", expected)
        compared = self.call(
            "unity_ui_reference_compare",
            {
                "projectRoot": str(self.project_root),
                "referenceId": "tool-ref-v1",
                "actualImage": str(actual),
                "stabilityImage": str(actual),
                "workspaceRoot": str(self.workspace),
                "comparisonId": "tool-comparison",
            },
        )
        self.assertFalse(compared["is_error"])
        self.assertEqual("passed", compared["payload"]["reference_acceptance"])

        mismatch = write_image(
            self.captures / "tool_mismatch.png",
            with_rect(expected, Rect(4, 8, 24, 24), (30, 200, 30, 255)),
        )
        failed = self.call(
            "unity_ui_reference_compare",
            {
                "projectRoot": str(self.project_root),
                "referenceId": "tool-ref-v1",
                "actualImage": str(mismatch),
                "stabilityImage": str(mismatch),
                "workspaceRoot": str(self.workspace),
                "comparisonId": "tool-comparison-failed",
            },
        )
        self.assertTrue(failed["is_error"])
        self.assertEqual("failed", failed["payload"]["reference_acceptance"])
        self.assertEqual("card", failed["payload"]["first_failed_region"])

    def test_tool_errors_are_typed_not_raised(self) -> None:
        missing = self.call(
            "unity_ui_reference_validate",
            {
                "projectRoot": str(self.project_root),
                "referenceId": "absent-reference",
                "workspaceRoot": str(self.workspace),
            },
        )
        self.assertTrue(missing["is_error"])
        self.assertEqual("ui_reference_not_registered", missing["payload"]["error"]["code"])


class UiFixtureContractTest(UiReferenceTestCase):
    def validate(self, **overrides) -> dict:
        payload = {
            "project_root": self.project_root,
            "workspace": self.workspace,
        }
        payload.update(overrides)
        return validate_ui_fixture(**payload)

    def test_receipt_backed_fixture_proves_visual_determinism(self) -> None:
        result = self.validate(fixture_result_path=self.scenario_result(fixture_block()))

        self.assertTrue(result["succeeded"])
        self.assertEqual("proven", result["visual_determinism"])
        self.assertTrue(result["established"])
        self.assertEqual([], result["fixture"]["determinism_gaps"])
        receipt = result["fixture"]["receipt"]
        self.assertEqual("establish_fixture", receipt["step_id"])
        self.assertEqual("example.ui.fixture", receipt["hook_name"])
        self.assertEqual(64, len(receipt["sha256"]))

    def test_caller_asserted_evidence_is_never_receipt_backed(self) -> None:
        result = self.validate(fixture_evidence=fixture_block())

        self.assertFalse(result["succeeded"])
        self.assertEqual("unproven", result["visual_determinism"])
        self.assertTrue(result["established"])
        self.assertEqual(["evidence_not_receipt_backed"], result["fixture"]["determinism_gaps"])
        self.assertIn("fixtureResultPath", " ".join(result["next_actions"]))

    def test_absent_evidence_reports_the_contract_instead_of_a_verdict(self) -> None:
        for supplied in (None, {}):
            with self.subTest(supplied=supplied):
                result = self.validate(fixture_evidence=supplied)
                self.assertEqual("not_reported", result["visual_determinism"])
                self.assertEqual("absent", result["fixture"]["proof_status"])
                self.assertEqual(UI_FIXTURE_SCHEMA_VERSION, result["contract"]["schema_version"])
                self.assertIn("ui_fixture", result["contract"]["example"])

    def test_live_data_needs_a_recorded_payload_hash(self) -> None:
        live = self.validate(
            fixture_result_path=self.scenario_result(fixture_block(data_source="live"), name="live")
        )
        self.assertEqual("unproven", live["visual_determinism"])
        self.assertIn("live_data_without_payload_hash", live["fixture"]["determinism_gaps"])

        pinned = self.validate(
            fixture_result_path=self.scenario_result(
                fixture_block(data_source="live", payload_hash="sha256:" + "a" * 64),
                name="live-pinned",
            )
        )
        self.assertEqual("proven", pinned["visual_determinism"])

    def test_mixed_data_follows_the_same_rule_as_live(self) -> None:
        result = self.validate(
            fixture_result_path=self.scenario_result(fixture_block(data_source="mixed"), name="mixed")
        )
        self.assertIn("live_data_without_payload_hash", result["fixture"]["determinism_gaps"])

    def test_unfrozen_clock_and_unpinned_locale_are_reported_separately(self) -> None:
        result = self.validate(
            fixture_result_path=self.scenario_result(
                fixture_block(clock={"frozen": False}, locale={"id": "en", "pinned": False}),
                name="drifting",
            )
        )
        gaps = result["fixture"]["determinism_gaps"]
        self.assertIn("clock_not_frozen", gaps)
        self.assertIn("locale_not_pinned", gaps)
        self.assertTrue(result["established"])
        self.assertEqual("unproven", result["visual_determinism"])

    def test_ready_predicate_timeout_means_the_fixture_was_not_established(self) -> None:
        result = self.validate(
            fixture_result_path=self.scenario_result(
                fixture_block(
                    ready={"predicate": "popup_visible", "satisfied": False, "waited_ms": 5000, "timeout_ms": 5000}
                ),
                name="timeout",
            )
        )
        self.assertFalse(result["established"])
        self.assertTrue(result["fixture"]["ready"]["timed_out"])
        self.assertIn("ready_predicate_timed_out", result["fixture"]["determinism_gaps"])

    def test_failed_hook_step_cannot_establish_a_fixture(self) -> None:
        result = self.validate(
            fixture_result_path=self.scenario_result(fixture_block(), name="failed", step_status="failed")
        )
        self.assertFalse(result["established"])
        self.assertIn("hook_step_failed", result["fixture"]["determinism_gaps"])

    def test_unsupported_schema_version_is_an_invalid_report(self) -> None:
        result = self.validate(
            fixture_result_path=self.scenario_result(
                fixture_block(schema_version="xuunity.ui-fixture.v0"), name="old-schema"
            )
        )
        self.assertEqual("invalid", result["fixture"]["proof_status"])
        self.assertIn("unsupported_or_missing_schema_version", result["fixture"]["validation_errors"])
        self.assertFalse(result["established"])

    def test_fixture_and_viewport_mismatch_against_the_reference_are_reported(self) -> None:
        result = self.validate(
            fixture_result_path=self.scenario_result(fixture_block(), name="mismatch"),
            declared_fixture="popup.locked",
            declared_viewport={"width": 1080, "height": 2400},
        )
        gaps = result["fixture"]["determinism_gaps"]
        self.assertIn("fixture_id_mismatch", gaps)
        self.assertIn("viewport_mismatch", gaps)

    def test_result_without_a_ui_fixture_block_is_absent_not_invalid(self) -> None:
        result = self.validate(fixture_result_path=self.scenario_result(None, name="silent"))
        self.assertEqual("absent", result["fixture"]["proof_status"])
        self.assertEqual("not_reported", result["visual_determinism"])
        self.assertEqual("run-1", result["fixture"]["receipt"]["run_id"])

    def test_missing_result_file_is_a_typed_error(self) -> None:
        with self.assertRaises(ToolInvocationError) as caught:
            self.validate(fixture_result_path=str(self.captures / "nope.json"))
        self.assertEqual("ui_fixture_result_not_found", caught.exception.code)

    def test_scenario_hook_summary_surfaces_the_fixture_report(self) -> None:
        summary = build_project_defined_hook_summary(
            [
                {
                    "stepId": "establish_fixture",
                    "kind": "project_defined_hook",
                    "hookName": "example.ui.fixture",
                    "status": "passed",
                    "payload_json": json.dumps({"outcome": "ok", "ui_fixture": fixture_block()}),
                }
            ]
        )
        reported = summary["hooks"][0]["ui_fixture"]
        self.assertEqual("popup.available", reported["fixture_id"])
        self.assertEqual("available_with_timer", reported["state_id"])
        self.assertTrue(reported["established"])
        self.assertEqual("valid", reported["proof_status"])

    def test_scaffolded_fixture_hook_ships_unsatisfied_so_it_fails_closed(self) -> None:
        from server_project_actions import scaffold_project_hook

        result = scaffold_project_hook(
            hook_name="example.ui.fixture",
            action_id="establish_popup_available",
            class_name="ExampleUiFixtureHook",
            namespace="Example.Project.Editor",
            output_dir=self.captures / "scaffold",
            ui_fixture=True,
        )
        files = {item["path"]: item["content"] for item in result["files"]}
        self.assertIn('public string schema_version = "xuunity.ui-fixture.v1";', files["ExampleUiFixtureHook.cs"])
        self.assertIn("public UiFixture ui_fixture = new UiFixture();", files["ExampleUiFixtureHook.cs"])
        self.assertIn("- ui_fixture", files["project_actions.fragment.yaml"])
        self.assertIn("visual_determinism=unproven", files["ACTIVATION_CHECKLIST.md"])

        unfilled = self.validate(
            fixture_evidence={
                "schema_version": UI_FIXTURE_SCHEMA_VERSION,
                "fixture_id": "",
                "data_source": "fixture",
                "clock": {"frozen": False},
                "locale": {"id": "", "pinned": False},
                "ready": {"predicate": "", "satisfied": False},
            }
        )
        self.assertEqual("unproven", unfilled["visual_determinism"])
        self.assertFalse(unfilled["established"])

    def test_fixture_tool_is_exposed_and_fails_closed(self) -> None:
        response = server.handle_json_rpc_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            {"initialized": True, "protocolVersion": server.PROTOCOL_VERSION},
        )
        self.assertIn("unity_ui_fixture_validate", [tool["name"] for tool in response["result"]["tools"]])

        result = server_batch_orchestrator.call_tool(
            "unity_ui_fixture_validate",
            {
                "projectRoot": str(self.project_root),
                "fixtureResultPath": self.scenario_result(fixture_block(clock={"frozen": False}), name="tool"),
                "workspaceRoot": str(self.workspace),
            },
        )
        self.assertTrue(bool(result.get("isError")))
        self.assertEqual("unproven", (result.get("structuredContent") or {})["visual_determinism"])


if __name__ == "__main__":
    unittest.main()
