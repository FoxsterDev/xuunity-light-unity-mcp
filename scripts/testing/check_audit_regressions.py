#!/usr/bin/env python3
"""Re-run the audit's own reproductions and assert each defect is still closed.

Every finding from the 2026-07-31 external audit came with a concrete reproduction and a measured
number. A passing unit suite proves the assertions hold; it does not prove the defects the audit
found are gone, because several of them were encoded in the suite as expected behaviour. This
script executes the reproductions directly and checks both directions:

  * closed   -- the defect no longer reproduces
  * benign   -- a capture that is legitimately the same screen still passes

Run from the repository root:  python3 scripts/testing/check_audit_regressions.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "templates"))

import server_ui_reference_png as png
from server_bridge_paths import scenario_results_dir
from server_core import ToolInvocationError
from server_ui_fixture import validate_ui_fixture
from server_ui_reference_manifest import Rect, TOLERANCE_PROFILES
from server_ui_reference_policy import build_mask_audit
from server_ui_reference_registry import register_ui_reference
from server_ui_reference_compare import compare_ui_reference
from server_ui_reference_similarity import build_cell_grid
from server_ui_vision_review import (
    CRITERIA,
    UI_VISION_SCHEMA_VERSION,
    normalize_vision_review,
    packet_hash,
    resolve_vision_policy,
)

CHECKS: list[tuple[str, str, bool, str]] = []


def record(area: str, name: str, ok: bool, detail: str) -> None:
    CHECKS.append((area, name, ok, detail))


# --------------------------------------------------------------------------------------- fixtures


def solid(width: int, height: int, colour: tuple[int, int, int, int]) -> png.RgbaImage:
    return png.RgbaImage(width=width, height=height, pixels=bytes(colour) * (width * height))


def with_rect(image: png.RgbaImage, rect: Rect, colour: tuple[int, int, int, int]) -> png.RgbaImage:
    pixels = bytearray(image.pixels)
    for y in range(max(0, rect.y), min(image.height, rect.bottom)):
        base = y * image.width * 4
        for x in range(max(0, rect.x), min(image.width, rect.right)):
            pixels[base + x * 4 : base + x * 4 + 4] = bytes(colour)
    return png.RgbaImage(width=image.width, height=image.height, pixels=bytes(pixels))


CARD = Rect(20, 60, 200, 410)
ILLUSTRATION = Rect(50, 90, 140, 140)
CTA = Rect(45, 410, 150, 40)
BODY_LINES = [Rect(48, 266 + index * 18, 140 - index * 6, 8) for index in range(6)]


def screen(scale: int = 1) -> png.RgbaImage:
    def s(rect: Rect) -> Rect:
        return Rect(rect.x * scale, rect.y * scale, rect.width * scale, rect.height * scale)

    image = solid(240 * scale, 480 * scale, (12, 14, 26, 255))
    image = with_rect(image, s(CARD), (245, 245, 250, 255))
    image = with_rect(image, s(ILLUSTRATION), (255, 205, 60, 255))
    for line in BODY_LINES:
        image = with_rect(image, s(line), (40, 40, 60, 255))
    image = with_rect(image, s(CTA), (40, 120, 220, 255))
    return image


REGIONS = [
    {"id": "illustration", "rect": ILLUSTRATION.to_mapping(), "weight": 4},
    {"id": "body", "rect": Rect(30, 255, 180, 140).to_mapping(), "weight": 4},
    {"id": "cta", "rect": CTA.to_mapping(), "weight": 3},
]


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.project = root / "Project"
        (self.project / "Assets").mkdir(parents=True)
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: 6000.0.58f1\n", encoding="utf-8"
        )
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        self.captures = root / "captures"
        self.captures.mkdir()

    def write(self, name: str, image: png.RgbaImage) -> Path:
        path = self.captures / f"{name}.png"
        png.write_png(path, image)
        return path

    def register(self, image: png.RgbaImage, reference_id: str, **overrides) -> dict:
        payload = {
            "project_root": self.project,
            "reference_id": reference_id,
            "source_image": str(self.write(f"{reference_id}-source", image)),
            "fixture": "popup.available",
            "regions": list(REGIONS),
            "acceptance": {"visual": "required", "semantic": "not_required", "interaction": "not_required"},
            "workspace_root": str(self.workspace),
            "register_in_artifact_registry": False,
        }
        payload.update(overrides)
        return register_ui_reference(**payload)

    def compare(self, reference_id: str, image: png.RgbaImage, name: str, **overrides) -> dict:
        actual = self.write(name, image)
        payload = {
            "project_root": self.project,
            "reference_id": reference_id,
            "actual_image": str(actual),
            "stability_image": str(actual),
            "workspace_root": str(self.workspace),
            "register_in_artifact_registry": False,
            "emit_artifacts": False,
            "comparison_id": name,
        }
        payload.update(overrides)
        return compare_ui_reference(**payload)


# ------------------------------------------------------------------------------------ the defects


def check_similarity_grid(h: Harness) -> None:
    """Audit: the identical design captured at 2x/3x/4x FAILED (title region 0.900)."""

    h.register(screen(), "grid")
    base = build_cell_grid(screen(), columns=128, rows=256)
    worst = 0
    for scale in (2, 3, 4):
        grid = build_cell_grid(screen(scale), columns=128, rows=256)
        worst = max(worst, max(abs(a - b) for a, b in zip(base.red, grid.red)))
    record(
        "grid",
        "same design redrawn at 2x/3x/4x yields identical cell means",
        worst == 0,
        f"max cell delta {worst} (audit: region scored 0.900 and failed)",
    )

    for scale in (2, 3):
        result = h.compare("grid", screen(scale), f"grid-{scale}x")
        ok = result["visual_verdict"] == "passed" and result["global"]["similarity_score"] == 1.0
        record(
            "grid",
            f"redrawn {scale}x comparison passes at 1.0",
            ok,
            f"{result['visual_verdict']} at {result['global']['similarity_score']}",
        )


def check_completeness(h: Harness) -> None:
    """Audit: missing body copy scored 0.970 and PASSED; missing CTA scored 0.968 and PASSED."""

    h.register(screen(), "completeness")
    cases = {
        "missing body copy": ("body", lambda img: _blank(img, BODY_LINES)),
        "missing cta": ("cta", lambda img: with_rect(img, CTA, (245, 245, 250, 255))),
    }
    for label, (region_id, mutate) in cases.items():
        result = h.compare("completeness", mutate(screen()), f"completeness-{region_id}")
        region = next(item for item in result["regions"] if item["region_id"] == region_id)
        coverage = region.get("content_coverage") or {}
        # Either lane catching it is a pass. For a region cropped tight to the element the colour
        # lane already fails hard; coverage is what catches the same defect inside a coarser region,
        # where the missing element is a small share of the area and gets averaged away.
        caught_by = []
        if coverage.get("passed") is False:
            caught_by.append("coverage")
        if region["similarity_score"] < region["threshold"]:
            caught_by.append("similarity")
        record(
            "completeness",
            f"{label} now fails",
            result["visual_verdict"] == "failed" and bool(caught_by),
            f"verdict={result['visual_verdict']} caught_by={'+'.join(caught_by) or 'nothing'} "
            f"similarity={region['similarity_score']} coverage={coverage.get('coverage_ratio')}",
        )


def check_completeness_in_a_coarse_region(h: Harness) -> None:
    """The headline case: the element is a small share of a large region, so a mismatched-cell
    fraction stays above the floor and only an area-independent check can see it."""

    h.register(
        screen(),
        "coarse-card",
        regions=[{"id": "card", "rect": CARD.to_mapping(), "weight": 4}],
    )
    result = h.compare("coarse-card", _blank(screen(), BODY_LINES), "coarse-card-no-body")
    region = next(item for item in result["regions"] if item["region_id"] == "card")
    coverage = region.get("content_coverage") or {}
    similarity_would_pass = region["similarity_score"] >= region["threshold"]
    record(
        "completeness",
        "missing body inside a large card region fails on coverage alone",
        result["visual_verdict"] == "failed" and coverage.get("passed") is False and similarity_would_pass,
        f"similarity={region['similarity_score']} (threshold {region['threshold']}, "
        f"would have passed={similarity_would_pass}) coverage={coverage.get('coverage_ratio')}",
    )


def _blank(image: png.RgbaImage, rects: list[Rect]) -> png.RgbaImage:
    for rect in rects:
        image = with_rect(image, rect, (245, 245, 250, 255))
    return image


def check_region_granularity(h: Harness) -> None:
    """Audit: a single full_screen region reduced the bar to ~6.5% of the screen being arbitrary."""

    try:
        h.register(
            screen(),
            "coarse",
            regions=[{"id": "everything", "rect": {"x": 0, "y": 0, "width": 240, "height": 480}}],
        )
        record("regions", "a single full-screen region is refused", False, "registration succeeded")
    except ToolInvocationError as exc:
        codes = [error["code"] for error in exc.details.get("errors", [])]
        record(
            "regions",
            "a single full-screen region is refused",
            "ui_reference_regions_coarse" in codes,
            f"{exc.code}: {codes}",
        )


def check_mask_accounting() -> None:
    """Audit: 1296 masks of 1x1 px audited as 0.81% while suppressing 54% of a region's cells."""

    view = Rect(0, 0, 1080, 1920)
    card = Rect(100, 100, 400, 400)
    lattice = [
        Rect(x, y, 1, 1)
        for y in range(150, 450, max(1, 1920 // 227))
        for x in range(150, 450, max(1, 1080 // 128))
    ]
    audit = build_mask_audit(lattice, view, {"card": card}, ("card",), columns=128, rows=227)
    record(
        "masks",
        f"a lattice of {len(lattice)} one-pixel masks is charged its cell footprint",
        bool(audit["violations"]),
        f"charged {audit['masked_pixels']}px (declared {audit['declared_masked_pixels']}px), "
        f"region ratio {audit['regions'][0]['masked_ratio']}, violations {len(audit['violations'])}",
    )

    not_required = build_mask_audit([card], view, {"card": card}, (), columns=128, rows=227)
    record(
        "masks",
        "the region cap applies to non-required regions too",
        bool(not_required["violations"]),
        f"region ratio {not_required['regions'][0]['masked_ratio']}, "
        f"violations {len(not_required['violations'])}",
    )


def check_vision_policy() -> None:
    """Audit: min_criterion/min_overall of 0 made a bar nothing could fail; the clamp never bit."""

    policy = resolve_vision_policy(
        {"tolerance_profile": "balanced", "vision_policy": {"min_criterion": 0, "min_overall": 0}}
    )
    record(
        "vision",
        "a zero bar is raised to the floor",
        policy["min_criterion"] >= 1 and policy["min_overall"] >= 1,
        f"min_criterion={policy['min_criterion']} min_overall={policy['min_overall']}",
    )

    balanced = resolve_vision_policy({"tolerance_profile": "balanced"})
    floor_review = {
        "schema_version": UI_VISION_SCHEMA_VERSION,
        "packet_hash": "abc",
        "judge": {"id": "j", "role": "independent_agent", "model": "m"},
        "overall": 3,
        "criteria": {name: {"score": 2, "observation": "visibly different"} for name in CRITERIA},
    }
    record_floor = normalize_vision_review(floor_review, policy=balanced, expected_packet_hash="abc")
    record(
        "vision",
        "every criterion on the bare floor no longer passes",
        record_floor["verdict"] == "failed",
        f"verdict={record_floor['verdict']} effective={record_floor['overall_effective']}",
    )

    duplicate = dict(floor_review)
    duplicate["criteria"] = {
        **{name: {"score": 4, "observation": "ok"} for name in CRITERIA},
        "layout": {"score": 0, "observation": "CTA absent"},
        "LAYOUT": {"score": 4, "observation": "looks fine"},
    }
    duplicate["overall"] = 4
    dup_record = normalize_vision_review(duplicate, policy=balanced, expected_packet_hash="abc")
    record(
        "vision",
        "a case-variant criterion key cannot overwrite a low score",
        not dup_record["valid"],
        f"errors={dup_record['errors'][:2]}",
    )

    strict_panel = resolve_vision_policy({"vision_policy": {"judges_required": 3, "allow_self_review": False}})
    lax_panel = resolve_vision_policy({"vision_policy": {"judges_required": 1, "allow_self_review": True}})
    material = {"reference_id": "r", "expected_sha256": "a" * 64, "actual_sha256": "b" * 64}
    record(
        "vision",
        "the independence bar is inside packet_hash",
        packet_hash(policy=strict_panel, **material) != packet_hash(policy=lax_panel, **material),
        "judges_required and allow_self_review now change the hash",
    )


def check_provenance(h: Harness) -> None:
    """Audit: a hand-written file passed as fixtureResultPath earned decision_ready=true."""

    block = {
        "schema_version": "xuunity.ui-fixture.v1",
        "fixture_id": "popup.available",
        "state_id": "available",
        "data_source": "fixture",
        "clock": {"frozen": True, "value_utc": "2026-01-01T00:00:00Z"},
        "locale": {"id": "en", "pinned": True},
        "viewport": {"width": 240, "height": 480, "orientation": "portrait"},
        "ready": {"predicate": "popup_open", "satisfied": True, "waited_ms": 5, "timeout_ms": 500},
        "established": True,
        "playmode_state": "playing",
        "visual_determinism": "proven",
    }

    def result_file(directory: Path, name: str, status: str = "passed", cleanup: bool = False) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(
            json.dumps(
                {
                    "run_id": "run-1",
                    "scenario_name": "establish",
                    "status": status,
                    "cleanup_start_index": 0 if cleanup else 1,
                    "steps": [
                        {
                            "stepId": "establish",
                            "kind": "project_defined_hook",
                            "hookName": "example.ui.fixture",
                            "status": "passed",
                            "payload_json": json.dumps({"ui_fixture": block}),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    genuine = result_file(scenario_results_dir(h.project), "genuine.json")
    payload = validate_ui_fixture(
        project_root=h.project, workspace=h.workspace, fixture_result_path=str(genuine)
    )
    record(
        "provenance",
        "a result written where the editor writes them is still a receipt",
        payload["visual_determinism"] == "proven" and payload["succeeded"],
        f"source={payload['fixture']['evidence_source']} determinism={payload['visual_determinism']}",
    )

    forged = result_file(h.captures, "forged.json")
    payload = validate_ui_fixture(
        project_root=h.project, workspace=h.workspace, fixture_result_path=str(forged)
    )
    record(
        "provenance",
        "a hand-written file elsewhere is only an assertion",
        payload["visual_determinism"] == "unproven"
        and payload["fixture"]["evidence_source"] == "unverified_result_path",
        f"source={payload['fixture']['evidence_source']} gaps={payload['fixture']['determinism_gaps']}",
    )

    crashed = result_file(scenario_results_dir(h.project), "crashed.json", status="failed")
    payload = validate_ui_fixture(
        project_root=h.project, workspace=h.workspace, fixture_result_path=str(crashed)
    )
    record(
        "provenance",
        "a failed scenario run does not prove determinism",
        "scenario_run_failed" in payload["fixture"]["determinism_gaps"],
        f"gaps={payload['fixture']['determinism_gaps']}",
    )

    teardown = result_file(scenario_results_dir(h.project), "teardown.json", cleanup=True)
    payload = validate_ui_fixture(
        project_root=h.project, workspace=h.workspace, fixture_result_path=str(teardown)
    )
    record(
        "provenance",
        "a fixture reported by a cleanup step is not credited",
        "fixture_reported_by_cleanup_step" in payload["fixture"]["determinism_gaps"],
        f"gaps={payload['fixture']['determinism_gaps']}",
    )


def check_png_codec() -> None:
    """Audit: a 782 KB file declaring 1x1 drove peak RSS to 1.6 GB and decoded successfully."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        import struct

        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    import struct

    bomb = (
        png.PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * (8 * 1024 * 1024), 9))
        + chunk(b"IEND", b"")
    )
    try:
        png.decode_png(bomb, source="bomb")
        record("png", "a decompression bomb is refused", False, "it decoded successfully")
    except ToolInvocationError as exc:
        record("png", "a decompression bomb is refused", exc.code == "ui_reference_image_too_large", exc.code)

    good = png.encode_png(solid(2, 2, (9, 9, 9, 255)))
    tampered = bytearray(good)
    tampered[len(png.PNG_SIGNATURE) + 8 + 7] = 1  # declared height, CRC left stale
    try:
        decoded = png.decode_png(bytes(tampered), source="tampered")
        record(
            "png",
            "a stale CRC is detected instead of changing the image",
            False,
            f"decoded as {decoded.width}x{decoded.height}",
        )
    except ToolInvocationError as exc:
        record(
            "png",
            "a stale CRC is detected instead of changing the image",
            exc.code == "ui_reference_image_corrupt",
            exc.code,
        )


def check_benign_variation(h: Harness) -> None:
    """The other direction: tightening must not reject a capture that is the same screen."""

    h.register(screen(), "benign")
    base = screen()

    def jitter(image: png.RgbaImage, delta: int) -> png.RgbaImage:
        pixels = bytearray(image.pixels)
        for index in range(0, len(pixels), 4):
            for channel in range(3):
                value = pixels[index + channel]
                step = delta if (index // 4 + channel) % 2 == 0 else -delta
                pixels[index + channel] = min(255, max(0, value + step))
        return png.RgbaImage(width=image.width, height=image.height, pixels=bytes(pixels))

    def downscale(image: png.RgbaImage, factor: int) -> png.RgbaImage:
        width, height = image.width // factor, image.height // factor
        pixels = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                source = ((y * factor) * image.width + x * factor) * 4
                target = (y * width + x) * 4
                pixels[target : target + 4] = image.pixels[source : source + 4]
        return png.RgbaImage(width=width, height=height, pixels=bytes(pixels))

    cases = {
        "identical": base,
        "jitter +/-2": jitter(base, 2),
        "jitter +/-8": jitter(base, 8),
        "redrawn 2x": screen(2),
        "redrawn 3x": screen(3),
    }
    for label, image in cases.items():
        result = h.compare("benign", image, f"benign-{label.replace(' ', '-').replace('/', '')}")
        score = (result.get("global") or {}).get("similarity_score")
        record(
            "benign",
            f"{label} still passes",
            result["visual_verdict"] == "passed",
            f"verdict={result['visual_verdict']} global={score}",
        )

    # Audit: a capture smaller than the comparison grid raised IndexError mid-comparison instead of
    # refusing. 240/2 = 120 px against a 128-cell grid is exactly that case.
    undersized = h.compare("benign", downscale(base, 2), "benign-below-grid")
    record(
        "benign",
        "a capture below the comparison grid is refused, not a crash",
        undersized["visual_verdict"] == "blocked"
        and "global" not in undersized
        and undersized["comparability"]["reason"] == "capture_below_comparison_grid",
        f"verdict={undersized['visual_verdict']} reason={undersized['comparability']['reason']}",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temp:
        harness = Harness(Path(temp))
        check_similarity_grid(harness)
        check_completeness(harness)
        check_completeness_in_a_coarse_region(harness)
        check_region_granularity(harness)
        check_mask_accounting()
        check_vision_policy()
        check_provenance(harness)
        check_png_codec()
        check_benign_variation(harness)

    width = max(len(name) for _, name, _, _ in CHECKS)
    failures = 0
    current = ""
    for area, name, ok, detail in CHECKS:
        if area != current:
            print(f"\n[{area}]")
            current = area
        flag = "ok  " if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  {flag} {name:<{width}}  {detail}")

    print(f"\naudit_regressions={'ok' if failures == 0 else 'failed'} "
          f"checks={len(CHECKS)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
