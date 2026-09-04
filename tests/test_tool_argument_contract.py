"""Required tool arguments are enforced by the server, not just declared in the schema.

`inputSchema.required` was advisory on both sides: a client that ignored it reached Unity with an invalid call.
That is not a free mistake. Observed on a real project: `unity_compile_player_scripts` arrived without `target`
against a dead editor, the mutating-operation path opened a Unity editor (`opened_by_host: true`, 31 s), attached
a new bridge generation, delivered the request, and only then did Unity reject it — reported as
`compile_player_scripts_failed`, which reads as a compile verdict for a compile that never ran.
"""

from __future__ import annotations

import json
import time
import os
import inspect
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates"
if str(TEMPLATES) not in sys.path:
    sys.path.insert(0, str(TEMPLATES))

import server_bridge_journal  # noqa: E402
import server_bridge_state  # noqa: E402
import server_health  # noqa: E402
import server_mcp_tools  # noqa: E402
import server_operation_evidence  # noqa: E402
import server_scenario_polling  # noqa: E402
import server_specs_tools  # noqa: E402
from server_core import parse_utc_timestamp  # noqa: E402

TOOLS = server_specs_tools.TOOLS


def unreachable_bridge(*args: object, **kwargs: object) -> dict[str, object]:
    raise AssertionError("an invalid call must never reach the bridge: that is what opens an editor")


def unreachable_project_root(value: str) -> Path:
    raise AssertionError("an invalid call must be refused before the project context is resolved")


def call(name: str, arguments: dict[str, object], **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "tools": TOOLS,
        "special_tool_handlers": {},
        "tool_invocation_error_type": RuntimeError,
        "ensure_project_root": unreachable_project_root,
        "resolve_operation_timeout_ms": lambda *a, **k: 5000,
        "invoke_bridge": unreachable_bridge,
        "build_tool_error_payload": lambda exc: {"error": str(exc)},
        "bridge_response_to_tool_result": lambda response, **kwargs: response,
    }
    kwargs.update(overrides)
    return server_mcp_tools.call_tool(name, arguments, **kwargs)  # type: ignore[arg-type]


class MissingRequiredArgumentTests(unittest.TestCase):
    def test_the_compile_call_that_opened_an_editor_is_now_refused_before_the_bridge(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError) as caught:
            call(
                "unity_compile_player_scripts",
                {"projectRoot": "/tmp/does-not-matter"},
            )

        message = str(caught.exception)
        self.assertIn("target", message)
        self.assertIn("Nothing was executed", message)

    def test_the_refusal_quotes_the_schema_so_the_call_can_be_fixed_from_the_error(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError) as caught:
            call("unity_compile_player_scripts", {"projectRoot": "/tmp/x"})

        message = str(caught.exception)
        self.assertIn("StandaloneOSX", message, "the schema documents the valid values; the error should too")

    def test_an_enum_argument_lists_its_values(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError) as caught:
            call("unity_playmode_set", {"projectRoot": "/tmp/x"})

        self.assertIn("action", str(caught.exception))

    def test_a_blank_string_counts_as_missing(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError):
            call("unity_console_grep", {"projectRoot": "/tmp/x", "pattern": "   "})

    def test_projectRoot_keeps_its_own_message(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError) as caught:
            call("unity_compile_player_scripts", {"target": "Android"})

        self.assertIn("projectRoot is required", str(caught.exception))


