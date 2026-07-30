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
from server_ui_reference_compare import compare_ui_reference
from server_ui_reference_manifest import Rect, UI_REFERENCE_SCHEMA_VERSION, union_area
from server_ui_reference_registry import register_ui_reference, validate_ui_reference

VISUAL_ONLY_ACCEPTANCE = {"visual": "required", "semantic": "not_required", "interaction": "not_required"}


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
        interlaced[29:33] = struct.pack(">I", zlib.crc32(bytes(interlaced[16:29])) & 0xFFFFFFFF)
        with self.assertRaises(ToolInvocationError) as adam7:
            png.decode_png(bytes(interlaced), source="capture.png")
        self.assertEqual("ui_reference_image_unsupported", adam7.exception.code)

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
        self.assertEqual(["full_screen"], payload["region_ids"])
        self.assertTrue(payload["validation"]["valid"])

        manifest = json.loads(Path(payload["manifest_path"]).read_text(encoding="utf-8"))
        expected_bytes = Path(payload["expected_image_path"]).read_bytes()
        self.assertEqual(manifest["expected_image"]["sha256"], payload["expected_image"]["sha256"])
        self.assertEqual(len(expected_bytes), manifest["expected_image"]["size_bytes"])
        self.assertIn(
            "ui_reference_regions_coarse",
            [warning["code"] for warning in payload["validation"]["warnings"]],
        )

    def test_second_registration_requires_explicit_overwrite(self) -> None:
        self.register(solid_image(10, 20, (1, 2, 3, 255)))
        with self.assertRaises(ToolInvocationError) as exc:
            self.register(solid_image(10, 20, (1, 2, 3, 255)))
        self.assertEqual("ui_reference_already_registered", exc.exception.code)

        payload = self.register(solid_image(10, 20, (9, 9, 9, 255)), overwrite=True)
        self.assertTrue(payload["validation"]["valid"])

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
        self.assertIn("fixture_establishment_unreported", without_evidence["decision_readiness_gaps"])

        with_evidence = self.compare(
            expected,
            stability_image=stability,
            fixture_evidence={
                "fixture": "popup.available",
                "data_source": "fixture",
                "clock_frozen": True,
                "established": True,
            },
            comparison_id="with-fixture",
        )
        self.assertTrue(with_evidence["decision_ready"])
        self.assertEqual([], with_evidence["decision_readiness_gaps"])

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


if __name__ == "__main__":
    unittest.main()
