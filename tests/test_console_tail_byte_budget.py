from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import server_health as health


def make_item(message: str, stack_trace: str = "", item_type: str = "log") -> dict:
    return {"type": item_type, "message": message, "timestamp": "2026-08-14T12:00:00Z", "stack_trace": stack_trace}


class ResolveConsoleTailByteBudgetTests(unittest.TestCase):
    def test_omitted_and_zero_resolve_to_the_default(self) -> None:
        self.assertEqual(health.resolve_console_tail_byte_budget(None), 16384)
        self.assertEqual(health.resolve_console_tail_byte_budget(0), 16384)

    def test_any_negative_resolves_to_unbounded(self) -> None:
        self.assertEqual(health.resolve_console_tail_byte_budget(-1), -1)
        self.assertEqual(health.resolve_console_tail_byte_budget(-100), -1)

    def test_positive_values_are_kept(self) -> None:
        self.assertEqual(health.resolve_console_tail_byte_budget(4096), 4096)

    def test_non_numeric_input_falls_back_to_the_default(self) -> None:
        self.assertEqual(health.resolve_console_tail_byte_budget("not-a-number"), 16384)


class EstimateConsoleItemBytesTests(unittest.TestCase):
    def test_estimate_counts_utf8_bytes_plus_overhead(self) -> None:
        item = make_item("abc", stack_trace="de")
        expected = 64 + len("log") + len("abc") + len("2026-08-14T12:00:00Z") + len("de")
        self.assertEqual(health.estimate_console_item_bytes(item), expected)

    def test_multibyte_text_is_counted_in_bytes_not_chars(self) -> None:
        item = {"type": "", "message": "ррр", "timestamp": "", "stack_trace": ""}
        self.assertEqual(health.estimate_console_item_bytes(item), 64 + 6)

    def test_non_dict_items_cost_only_the_overhead(self) -> None:
        self.assertEqual(health.estimate_console_item_bytes(None), 64)


class ApplyConsoleTailByteBudgetTests(unittest.TestCase):
    def test_items_within_budget_are_untouched(self) -> None:
        payload = {"items": [make_item("a"), make_item("b")], "truncated": False}

        bounded = health.apply_console_tail_byte_budget(payload, None)

        self.assertEqual(len(bounded["items"]), 2)
        self.assertFalse(bounded["byte_budget_truncated"])
        self.assertEqual(bounded["items_dropped_for_byte_budget"], 0)
        self.assertEqual(bounded["max_payload_bytes"], 16384)
        self.assertEqual(bounded["byte_budget_enforced_by"], "host")
        self.assertNotIn("truncation_recovery_tool", bounded)

    def test_oldest_items_are_dropped_first_with_accounting(self) -> None:
        items = [make_item(f"item-{index}-" + "x" * 100) for index in range(5)]
        per_item = health.estimate_console_item_bytes(items[0])
        payload = {"items": items, "truncated": False}

        bounded = health.apply_console_tail_byte_budget(payload, per_item * 2 + 10)

        self.assertEqual(len(bounded["items"]), 2)
        self.assertIn("item-3", bounded["items"][0]["message"])
        self.assertIn("item-4", bounded["items"][1]["message"])
        self.assertEqual(bounded["items_dropped_for_byte_budget"], 3)
        self.assertTrue(bounded["byte_budget_truncated"])
        self.assertFalse(bounded["newest_item_truncated"])
        self.assertLessEqual(bounded["payload_bytes_estimate"], per_item * 2 + 10)
        self.assertEqual(bounded["truncation_recovery_tool"], "unity_console_grep")
        self.assertIn("maxPayloadBytes=-1", bounded["full_payload_recovery_hint"])

    def test_an_oversized_single_newest_item_is_content_truncated(self) -> None:
        items = [make_item("old"), make_item("giant-" + "y" * 5000, stack_trace="s" * 5000)]
        payload = {"items": items, "truncated": False}

        bounded = health.apply_console_tail_byte_budget(payload, 512)

        self.assertEqual(len(bounded["items"]), 1)
        self.assertTrue(bounded["newest_item_truncated"])
        self.assertTrue(bounded["byte_budget_truncated"])
        self.assertEqual(bounded["items_dropped_for_byte_budget"], 1)
        newest = bounded["items"][0]
        self.assertTrue(newest["message"].endswith("[truncated_by_byte_budget]"))
        self.assertTrue(newest["message"].startswith("giant-"))
        self.assertEqual(newest["stack_trace"], "")
        self.assertLessEqual(health.estimate_console_item_bytes(newest), 512)
        self.assertLessEqual(bounded["payload_bytes_estimate"], 512)

    def test_multibyte_content_is_truncated_on_a_valid_utf8_boundary(self) -> None:
        items = [make_item("р" * 4000)]
        payload = {"items": items, "truncated": False}

        bounded = health.apply_console_tail_byte_budget(payload, 256)

        message = bounded["items"][0]["message"]
        self.assertTrue(message.endswith("[truncated_by_byte_budget]"))
        message.encode("utf-8")

    def test_unbounded_negative_budget_keeps_everything(self) -> None:
        items = [make_item("x" * 50000) for _ in range(10)]
        payload = {"items": items, "truncated": False}

        bounded = health.apply_console_tail_byte_budget(payload, -1)

        self.assertEqual(len(bounded["items"]), 10)
        self.assertEqual(bounded["max_payload_bytes"], -1)
        self.assertFalse(bounded["byte_budget_truncated"])
        self.assertNotIn("truncation_recovery_tool", bounded)

    def test_count_truncated_payload_gets_grep_guidance_even_within_byte_budget(self) -> None:
        payload = {"items": [make_item("a")], "truncated": True}

        bounded = health.apply_console_tail_byte_budget(payload, None)

        self.assertFalse(bounded["byte_budget_truncated"])
        self.assertEqual(bounded["truncation_recovery_tool"], "unity_console_grep")

    def test_a_bridge_bounded_payload_is_not_re_enforced(self) -> None:
        payload = {
            "items": [make_item("x" * 100000)],
            "truncated": False,
            "max_payload_bytes": 16384,
            "byte_budget_enforced_by": "unity_bridge",
        }

        bounded = health.apply_console_tail_byte_budget(payload, 128)

        self.assertEqual(bounded["byte_budget_enforced_by"], "unity_bridge")
        self.assertEqual(len(bounded["items"][0]["message"]), 100000)

    def test_non_dict_items_are_filtered_out_before_bounding(self) -> None:
        payload = {"items": [None, "text", make_item("kept")], "truncated": False}

        bounded = health.apply_console_tail_byte_budget(payload, None)

        self.assertEqual(len(bounded["items"]), 1)
        self.assertEqual(bounded["items"][0]["message"], "kept")