class SuppliedFalsyArgumentsAreNotMissingTests(unittest.TestCase):
    """`approve=false` and `width=0` are supplied values. Treating them as missing would break the refusal paths
    that exist to answer them — `unity_ui_click` is designed to refuse `approve=false` with
    `ui_click_approval_required`, which it can only do if the call is allowed through."""

    def test_approve_false_reaches_the_bridge(self) -> None:
        seen: dict[str, object] = {}

        def record_bridge(project_root: str, operation: str, args: dict[str, object], timeout_ms: int):
            seen["operation"] = operation
            seen["args"] = args
            return {"status": "ok", "payload_type": operation, "payload_json": "{}"}

        with tempfile.TemporaryDirectory() as tmp:
            call(
                "unity_ui_click",
                {"projectRoot": tmp, "selector": {"name": "Button"}, "approve": False},
                ensure_project_root=lambda value: Path(value),
                invoke_bridge=record_bridge,
            )

        self.assertEqual("unity.ui.click", seen["operation"])
        self.assertIs(False, seen["args"]["approve"])  # type: ignore[index]

    def test_zero_sized_arguments_reach_the_bridge(self) -> None:
        seen: dict[str, object] = {}

        def record_bridge(project_root: str, operation: str, args: dict[str, object], timeout_ms: int):
            seen["args"] = args
            return {"status": "ok", "payload_type": operation, "payload_json": "{}"}

        with tempfile.TemporaryDirectory() as tmp:
            call(
                "unity_game_view_configure",
                {"projectRoot": tmp, "width": 0, "height": 0},
                ensure_project_root=lambda value: Path(value),
                invoke_bridge=record_bridge,
            )

        self.assertEqual(0, seen["args"]["width"])  # type: ignore[index]

    def test_every_required_argument_is_satisfiable_without_a_falsy_trap(self) -> None:
        """A required argument whose only legal values are falsy would be permanently unsatisfiable."""

        for name, spec in TOOLS.items():
            required = spec.get("inputSchema", {}).get("required") or []
            properties = spec.get("inputSchema", {}).get("properties", {})
            for argument in required:
                enum_values = properties.get(argument, {}).get("enum")
                if not enum_values:
                    continue
                truthy = [value for value in enum_values if value not in (None, "", False)]
                self.assertTrue(
                    truthy,
                    f"{name}.{argument} declares only falsy enum values, so it could never be supplied",
                )


class InvalidArgumentsAreNotAnOperationFailureTests(unittest.TestCase):
    """Argument validation and a failed operation are different answers. Reporting both as
    `<operation>_failed` let a caller read `compile_player_scripts_failed` as a compile verdict — one did, and
    wrote a retro concluding the compile had run and failed."""

    def source(self, relative: str) -> str:
        return (REPO_ROOT / "packages" / "com.xuunity.light-mcp" / "Editor" / relative).read_text(encoding="utf-8")

    def test_the_editor_reports_a_distinct_code_for_bad_arguments(self) -> None:
        guard = self.source("Helpers/XUUnityLightMcpEditorBusyGuard.cs")

        self.assertIn("XUUnityLightMcpInvalidArgumentsException", guard)
        self.assertIn('InvalidArgumentsCode = "operation_arguments_invalid"', guard)
        self.assertIn("IXUUnityLightMcpCodedException", guard)

    def test_every_coded_exception_maps_through_one_resolver(self) -> None:
        guard = self.source("Helpers/XUUnityLightMcpEditorBusyGuard.cs")

        self.assertIn("if (exception is IXUUnityLightMcpCodedException coded", guard)

    def test_compile_argument_errors_name_the_parameter_and_its_values(self) -> None:
        utility = self.source("Helpers/XUUnityLightMcpCompileUtility.cs")

        self.assertNotIn('InvalidOperationException("Compile target is required.")', utility)
        self.assertIn("target is required", utility)
        self.assertIn("StandaloneOSX", utility)
        self.assertIn("Nothing was compiled", utility)

    def test_an_unknown_target_also_says_nothing_was_compiled(self) -> None:
        utility = self.source("Helpers/XUUnityLightMcpCompileUtility.cs")

        self.assertIn("is not a Unity BuildTarget enum name", utility)


class SchemaRequiredListsAreHonestTests(unittest.TestCase):
    def test_declared_required_names_exist_as_properties(self) -> None:
        for name, spec in TOOLS.items():
            schema = spec.get("inputSchema", {})
            properties = schema.get("properties", {})
            for argument in schema.get("required") or []:
                self.assertIn(
                    argument,
                    properties,
                    f"{name} requires {argument!r} but never declares it, so the error cannot describe it",
                )

    def test_the_missing_argument_helper_ignores_undeclared_extras(self) -> None:
        tool = {"inputSchema": {"required": ["a"], "properties": {"a": {"type": "string"}}}}

        self.assertEqual([], server_mcp_tools.missing_required_arguments(tool, {"a": "x", "b": None}))
        self.assertEqual(["a"], server_mcp_tools.missing_required_arguments(tool, {"b": 1}))


