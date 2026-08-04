"""Required tool arguments are enforced by the server, not just declared in the schema.

`inputSchema.required` was advisory on both sides: a client that ignored it reached Unity with an invalid call.
That is not a free mistake. Observed on a real project: `unity_compile_player_scripts` arrived without `target`
against a dead editor, the mutating-operation path opened a Unity editor (`opened_by_host: true`, 31 s), attached
a new bridge generation, delivered the request, and only then did Unity reject it — reported as
`compile_player_scripts_failed`, which reads as a compile verdict for a compile that never ran.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates"
if str(TEMPLATES) not in sys.path:
    sys.path.insert(0, str(TEMPLATES))

import server_mcp_tools  # noqa: E402
import server_specs_tools  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
