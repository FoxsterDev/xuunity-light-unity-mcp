"""Failed-region -> UI node stitching, semantic lane, and device lane.

The comparator can say a region differs; only the semantic snapshot can say why.
Joining the two means crossing two coordinate conventions - Unity screen bounds are
bottom-left origin in capture pixels, reference regions are top-left origin in
reference pixels - so the transform is pinned here explicitly. A silent flip would
produce confident, wrong explanations, which is worse than no explanation.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
if str(TEMPLATES_DIR) not in sys.path:
    sys.path.insert(0, str(TEMPLATES_DIR))

import server_ui_reference_png as png
from server_core import ToolInvocationError
from server_ui_device_lane import device_lane_state, device_lane_warnings, normalize_device_context
from server_ui_reference_compare import compare_ui_reference
from server_ui_reference_registry import register_ui_reference
from server_ui_region_explain import (
    UI_SNAPSHOT_SCHEMA_VERSION,
    evaluate_semantic_lane,
    explain_regions,
    load_ui_snapshot,
)

VISUAL_ONLY_ACCEPTANCE = {"visual": "required", "semantic": "not_required", "interaction": "not_required"}


def node(name: str, *, bounds: tuple[float, float, float, float], **overrides) -> dict:
    record = {
        "node_id": f"ugui:Canvas/{name}",
        "path": f"Canvas/{name}",
        "parent_path": "Canvas",
        "name": name,
        "type": "RectTransform",
        "components": ["RectTransform"],
        "active_in_hierarchy": True,
        "visible": True,
        "interactable": True,
        "effective_alpha": 1.0,
        "has_bounds": True,
        "bounds": {"x": bounds[0], "y": bounds[1], "width": bounds[2], "height": bounds[3]},
        "bounds_space": "screen_pixels",
        "has_text": False,
        "text": "",
        "font_resolved_status": "resolved",
        "material_resolved_status": "resolved",
        "clip_state": "not_clipped",
    }
    record.update(overrides)
    return record


def snapshot(nodes: list[dict], *, width: int = 1080, height: int = 2400) -> dict:
    target = {"kind": "active_scene", "backend": "ugui", "bounds_origin": "bottom_left"}
    if width and height:
        target["capture_width"] = width
        target["capture_height"] = height
    return {
        "schema_version": UI_SNAPSHOT_SCHEMA_VERSION,
        "operation": "unity.ui.tree_snapshot",
        "success": True,
        "proof_class": "semantic_ui_tree",
        "component_detail_backends": ["ugui"],
        "target": target,
        "nodes": nodes,
    }


def failed_region(region_id: str, rect: tuple[int, int, int, int]) -> dict:
    return {
        "region_id": region_id,
        "rect": {"x": rect[0], "y": rect[1], "width": rect[2], "height": rect[3]},
        "passed": False,
    }


class CoordinateTransformTest(unittest.TestCase):
    def test_bottom_left_capture_bounds_map_to_top_left_reference_rect(self) -> None:
        # A 108x240 node sitting in the bottom-left corner of a 1080x2400 capture must
        # land in the bottom-left of a 240x480 reference, i.e. y = 480 - 48 = 432.
        result = explain_regions(
            snapshot=snapshot([node("Corner", bounds=(0.0, 0.0, 108.0, 240.0))]),
            regions=[failed_region("corner", (0, 432, 24, 48))],
            reference_viewport={"width": 240, "height": 480},
            actual_viewport={"width": 1080, "height": 2400},
        )

        self.assertTrue(result["available"])
        transform = result["coordinate_transform"]
        self.assertEqual("snapshot_capture_viewport", transform["viewport_source"])
        self.assertAlmostEqual(0.222222, transform["scale_x"], places=5)

        mapped = result["regions"]["corner"]["nodes"][0]["reference_rect"]
        self.assertEqual({"x": 0, "y": 432, "width": 24, "height": 48}, mapped)

    def test_top_of_capture_maps_to_top_of_reference(self) -> None:
        result = explain_regions(
            snapshot=snapshot([node("Header", bounds=(0.0, 2160.0, 1080.0, 240.0))]),
            regions=[failed_region("header", (0, 0, 240, 48))],
            reference_viewport={"width": 240, "height": 480},
            actual_viewport={"width": 1080, "height": 2400},
        )

        mapped = result["regions"]["header"]["nodes"][0]["reference_rect"]
        self.assertEqual({"x": 0, "y": 0, "width": 240, "height": 48}, mapped)

    def test_snapshot_viewport_mismatch_is_warned_not_silently_rescaled(self) -> None:
        result = explain_regions(
            snapshot=snapshot([node("Card", bounds=(0.0, 0.0, 100.0, 100.0))], width=720, height=1600),
            regions=[failed_region("card", (0, 0, 240, 480))],
            reference_viewport={"width": 240, "height": 480},
            actual_viewport={"width": 1080, "height": 2400},
        )

        codes = [warning["code"] for warning in result["warnings"]]
        self.assertIn("ui_snapshot_viewport_differs_from_capture", codes)
        self.assertEqual({"width": 720, "height": 1600}, result["coordinate_transform"]["snapshot_viewport"])

    def test_snapshot_without_a_viewport_falls_back_and_says_so(self) -> None:
        payload = snapshot([node("Card", bounds=(0.0, 0.0, 100.0, 100.0))])
        payload["target"].pop("capture_width")
        payload["target"].pop("capture_height")

        result = explain_regions(
            snapshot=payload,
            regions=[failed_region("card", (0, 0, 240, 480))],
            reference_viewport={"width": 240, "height": 480},
            actual_viewport={"width": 1080, "height": 2400},
        )

        self.assertEqual("actual_capture_dimensions", result["coordinate_transform"]["viewport_source"])
        self.assertIn("ui_snapshot_viewport_assumed", [item["code"] for item in result["warnings"]])

    def test_prefab_snapshot_without_screen_bounds_refuses_to_stitch(self) -> None:
        payload = snapshot([node("Card", bounds=(0.0, 0.0, 100.0, 100.0), has_bounds=False)])

        result = explain_regions(
            snapshot=payload,
            regions=[failed_region("card", (0, 0, 240, 480))],
            reference_viewport={"width": 240, "height": 480},
            actual_viewport={"width": 1080, "height": 2400},
        )

        self.assertFalse(result["available"])
        self.assertEqual("snapshot_has_no_nodes_with_screen_bounds", result["reason"])


class RegionExplanationTest(unittest.TestCase):
    def explain(self, nodes: list[dict], rect: tuple[int, int, int, int] = (0, 0, 240, 480)) -> dict:
        result = explain_regions(
            snapshot=snapshot(nodes),
            regions=[failed_region("body", rect)],
            reference_viewport={"width": 240, "height": 480},
            actual_viewport={"width": 1080, "height": 2400},
        )
        return result["regions"]["body"]

    def test_unresolved_font_is_named_as_the_likely_cause(self) -> None:
        explanation = self.explain(
            [
                node(
                    "Body",
                    bounds=(0.0, 0.0, 1080.0, 2400.0),
                    components=["RectTransform", "TextMeshProUGUI"],
                    has_text=True,
                    text="Body copy",
                    font_resolved_status="unresolved",
                )
            ]
        )

        self.assertEqual("font_unresolved", explanation["likely_cause"])
        self.assertEqual("Canvas/Body", explanation["likely_cause_node"])
        self.assertIn("font asset did not resolve", explanation["summary"])

    def test_empty_text_and_zero_alpha_are_reported_separately(self) -> None:
        explanation = self.explain(
            [
                node(
                    "Body",
                    bounds=(0.0, 0.0, 1080.0, 2400.0),
                    has_text=True,
                    text="   ",
                    effective_alpha=0.0,
                    visible=False,
                )
            ]
        )

        self.assertIn("empty_text", explanation["nodes"][0]["suspicions"])
        self.assertIn("alpha_zero", explanation["nodes"][0]["suspicions"])
        self.assertEqual("empty_text", explanation["likely_cause"])

    def test_a_region_with_no_overlapping_node_is_itself_the_finding(self) -> None:
        explanation = self.explain(
            [node("Elsewhere", bounds=(0.0, 0.0, 10.0, 10.0))],
            rect=(200, 10, 30, 30),
        )

        self.assertEqual(0, explanation["candidate_count"])
        self.assertIn("renders nothing", explanation["summary"])

    def test_healthy_nodes_point_at_a_visual_difference_not_a_binding(self) -> None:
        explanation = self.explain([node("Illustration", bounds=(0.0, 0.0, 1080.0, 2400.0))])

        self.assertEqual("", explanation["likely_cause"])
        self.assertIn("not a broken binding", explanation["summary"])

    def test_candidates_are_ranked_by_defect_then_coverage(self) -> None:
        explanation = self.explain(
            [
                node("Backdrop", bounds=(0.0, 0.0, 1080.0, 2400.0)),
                node(
                    "Label",
                    bounds=(0.0, 1200.0, 540.0, 200.0),
                    has_text=True,
                    text="Hi",
                    material_resolved_status="unresolved",
                ),
            ]
        )

        self.assertEqual("Canvas/Label", explanation["nodes"][0]["path"])
        self.assertEqual("material_unresolved", explanation["likely_cause"])

    def test_missing_script_outranks_every_other_suspicion(self) -> None:
        explanation = self.explain(
            [
                node(
                    "Broken",
                    bounds=(0.0, 0.0, 1080.0, 2400.0),
                    components=["RectTransform", "<missing script>"],
                    has_text=True,
                    text="",
                    font_resolved_status="unresolved",
                )
            ]
        )

        self.assertEqual("missing_script_component", explanation["likely_cause"])


class SemanticLaneTest(unittest.TestCase):
    def nodes(self) -> list[dict]:
        return [
            node(
                "ClaimButton",
                bounds=(0.0, 0.0, 100.0, 100.0),
                components=["RectTransform", "Image", "Button"],
                has_text=False,
            ),
            node(
                "Title",
                bounds=(0.0, 200.0, 100.0, 100.0),
                components=["RectTransform", "TextMeshProUGUI"],
                has_text=True,
                text="Daily Gift",
            ),
        ]

    def test_no_snapshot_leaves_the_lane_unevaluated(self) -> None:
        lane = evaluate_semantic_lane(snapshot=None, required_ui=[{"selector": {"name": "Title"}}])

        self.assertEqual("not_evaluated", lane["status"])
        self.assertEqual("no_ui_snapshot_supplied", lane["evidence"])

    def test_satisfied_selectors_pass_the_lane(self) -> None:
        lane = evaluate_semantic_lane(
            snapshot=snapshot(self.nodes()),
            required_ui=[
                {"id": "title", "selector": {"name": "Title"}, "text": "Daily Gift"},
                {"id": "cta", "selector": {"name": "ClaimButton", "type": "Button"}, "interactable": True},
            ],
        )

        self.assertEqual("passed", lane["status"])
        self.assertEqual(2, lane["checked"])
        self.assertEqual([], lane["failures"])

    def test_missing_ambiguous_and_mismatched_text_are_distinct_failures(self) -> None:
        duplicated = self.nodes() + [
            node("Title", bounds=(0.0, 400.0, 100.0, 100.0), components=["RectTransform"])
        ]
        lane = evaluate_semantic_lane(
            snapshot=snapshot(duplicated),
            required_ui=[
                {"id": "absent", "selector": {"name": "NoSuchNode"}},
                {"id": "dupe", "selector": {"name": "Title"}},
                {"id": "cta", "selector": {"name": "ClaimButton"}, "text": "Claim"},
            ],
        )

        codes = {failure["id"]: failure["code"] for failure in lane["failures"]}
        self.assertEqual("failed", lane["status"])
        self.assertEqual("ui_node_not_found", codes["absent"])
        self.assertEqual("selector_ambiguous", codes["dupe"])
        self.assertEqual("ui_text_mismatch", codes["cta"])

    def test_invisible_required_node_fails_the_lane(self) -> None:
        hidden = [node("Title", bounds=(0.0, 0.0, 10.0, 10.0), visible=False, effective_alpha=0.0)]
        lane = evaluate_semantic_lane(
            snapshot=snapshot(hidden),
            required_ui=[{"id": "title", "selector": {"name": "Title"}}],
        )

        self.assertEqual("failed", lane["status"])
        self.assertEqual("ui_node_not_visible", lane["failures"][0]["code"])


class DeviceLaneTest(unittest.TestCase):
    def complete_device(self) -> dict:
        return {
            "model": "iPhone 15 Pro",
            "os": "iOS",
            "os_version": "17.4",
            "resolution": {"width": 1179, "height": 2556},
            "orientation": "portrait",
            "build_revision": "abc1234",
            "safe_area": {"top": 59, "bottom": 34},
        }

    def test_complete_device_context_is_reported(self) -> None:
        context = normalize_device_context(self.complete_device())
        state = device_lane_state(
            capture_lane="device",
            acceptance_policy={"device": "required"},
            device_context=context,
        )

        self.assertTrue(context["complete"])
        self.assertEqual("passed", state["status"])
        self.assertEqual([], device_lane_warnings(capture_lane="device", device_context=context))

    def test_declared_device_resolution_must_match_the_capture(self) -> None:
        context = normalize_device_context(self.complete_device())
        state = device_lane_state(
            capture_lane="device",
            acceptance_policy={"device": "required"},
            device_context=context,
            capture_size={"width": 1080, "height": 2400},
        )

        self.assertEqual("failed", state["status"])
        self.assertEqual("device_resolution_mismatch", state["failures"][0]["code"])
        self.assertEqual(
            "passed",
            device_lane_state(
                capture_lane="device",
                acceptance_policy={"device": "required"},
                device_context=context,
                capture_size={"width": 1179, "height": 2556},
            )["status"],
        )

    def test_incomplete_device_context_blocks_the_lane(self) -> None:
        context = normalize_device_context({"model": "Pixel 8"})
        state = device_lane_state(
            capture_lane="device",
            acceptance_policy={"device": "required"},
            device_context=context,
        )

        self.assertFalse(context["complete"])
        self.assertEqual("blocked", state["status"])
        self.assertIn("os", state["missing_fields"])
        codes = [item["code"] for item in device_lane_warnings(capture_lane="device", device_context=context)]
        self.assertIn("device_context_incomplete", codes)
        self.assertIn("device_safe_area_undeclared", codes)

    def test_game_view_capture_is_never_device_evidence(self) -> None:
        state = device_lane_state(
            capture_lane="game_view",
            acceptance_policy={"device": "required"},
            device_context={},
        )

        self.assertEqual("not_evaluated", state["status"])
        self.assertEqual("comparison_ran_on_the_game_view_lane", state["evidence"])


class ComparisonIntegrationTest(unittest.TestCase):
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

    def solid(self, color: tuple[int, int, int, int], width: int = 120, height: int = 240) -> png.RgbaImage:
        return png.RgbaImage(width=width, height=height, pixels=bytes(color) * (width * height))

    def build(self, **overrides) -> None:
        source = self.captures / "reference.png"
        png.write_png(source, self.solid((240, 240, 240, 255)))
        payload = {
            "project_root": self.project_root,
            "reference_id": "explain-ref",
            "source_image": str(source),
            "fixture": "popup.available",
            "regions": [
                {"id": "body", "rect": {"x": 0, "y": 0, "width": 120, "height": 160}},
                {"id": "footer", "rect": {"x": 0, "y": 160, "width": 120, "height": 80}},
            ],
            "acceptance": dict(VISUAL_ONLY_ACCEPTANCE),
            "workspace_root": str(self.workspace),
            "register_in_artifact_registry": False,
        }
        payload.update(overrides)
        register_ui_reference(**payload)

    def write_snapshot(self, payload: dict, name: str = "snapshot") -> str:
        path = self.captures / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def compare(self, image: png.RgbaImage, **overrides) -> dict:
        path = self.captures / f"{overrides.pop('capture_name', 'actual')}.png"
        png.write_png(path, image)
        payload = {
            "project_root": self.project_root,
            "reference_id": "explain-ref",
            "actual_image": str(path),
            "workspace_root": str(self.workspace),
            "register_in_artifact_registry": False,
            "emit_artifacts": False,
            "comparison_id": "explain",
        }
        payload.update(overrides)
        return compare_ui_reference(**payload)

    def test_failed_region_carries_the_node_that_explains_it(self) -> None:
        self.build()
        result = self.compare(
            self.solid((10, 10, 10, 255)),
            ui_snapshot_path=self.write_snapshot(
                snapshot(
                    [
                        node(
                            "Body",
                            bounds=(0.0, 0.0, 120.0, 240.0),
                            components=["RectTransform", "TextMeshProUGUI"],
                            has_text=True,
                            text="Body copy",
                            font_resolved_status="unresolved",
                        )
                    ],
                    width=120,
                    height=240,
                )
            ),
        )

        self.assertEqual("failed", result["visual_verdict"])
        region = result["regions"][0]
        self.assertEqual("font_unresolved", region["explained_by"]["likely_cause"])
        self.assertTrue(result["semantic_explanations"]["available"])
        self.assertTrue(
            any("font asset did not resolve" in action for action in result["next_actions"]),
            result["next_actions"],
        )

    def test_without_a_snapshot_the_verdict_says_how_to_get_the_explanation(self) -> None:
        self.build()
        result = self.compare(self.solid((10, 10, 10, 255)))

        self.assertFalse(result["semantic_explanations"]["available"])
        self.assertTrue(
            any("uiSnapshotPath" in action for action in result["next_actions"]),
            result["next_actions"],
        )

    def test_required_ui_failure_fails_the_reference_even_when_pixels_match(self) -> None:
        self.build(
            required_ui=[{"id": "cta", "selector": {"name": "ClaimButton"}}],
            acceptance={"visual": "required", "semantic": "required", "interaction": "not_required"},
        )
        expected = self.solid((240, 240, 240, 255))
        stability = self.captures / "stability.png"
        png.write_png(stability, expected)

        result = self.compare(
            expected,
            stability_image=str(stability),
            ui_snapshot_path=self.write_snapshot(
                snapshot([node("SomethingElse", bounds=(0.0, 0.0, 10.0, 10.0))], width=120, height=240)
            ),
        )

        self.assertEqual("passed", result["visual_verdict"])
        self.assertEqual("failed", result["reference_acceptance"])
        self.assertEqual("failed", result["acceptance_lanes"]["semantic"]["status"])
        self.assertEqual(["semantic"], result["failed_lanes"])

    def test_required_ui_satisfied_promotes_the_semantic_lane_to_passed(self) -> None:
        self.build(
            required_ui=[{"id": "cta", "selector": {"name": "ClaimButton"}}],
            acceptance={"visual": "required", "semantic": "required", "interaction": "not_required"},
        )
        expected = self.solid((240, 240, 240, 255))
        stability = self.captures / "stability.png"
        png.write_png(stability, expected)

        result = self.compare(
            expected,
            stability_image=str(stability),
            ui_snapshot_path=self.write_snapshot(
                snapshot(
                    [node("ClaimButton", bounds=(0.0, 0.0, 60.0, 60.0), components=["RectTransform", "Button"])],
                    width=120,
                    height=240,
                )
            ),
        )

        self.assertEqual("passed", result["acceptance_lanes"]["semantic"]["status"])
        self.assertEqual("passed", result["reference_acceptance"])

    def test_device_lane_records_context_and_never_borrows_game_view_evidence(self) -> None:
        self.build()
        expected = self.solid((240, 240, 240, 255))
        stability = self.captures / "stability.png"
        png.write_png(stability, expected)

        game_view = self.compare(expected, stability_image=str(stability))
        device = self.compare(
            expected,
            stability_image=str(stability),
            capture_lane="device",
            device={
                "model": "iPhone 15 Pro",
                "os": "iOS",
                "os_version": "17.4",
                "resolution": {"width": 120, "height": 240},
                "orientation": "portrait",
                "build_revision": "abc1234",
                "safe_area": {"top": 59, "bottom": 34},
            },
            comparison_id="device",
            capture_name="device-actual",
        )

        self.assertEqual("game_view", game_view["capture_lane"])
        self.assertEqual("not_evaluated", game_view["acceptance_lanes"]["device"]["status"])
        self.assertEqual("device", device["capture_lane"])
        self.assertEqual("passed", device["acceptance_lanes"]["device"]["status"])
        self.assertEqual("iPhone 15 Pro", device["device_context"]["model"])

    def test_a_required_device_lane_blocks_acceptance_end_to_end(self) -> None:
        acceptance = dict(VISUAL_ONLY_ACCEPTANCE)
        acceptance["device"] = "required"
        self.build(acceptance=acceptance)
        expected = self.solid((240, 240, 240, 255))
        stability = self.captures / "stability.png"
        png.write_png(stability, expected)

        result = self.compare(
            expected,
            stability_image=str(stability),
            capture_lane="device",
            device={"model": "Pixel 8"},
            comparison_id="device-required",
            capture_name="device-required-actual",
        )

        self.assertEqual("required", result["acceptance_lanes"]["device"]["requirement"])
        self.assertEqual("blocked", result["acceptance_lanes"]["device"]["status"])
        self.assertIn("device", result["blocked_lanes"])
        self.assertEqual("blocked", result["reference_acceptance"])
        self.assertFalse(result["decision_ready"])
        self.assertFalse(result["succeeded"])

    def test_invalid_capture_lane_is_a_typed_error(self) -> None:
        self.build()
        with self.assertRaises(ToolInvocationError) as caught:
            self.compare(self.solid((240, 240, 240, 255)), capture_lane="emulator")
        self.assertEqual("ui_reference_capture_lane_invalid", caught.exception.code)

    def test_snapshot_schema_mismatch_is_a_typed_error(self) -> None:
        path = self.captures / "bad.json"
        path.write_text(json.dumps({"schema_version": "xuunity.ui.read.v0"}), encoding="utf-8")

        with self.assertRaises(ToolInvocationError) as caught:
            load_ui_snapshot(str(path), self.workspace)
        self.assertEqual("ui_snapshot_schema_unsupported", caught.exception.code)

    def test_missing_snapshot_is_a_typed_error(self) -> None:
        with self.assertRaises(ToolInvocationError) as caught:
            load_ui_snapshot(str(self.captures / "nope.json"), self.workspace)
        self.assertEqual("ui_snapshot_not_found", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