class TailEditorLogByteBudgetIntegrationTests(unittest.TestCase):
    def test_editor_log_tail_is_byte_bounded_with_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "Editor.log"
            lines = [f"line-{index} " + "z" * 200 for index in range(40)]
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            payload = health.tail_editor_log_payload(
                Path(tmp),
                log_path,
                limit=50,
                bridge_state=None,
                bridge_state_is_live=False,
                max_payload_bytes=1024,
            )

            self.assertEqual(payload["max_payload_bytes"], 1024)
            self.assertTrue(payload["byte_budget_truncated"])
            self.assertGreater(payload["items_dropped_for_byte_budget"], 0)
            self.assertLessEqual(payload["payload_bytes_estimate"], 1024)
            self.assertEqual(payload["byte_budget_enforced_by"], "host")
            self.assertEqual(payload["truncation_recovery_tool"], "unity_console_grep")
            self.assertIn("line-39", payload["items"][-1]["message"])

    def test_editor_log_tail_defaults_to_the_16384_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "Editor.log"
            log_path.write_text("short line\n", encoding="utf-8")

            payload = health.tail_editor_log_payload(
                Path(tmp),
                log_path,
                limit=50,
                bridge_state=None,
                bridge_state_is_live=False,
            )

            self.assertEqual(payload["max_payload_bytes"], 16384)
            self.assertFalse(payload["byte_budget_truncated"])

    def test_editor_log_tail_supports_the_unbounded_raw_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "Editor.log"
            log_path.write_text("giant " + "q" * 100000 + "\n", encoding="utf-8")

            payload = health.tail_editor_log_payload(
                Path(tmp),
                log_path,
                limit=50,
                bridge_state=None,
                bridge_state_is_live=False,
                max_payload_bytes=-1,
            )

            self.assertEqual(payload["max_payload_bytes"], -1)
            self.assertFalse(payload["byte_budget_truncated"])
            self.assertGreater(len(payload["items"][0]["message"]), 100000 - 10)


if __name__ == "__main__":
    unittest.main()