class DeclaredArgumentTypeTests(unittest.TestCase):
    def test_scalar_test_names_is_refused_before_project_resolution_or_unity(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError) as caught:
            call(
                "unity_tests_run_editmode",
                {"projectRoot": "/tmp/does-not-matter", "testNames": "Namespace.Test"},
            )

        message = str(caught.exception)
        self.assertIn("unity_tests_run_editmode.testNames must be array", message)
        self.assertIn("Nothing was executed", message)

    def test_test_filter_arrays_reject_non_string_items(self) -> None:
        with self.assertRaises(server_mcp_tools.JsonRpcError) as caught:
            call(
                "unity_tests_run_playmode",
                {"projectRoot": "/tmp/does-not-matter", "testNames": ["Namespace.Test", 7]},
            )

        self.assertIn("array of string values", str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class StaleStateIsNotReportedAsReadyTests(unittest.TestCase):
    """A dead editor's state file still says `listener_state: listening`. `build_bridge_stabilization_summary`
    accepted an `editor_running` argument but defaulted it to `True`, and four of its five callers rely on the
    default, so a stale file produced `stabilized: true` / `safe_to_retry: true` in the same payload whose
    `host_health_classification` said `offline`."""

    def test_a_dead_pid_in_the_state_blocks_stabilization(self) -> None:
        import server_bridge_final_status as final_status

        summary = final_status.build_bridge_stabilization_summary(
            {
                "health_status": "healthy",
                "transport": "tcp_loopback",
                "transport_listener_state": "listening",
                "editor_pid": 999_999,
            }
        )

        self.assertFalse(summary["stabilized"])
        self.assertFalse(summary["safe_to_retry"])
        self.assertIn("editor_not_running", summary["blocking_reasons"])

    def test_a_live_pid_still_stabilizes(self) -> None:
        import os

        import server_bridge_final_status as final_status

        summary = final_status.build_bridge_stabilization_summary(
            {
                "health_status": "healthy",
                "transport": "tcp_loopback",
                "transport_listener_state": "listening",
                "editor_pid": os.getpid(),
            }
        )

        self.assertTrue(summary["stabilized"], "the guard must not refuse a live editor")
        self.assertEqual([], summary["blocking_reasons"])

    def test_a_state_with_no_pid_stays_unknowable(self) -> None:
        import server_bridge_final_status as final_status

        summary = final_status.build_bridge_stabilization_summary(
            {"health_status": "healthy", "transport": "tcp_loopback", "transport_listener_state": "listening"}
        )

        self.assertTrue(summary["stabilized"], "with nothing to check, the previous optimistic answer stands")

    def test_an_explicit_argument_still_wins(self) -> None:
        import os

        import server_bridge_final_status as final_status

        summary = final_status.build_bridge_stabilization_summary(
            {"health_status": "healthy", "transport": "file_ipc", "editor_pid": os.getpid()},
            editor_running=False,
        )

        self.assertIn("editor_not_running", summary["blocking_reasons"])


class EditorOpenedByThisCallIsVisibleTests(unittest.TestCase):
    """A mutating operation can launch Unity as a side effect. That fact lived only inside
    `_xuunity_lifecycle.activation`, so a caller reading the payload kept reporting the editor as not running."""

    def lifecycle(self) -> dict[str, object]:
        return {
            "operation": "unity.compile.player_scripts",
            "activation": {
                "action": "opened_editor",
                "editor_opened_by_this_call": True,
                "editor_open_started_utc": "2026-08-04T21:23:58Z",
                "editor_open_completed_utc": "2026-08-04T21:24:14Z",
                "editor_open_duration_seconds": 16.4,
                "editor_open_note": "This call opened a Unity editor for the project.",
            },
        }

    def result(self, *, include_full_payload: bool) -> dict[str, object]:
        import server_bridge_payloads as payloads

        response = {
            "status": "ok",
            "payload_type": "unity.compile.player_scripts",
            "payload_json": json.dumps({"result": {"status": "ok"}}),
            "_xuunity_lifecycle": self.lifecycle(),
        }
        out = payloads.bridge_response_to_tool_result(
            response,
            normalize_scenario_payload=lambda payload, statuses: payload,
            scenario_terminal_statuses=set(),
            include_full_payload=include_full_payload,
        )
        return out["structuredContent"]

    def test_the_compact_envelope_keeps_the_attribution(self) -> None:
        payload = self.result(include_full_payload=False)

        self.assertTrue(payload["editor_opened_by_this_call"])
        self.assertEqual(16.4, payload["editor_open_duration_seconds"])
        self.assertIn("opened a Unity editor", str(payload["editor_open_note"]))

    def test_the_full_payload_keeps_the_attribution(self) -> None:
        payload = self.result(include_full_payload=True)

        self.assertTrue(payload["editor_opened_by_this_call"])

    def test_an_already_ready_editor_adds_nothing(self) -> None:
        import server_bridge_payloads as payloads

        self.assertEqual(
            {},
            payloads.hoist_editor_open_attribution(
                {"operation": "unity.status", "activation": {"action": "already_ready"}}
            ),
        )


class HostileTimezoneStampTests(unittest.TestCase):
    """A UTC stamp must parse identically on every host.

    `time.mktime` reads a struct as local time, so the original conversion was exact on a host without DST and off
    by 3600 s where DST applies — the error landing in the opposite half of the year in the southern hemisphere.
    That hour feeds the log-lane staleness threshold and the rotation guard, so it decides whether evidence is
    accepted. This host has no DST, which is precisely why the defect was invisible until it was forced.
    """

    def setUp(self) -> None:
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset is unavailable on this platform")
        self._original_tz = os.environ.get("TZ")

    def tearDown(self) -> None:
        if self._original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._original_tz
        time.tzset()

    def parse_under(self, timezone_name: str, stamp: str) -> tuple[dict[str, float | None], int]:
        import calendar

        os.environ["TZ"] = timezone_name
        time.tzset()
        return (
            {
                "core": parse_utc_timestamp(stamp),
                "bridge_state": server_bridge_state.parse_utc_timestamp(stamp),
                "journal": server_bridge_journal.parse_journal_utc_timestamp(stamp),
                "operation_evidence": server_operation_evidence.parse_utc_timestamp(stamp),
                "scenario_polling": server_scenario_polling.parse_utc_seconds(stamp),
                "health": server_health._parse_stamp_utc(stamp),
            },
            calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")),
        )

    def test_the_stamp_parses_exactly_under_dst_timezones(self) -> None:
        cases = [
            ("Europe/Berlin", "2026-08-04T22:28:53Z"),
            ("Europe/Berlin", "2026-01-15T03:00:00Z"),
            ("America/New_York", "2026-08-04T22:28:53Z"),
            ("Australia/Sydney", "2026-01-15T03:00:00Z"),
            ("UTC", "2026-08-04T22:28:53Z"),
        ]
        for timezone_name, stamp in cases:
            with self.subTest(timezone=timezone_name, stamp=stamp):
                parsed, expected = self.parse_under(timezone_name, stamp)
                self.assertEqual(
                    {name: float(expected) for name in parsed},
                    parsed,
                    f"{timezone_name} {stamp}",
                )

    def test_heartbeat_age_uses_the_shared_timezone_safe_parser(self) -> None:
        stamp = "2026-08-04T22:28:53Z"
        expected_epoch = 1785882533.0
        with mock.patch.object(server_bridge_state.time, "time", return_value=expected_epoch + 3.5):
            self.assertEqual(3.5, server_bridge_state.heartbeat_age_seconds({"heartbeat_utc": stamp}))

    def test_each_legacy_empty_contract_is_preserved(self) -> None:
        for parser in (
            parse_utc_timestamp,
            server_bridge_state.parse_utc_timestamp,
            server_operation_evidence.parse_utc_timestamp,
            server_scenario_polling.parse_utc_seconds,
        ):
            self.assertIsNone(parser(""))
            self.assertIsNone(parser("not a stamp"))
        self.assertEqual(0.0, server_bridge_journal.parse_journal_utc_timestamp(""))
        self.assertEqual(0.0, server_bridge_journal.parse_journal_utc_timestamp("not a stamp"))

    def test_bridge_state_keeps_its_strict_whitespace_contract(self) -> None:
        stamp = "2026-08-04T22:28:53Z"
        self.assertIsNotNone(server_bridge_state.parse_utc_timestamp(stamp))
        self.assertIsNone(server_bridge_state.parse_utc_timestamp(f" {stamp}"))
        self.assertIsNone(server_bridge_state.parse_utc_timestamp(f"{stamp} "))

    def test_a_blank_or_malformed_stamp_is_zero_not_an_exception(self) -> None:
        self.assertEqual(0.0, server_health._parse_stamp_utc(""))
        self.assertEqual(0.0, server_health._parse_stamp_utc("not a stamp"))
        self.assertEqual(0.0, server_health._parse_stamp_utc(None))


class PlatformPathEqualityTests(unittest.TestCase):
    """Path equality must follow the platform, because the anchor guards compare a stamped log path against the
    searched one exactly when one of them may no longer exist — a rotated or deleted log. The string fallback was
    case- and separator-sensitive, so on Windows a valid anchor was refused as `anchor_log_mismatch`."""

    def test_an_existing_file_is_the_same_file_through_two_spellings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "Editor.log"
            log.write_bytes(b"line\n")

            self.assertTrue(server_health._same_path(log, root / "." / "Editor.log"))

    def test_equality_uses_the_platform_rule_for_absent_files(self) -> None:
        import ntpath
        import posixpath

        upper = "C:\\Users\\u\\AppData\\Local\\Unity\\Editor\\Editor.log"
        lower = "c:/users/u/appdata/local/unity/editor/editor.log"

        # The comparison the fix relies on: normcase folds case and separators on Windows and is identity on POSIX.
        self.assertEqual(ntpath.normcase(upper), ntpath.normcase(lower))
        self.assertNotEqual(posixpath.normcase(upper), posixpath.normcase(lower))
        self.assertIn("normcase", inspect.getsource(server_health._same_path))

    def test_distinct_files_are_still_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Editor.log").write_bytes(b"a\n")
            (root / "Editor-prev.log").write_bytes(b"b\n")

            self.assertFalse(server_health._same_path(root / "Editor.log", root / "Editor-prev.log"))


class EditorLogSearchBoundsContractTests(unittest.TestCase):
    """The MCP schema, the MCP rejection and the CLI clamp must bound the same window.

    The tool schema refuses an out-of-range maxSearchChars while the CLI clamps it, which is a
    deliberate split: a protocol call must not be silently narrowed, an operator command may be.
    The split is only safe while both sides use the same bounds.
    """

    def test_the_tool_schema_bounds_match_the_shared_constants(self) -> None:
        schema = TOOLS["unity_console_grep"]["inputSchema"]["properties"]["maxSearchChars"]

        self.assertEqual(server_health.EDITOR_LOG_GREP_MAX_CHARS, schema["default"])
        self.assertEqual(server_health.EDITOR_LOG_GREP_MIN_CHARS, schema["minimum"])
        self.assertEqual(server_health.EDITOR_LOG_GREP_ABS_MAX_CHARS, schema["maximum"])

    def test_the_cli_clamps_through_the_same_constants(self) -> None:
        source = (TEMPLATES / "server_cli_bridge_commands.py").read_text(encoding="utf-8")

        self.assertIn("EDITOR_LOG_GREP_MIN_CHARS", source)
        self.assertIn("EDITOR_LOG_GREP_ABS_MAX_CHARS", source)
        self.assertNotIn("min(10000000", source)
