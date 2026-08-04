"""Evidence-surface contract from the 2026-08-03 multi-scene UI targeting retro.

Every case here encodes a way the previous evidence layer misled an operator:

- an unanchored `source=editor_log` grep matched a marker line written by a *previous* play session,
  so a shell wait loop returned immediately on a stale line;
- a live-editor batch refusal was counted as `projects_failed`, which reads as "the code does not compile";
- a compile refused during Play Mode reported a generic "editor is busy";
- a refresh that settled during Play Mode reported `post_settle_compile: passed` while asset import was deferred;
- `includeImage: true` returned a 184k-character payload whose only useful field was `file_path`;
- `unity_ui_*` resolved targets in the active scene only, and said `ui_target_not_found` when the object
  was merely out of scope.

The C# half of the UI-scope contract is asserted from source here because it needs a live editor to run.
"""

import json
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates"
RUNNER_DIR = REPO_ROOT / "scripts" / "testing"
for candidate in (TEMPLATES_DIR, RUNNER_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import run_multi_project
import server_bridge_payloads
import server_health
import server_specs

PACKAGE_EDITOR_ROOT = REPO_ROOT / "packages" / "com.xuunity.light-mcp" / "Editor"


def write_log(path: Path, text: str, newline: str = "\n") -> bytes:
    """Write a log byte-exactly and return the bytes written.

    Path.write_text() applies platform newline translation, so on Windows every "\n" becomes "\r\n" and the
    file stops matching a byte offset the test computed from the source string. Anchors are byte offsets, so
    these tests must own the exact bytes. `newline` also lets a case assert the CRLF layout Unity writes on
    Windows rather than merely neutralising it.
    """

    data = text.replace("\n", newline).encode("utf-8")
    path.write_bytes(data)
    return data


def read_source(relative: str) -> str:
    return (PACKAGE_EDITOR_ROOT / relative).read_text(encoding="utf-8")


class EditorLogSinceAnchorTests(unittest.TestCase):
    """A `since` anchor must bound the search to the current session, not the whole accumulated log."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.log = self.root / "Editor.log"
        self.stale = "hook fired MARKER\n" * 3
        self.fresh = "hook fired MARKER\n" * 2
        self.offset = len(write_log(self.log, self.stale))
        write_log(self.log, self.stale + self.fresh)
        self.bridge_state = {
            "editor_log_offset_at_playmode_start": self.offset,
            "editor_log_playmode_started_utc": "2026-08-03T10:00:00Z",
            "editor_log_offset_at_bridge_generation_start": self.offset,
            "editor_log_offset_bridge_generation": 7,
        }

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_unanchored_grep_still_matches_previous_session_lines(self) -> None:
        payload = server_health.grep_editor_log_payload(self.root, self.log, pattern="MARKER")

        self.assertEqual(5, payload["match_count"])
        self.assertEqual("editor_log_spans_multiple_sessions", payload["result_trust_class"])
        self.assertTrue(payload["stale_match_caveat"])
        self.assertFalse(payload["since_anchor_degraded"])

    def test_playmode_anchor_excludes_previous_session_lines(self) -> None:
        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state=self.bridge_state,
        )

        self.assertEqual(2, payload["match_count"])
        self.assertEqual("session_scoped_editor_log", payload["result_trust_class"])
        self.assertEqual("", payload["stale_match_caveat"])
        self.assertEqual("playmode_start", payload["since_anchor"]["resolved"])
        self.assertEqual(self.offset, payload["since_anchor"]["start_offset_bytes"])

    def test_anchored_line_numbers_stay_absolute_in_the_editor_log(self) -> None:
        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state=self.bridge_state,
        )

        self.assertEqual("editor_log_absolute", payload["line_numbering_basis"])
        self.assertEqual(4, payload["searched_from_line"])
        self.assertEqual([4, 5], [item["line"] for item in payload["items"]])

    def test_bridge_generation_anchor_echoes_the_generation_it_resolved(self) -> None:
        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="bridge_generation",
            bridge_state=self.bridge_state,
        )

        self.assertTrue(payload["since_anchor"]["anchored"])
        self.assertEqual(7, payload["since_anchor"]["bridge_generation"])

    def test_a_requested_anchor_the_editor_never_recorded_is_reported_not_faked(self) -> None:
        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={},
        )

        self.assertEqual("anchor_unavailable", payload["since_anchor"]["resolved"])
        self.assertTrue(payload["since_anchor_degraded"])
        self.assertTrue(payload["stale_match_caveat"])
        self.assertTrue(payload["since_anchor"]["recommended_next_action"])

    def test_a_rotated_log_smaller_than_the_offset_is_reported_as_stale(self) -> None:
        write_log(self.log, "short\n")

        anchor = server_health.resolve_editor_log_since_anchor(
            self.log,
            since="playmode_start",
            bridge_state=self.bridge_state,
        )

        self.assertEqual("anchor_stale", anchor["resolved"])
        self.assertFalse(anchor["anchored"])

    def test_unsupported_anchor_names_the_supported_set(self) -> None:
        anchor = server_health.resolve_editor_log_since_anchor(self.log, since="last_tuesday")

        self.assertEqual("unsupported_anchor", anchor["resolved"])
        self.assertEqual(list(server_health.SINCE_ANCHORS), anchor["supported_anchors"])

    def test_request_id_anchor_uses_the_offset_the_editor_journalled(self) -> None:
        """Per-request anchoring answers "did *this* call log it", which playmode_start cannot: one play session
        holds many operations. The offset comes from the request_started journal event, so it costs one stat per
        operator-issued request and never a stat inside the 0.5 s request pump."""

        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="request_id",
            since_request_id="req-42",
            journal_events=[
                {"event_type": "request_submitted", "request_id": "req-42"},
                {"event_type": "request_started", "request_id": "req-42", "editor_log_offset_bytes": self.offset},
                {"event_type": "request_completed", "request_id": "req-42"},
            ],
        )

        self.assertEqual(2, payload["match_count"])
        self.assertEqual("session_scoped_editor_log", payload["result_trust_class"])
        self.assertEqual("request_id", payload["since_anchor"]["resolved"])
        self.assertEqual("req-42", payload["since_anchor"]["since_request_id"])
        self.assertEqual(self.offset, payload["since_anchor"]["start_offset_bytes"])

    def test_request_id_anchor_without_a_request_id_says_so(self) -> None:
        anchor = server_health.resolve_editor_log_since_anchor(self.log, since="request_id")

        self.assertEqual("anchor_argument_missing", anchor["resolved"])
        self.assertFalse(anchor["anchored"])

    def test_a_journal_without_the_offset_degrades_instead_of_guessing(self) -> None:
        """Requests journalled by an older package carry no offset; that must not silently widen the search."""

        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="request_id",
            since_request_id="req-old",
            journal_events=[{"event_type": "request_started", "request_id": "req-old"}],
        )

        self.assertEqual("anchor_unavailable", payload["since_anchor"]["resolved"])
        self.assertTrue(payload["since_anchor_degraded"])
        self.assertIn("journal", payload["since_anchor"]["anchor_unavailable_reason"])

    def test_the_editor_journals_the_offset_at_request_start_not_in_the_pump(self) -> None:
        package = REPO_ROOT / "packages" / "com.xuunity.light-mcp" / "Editor"
        journal = (package / "Bridge" / "XUUnityLightMcpRequestJournal.cs").read_text(encoding="utf-8")
        models = (package / "Core" / "XUUnityLightMcpBridgeModels.cs").read_text(encoding="utf-8")

        self.assertIn("public long editor_log_offset_bytes;", models)
        started = journal.index("WriteRequestStarted")
        completed = journal.index("WriteRequestCompleted")
        offset_call = journal.index("XUUnityLightMcpEditorLogAnchors.CurrentEditorLogLengthBytes()")
        self.assertTrue(started < offset_call < completed, "the offset must be stamped by WriteRequestStarted")
        self.assertEqual(
            1,
            journal.count("XUUnityLightMcpEditorLogAnchors.CurrentEditorLogLengthBytes()"),
            "one stat per started request; never a second call site",
        )

    def test_both_console_tools_accept_the_request_id_argument(self) -> None:
        for tool_name in ("unity_console_grep", "unity_console_tail"):
            with self.subTest(tool=tool_name):
                self.assertIn("sinceRequestId", server_specs.TOOLS[tool_name]["inputSchema"]["properties"])

    def test_an_offset_measured_against_a_different_log_is_refused(self) -> None:
        """The editor stamps offsets against Application.consoleLogPath; the host defaults to the project-local
        log. Those are the same file only when the host launched the editor with -logFile. An editor opened from
        the Hub writes to the platform Editor.log, and applying its offset to the project-local log would scope
        the search to an arbitrary byte while still reporting session_scoped_editor_log — the precise class of
        false trust this retro exists to remove."""

        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={
                **self.bridge_state,
                "editor_log_path": "/somewhere/else/Library/Logs/Unity/Editor.log",
            },
        )

        self.assertEqual("anchor_log_mismatch", payload["since_anchor"]["resolved"])
        self.assertFalse(payload["since_anchor"]["anchored"])
        self.assertTrue(payload["since_anchor_degraded"])
        self.assertTrue(payload["stale_match_caveat"])
        self.assertEqual(5, payload["match_count"], "must fall back to the full tail, not a bogus scope")
        self.assertEqual("editor_log_spans_multiple_sessions", payload["result_trust_class"])
        self.assertIn("editorLogPath", payload["since_anchor"]["recommended_next_action"])

    def test_a_matching_log_path_still_anchors(self) -> None:
        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={**self.bridge_state, "editor_log_path": str(self.log)},
        )

        self.assertEqual("playmode_start", payload["since_anchor"]["resolved"])
        self.assertEqual(2, payload["match_count"])

    def test_the_request_id_anchor_is_guarded_by_the_same_check(self) -> None:
        payload = server_health.grep_editor_log_payload(
            self.root,
            self.log,
            pattern="MARKER",
            since="request_id",
            since_request_id="req-42",
            bridge_state={"editor_log_path": "/somewhere/else/Editor.log"},
            journal_events=[
                {"event_type": "request_started", "request_id": "req-42", "editor_log_offset_bytes": self.offset}
            ],
        )

        self.assertEqual("anchor_log_mismatch", payload["since_anchor"]["resolved"])
        self.assertEqual(5, payload["match_count"])

    def test_an_offset_landing_mid_line_cannot_fabricate_a_match(self) -> None:
        """The editor records FileInfo.Length at a moment in time, so the offset can land inside a partially
        written line. Keeping the fragment lets a pattern match text the real line does not contain: an offset
        splitting "xxNOMARKER here" leaves "MARKER here", which a grep for MARKER reported as a hit on a line
        that literally says NOMARKER — with result_trust_class session_scoped_editor_log and an empty caveat.
        A false positive wearing a trust label is exactly what this retro exists to remove."""

        log = self.root / "midline.log"
        write_log(log, "L1aaaaaa\nxxNOMARKER here\nL3cccccc\n")

        payload = server_health.grep_editor_log_payload(
            self.root,
            log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={"editor_log_offset_at_playmode_start": 13, "editor_log_path": str(log)},
        )

        self.assertTrue(payload["since_anchor"]["starts_mid_line"])
        self.assertTrue(payload["since_anchor"]["partial_leading_line_dropped"])
        self.assertEqual(0, payload["match_count"], "the NOMARKER line must not be reported as a MARKER hit")

    def test_dropping_the_partial_line_advances_the_reported_start_line(self) -> None:
        log = self.root / "midline2.log"
        write_log(log, "L1aaaaaaa\nL2bbbbbbb\nL3MARKERc\nL4ddddddd\nL5MARKERe\n")

        payload = server_health.grep_editor_log_payload(
            self.root,
            log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={"editor_log_offset_at_playmode_start": 22, "editor_log_path": str(log)},
        )

        self.assertEqual(4, payload["searched_from_line"], "line 3 was partial and dropped")
        self.assertEqual([5], [item["line"] for item in payload["items"]])

    def test_a_crlf_log_anchors_on_real_byte_offsets(self) -> None:
        """Unity writes CRLF on Windows. Both sides of the anchor deal in real bytes - the editor stamps
        FileInfo.Length, the host seeks to that byte - and a CRLF line still carries exactly one b"\n", so the
        line counter stays right. This case exists because the LF-only fixtures passed on macOS while the
        Windows CI leg failed: the tests, not the product, were assuming LF."""

        log = self.root / "crlf.log"
        stale = write_log(log, "hook fired MARKER\n" * 3, newline="\r\n")
        write_log(log, "hook fired MARKER\n" * 5, newline="\r\n")

        payload = server_health.grep_editor_log_payload(
            self.root,
            log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={"editor_log_offset_at_playmode_start": len(stale), "editor_log_path": str(log)},
        )

        self.assertEqual(57, len(stale), "three CRLF lines are 19 bytes each, not 18")
        self.assertEqual(2, payload["match_count"])
        self.assertFalse(payload["since_anchor"]["starts_mid_line"])
        self.assertEqual(4, payload["searched_from_line"])
        self.assertEqual([4, 5], [item["line"] for item in payload["items"]])

    def test_a_crlf_offset_landing_mid_line_still_drops_the_fragment(self) -> None:
        log = self.root / "crlf_mid.log"
        write_log(log, "L1aaaaaa\nxxNOMARKER here\nL3cccccc\n", newline="\r\n")

        payload = server_health.grep_editor_log_payload(
            self.root,
            log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={"editor_log_offset_at_playmode_start": 14, "editor_log_path": str(log)},
        )

        self.assertTrue(payload["since_anchor"]["starts_mid_line"])
        self.assertEqual(0, payload["match_count"], "the NOMARKER line must not be reported as a MARKER hit")

    def test_an_offset_on_a_line_boundary_keeps_the_whole_first_line(self) -> None:
        log = self.root / "boundary.log"
        write_log(log, "L1aaaaaaa\nL2bbbbbbb\nL3MARKERc\nL4ddddddd\nL5MARKERe\n")

        payload = server_health.grep_editor_log_payload(
            self.root,
            log,
            pattern="MARKER",
            since="playmode_start",
            bridge_state={"editor_log_offset_at_playmode_start": 20, "editor_log_path": str(log)},
        )

        self.assertFalse(payload["since_anchor"]["starts_mid_line"])
        self.assertNotIn("partial_leading_line_dropped", payload["since_anchor"])
        self.assertEqual([3, 5], [item["line"] for item in payload["items"]])

    def test_a_truncated_scope_does_not_mix_absolute_and_relative_line_numbers(self) -> None:
        """read_editor_log_scope keeps the TAIL of the scope, so the window no longer starts at the anchor.
        Reporting searched_from_line as the anchor's absolute line next to window-relative item numbers was
        self-contradictory. The anchor line keeps its own key instead."""

        log = self.root / "big.log"
        write_log(log, "".join(f"line{n:05d} " + "x" * 38 + "\n" for n in range(1, 2001)))

        payload = server_health.grep_editor_log_payload(
            self.root,
            log,
            pattern="line0",
            since="playmode_start",
            limit=3,
            max_chars=2000,
            bridge_state={"editor_log_offset_at_playmode_start": 500, "editor_log_path": str(log)},
        )
        anchor = payload["since_anchor"]

        self.assertTrue(anchor["scope_truncated"])
        self.assertEqual("anchored_scope_relative", payload["line_numbering_basis"])
        self.assertEqual(1, payload["searched_from_line"], "relative basis must start its own numbering at 1")
        self.assertGreater(anchor["anchor_line"], 1, "the absolute anchor line keeps its own key")

    def test_tail_honours_the_same_anchor(self) -> None:
        payload = server_health.tail_editor_log_payload(
            self.root,
            self.log,
            limit=10,
            since="playmode_start",
            bridge_state=self.bridge_state,
        )

        self.assertEqual(2, payload["tail_count"])
        self.assertEqual(4, payload["items"][0]["line"])
        self.assertEqual("session_scoped_editor_log", payload["result_trust_class"])

    def test_both_console_tools_expose_the_anchor(self) -> None:
        for tool_name in ("unity_console_grep", "unity_console_tail"):
            with self.subTest(tool=tool_name):
                schema = server_specs.TOOLS[tool_name]["inputSchema"]["properties"]
                self.assertIn("since", schema)
                self.assertEqual(list(server_health.SINCE_ANCHORS), schema["since"]["enum"])


class AnchorStateResolutionIsBestEffortTests(unittest.TestCase):
    """Reading an Editor.log must not start requiring a resolvable Unity project context.

    The log is path-backed, and the console tools are exactly what an operator reaches for when the project is
    in a bad state. Resolving a `since` anchor needs bridge state, but that lookup is best-effort: an
    unresolvable project context degrades to an unanchored search, which the payload already reports.
    """

    def _modules(self):
        import server_batch_orchestrator
        import server_cli_bridge_commands

        return (
            ("server_batch_orchestrator", server_batch_orchestrator),
            ("server_cli_bridge_commands", server_cli_bridge_commands),
        )

    def test_no_anchor_requested_never_touches_the_project_context(self) -> None:
        for name, module in self._modules():
            with self.subTest(module=name):
                self.assertEqual(({}, {}), module.editor_log_anchor_state("/definitely/not/a/unity/project", ""))

    def test_an_unresolvable_project_context_degrades_instead_of_raising(self) -> None:
        for name, module in self._modules():
            with self.subTest(module=name):
                self.assertEqual(
                    ({}, {}),
                    module.editor_log_anchor_state("/definitely/not/a/unity/project", "playmode_start"),
                )

    def test_the_journal_lookup_branch_actually_executes_in_both_entrypoints(self) -> None:
        """Executes the branch, not just the early return.

        `server_cli_bridge_commands` is a `from server_cli_shared import *` module, so a name the helper body
        needs but the star-import does not re-export is a latent NameError on an untested branch. That is exactly
        what shipped here: a 738-test suite stayed green while the live CLI raised
        `NameError: read_request_journal_events`. Asserting the early return is not enough — the call must reach
        the journal read.
        """

        for name, module in self._modules():
            with self.subTest(module=name):
                self.assertEqual(
                    [],
                    module.editor_log_anchor_journal(Path("/definitely/not/a/unity/project"), "request_id", "req-1"),
                )

    def test_the_journal_lookup_is_skipped_for_every_other_anchor(self) -> None:
        for name, module in self._modules():
            for since in ("", "playmode_start", "bridge_generation"):
                with self.subTest(module=name, since=since):
                    self.assertEqual([], module.editor_log_anchor_journal(Path("/nope"), since, "req-1"))

    def test_both_entrypoints_share_one_helper_rather_than_duplicating_it(self) -> None:
        import server_batch_orchestrator
        import server_cli_bridge_commands

        for helper in ("editor_log_anchor_state", "editor_log_anchor_journal"):
            with self.subTest(helper=helper):
                self.assertIs(
                    getattr(server_batch_orchestrator, helper),
                    getattr(server_cli_bridge_commands, helper),
                )


class PostSettleCompileTrustTests(unittest.TestCase):
    """A refresh that settles during Play Mode defers asset import, so its compile verdict is not authoritative."""

    def _refresh(self, playmode_state: str, *, is_playing: bool) -> dict:
        return server_bridge_payloads.normalize_refresh_payload_from_lifecycle(
            {"outcome": "refresh_completed", "settle_request_id": "req-1"},
            {
                "operation": "unity.project.refresh",
                "idle_wait_after": {
                    "heartbeat_utc": "2026-08-03T10:00:00Z",
                    "is_compiling": False,
                    "is_updating": False,
                    "is_playing": is_playing,
                    "playmode_state": playmode_state,
                    "compiler_error_count": 0,
                    "script_compilation_failed": False,
                    "recent_compiler_diagnostics": [],
                },
            },
        )

    def test_refresh_in_edit_mode_is_a_confirmed_green(self) -> None:
        payload = self._refresh("edit", is_playing=False)

        self.assertEqual("passed", payload["post_settle_compile"])
        self.assertEqual("confirmed", payload["post_settle_compile_trust_class"])

    def test_refresh_during_playmode_marks_the_green_as_deferred(self) -> None:
        payload = self._refresh("playing", is_playing=True)

        self.assertEqual("passed", payload["post_settle_compile"])
        self.assertEqual("deferred_during_playmode", payload["post_settle_compile_trust_class"])
        self.assertIn("not authoritative", payload["post_settle_compile_note"])
        self.assertEqual("exit_play_mode_then_rerun_refresh", payload["post_settle_compile_recommended_next_action"])

    def test_a_playmode_test_run_is_not_mislabelled_as_deferred(self) -> None:
        payload = server_bridge_payloads.normalize_tests_payload_from_lifecycle(
            {"status": "completed"},
            {
                "operation": "unity.tests.run_playmode",
                "idle_wait_after": {
                    "is_compiling": False,
                    "is_updating": False,
                    "is_playing": True,
                    "playmode_state": "playing",
                    "compiler_error_count": 0,
                    "script_compilation_failed": False,
                    "recent_compiler_diagnostics": [],
                },
            },
        )

        self.assertEqual("confirmed", payload["post_settle_compile_trust_class"])

    def test_the_trust_class_survives_the_compact_envelope(self) -> None:
        payload = self._refresh("playing", is_playing=True)

        compact = server_bridge_payloads.compact_operation_payload(payload, "unity.project.refresh")

        self.assertEqual("deferred_during_playmode", compact["post_settle_compile_trust_class"])
        self.assertIn("post_settle_compile_recommended_next_action", compact)


class CompactEnvelopeTests(unittest.TestCase):
    """The hot interactive tools must be able to answer without spending the whole result budget."""

    def test_playmode_and_screenshot_are_compactable(self) -> None:
        for operation in ("unity.playmode.state", "unity.playmode.set", "unity.game_view.screenshot"):
            with self.subTest(operation=operation):
                self.assertIn(operation, server_bridge_payloads.COMPACT_OPERATION_PAYLOADS)

    def test_compact_screenshot_keeps_the_decision_fields_and_drops_the_bulk(self) -> None:
        payload = {
            "capture_source": "game_view",
            "file_path": "/tmp/shot.png",
            "width": 1170,
            "height": 2532,
            "image_included": False,
            "image_requested": True,
            "image_omitted_reason": "payload_budget",
            "image_bytes": 184000,
            "image_budget_bytes": 48000,
            "recommended_next_action": "read_file_path_with_an_image_reader",
            "some_bulky_diagnostic_block": {"a": 1},
        }

        compact = server_bridge_payloads.compact_operation_payload(payload, "unity.game_view.screenshot")

        self.assertEqual("/tmp/shot.png", compact["file_path"])
        self.assertEqual("payload_budget", compact["image_omitted_reason"])
        self.assertNotIn("some_bulky_diagnostic_block", compact)
        self.assertNotIn("image_base64", compact)

    def test_a_within_budget_inline_image_is_preserved(self) -> None:
        compact = server_bridge_payloads.compact_operation_payload(
            {"file_path": "/tmp/shot.png", "image_included": True, "image_base64": "aGk="},
            "unity.game_view.screenshot",
        )

        self.assertEqual("aGk=", compact["image_base64"])

    def test_compact_playmode_keeps_the_state_fields(self) -> None:
        compact = server_bridge_payloads.compact_operation_payload(
            {
                "playmode_state": "playing",
                "is_playing": True,
                "is_paused": False,
                "settle_phase": "settled",
                "noise": list(range(100)),
            },
            "unity.playmode.state",
        )

        self.assertEqual("playing", compact["playmode_state"])
        self.assertTrue(compact["is_playing"])
        self.assertNotIn("noise", compact)

    def test_the_compactable_tools_expose_the_opt_out(self) -> None:
        for tool_name in ("unity_playmode_state", "unity_playmode_set", "unity_game_view_screenshot"):
            with self.subTest(tool=tool_name):
                properties = server_specs.TOOLS[tool_name]["inputSchema"]["properties"]
                self.assertIn("includeFullPayload", properties)
                self.assertFalse(properties["includeFullPayload"]["default"])


class BlockedVersusFailedTests(unittest.TestCase):
    """A live-editor refusal is environmental; counting it as a compile failure misreads the whole rollout."""

    def test_a_live_editor_conflict_is_classified_as_blocked(self) -> None:
        payload = {
            "error": {
                "code": "editor_running_batch_conflict",
                "message": "An editor is open on this project.",
                "details": {"live_project_editor_pids": [4242]},
            }
        }

        self.assertEqual("editor_running_batch_conflict", run_multi_project.batch_error_code(payload))
        self.assertEqual([4242], run_multi_project.live_project_editor_pids_from_run(payload, {}))

    def test_pids_are_found_inside_the_batch_failure_summary(self) -> None:
        payload = {
            "error": {
                "details": {
                    "batch_failure_summary": {
                        "transport_outcome": "batch_prepare_blocked",
                        "live_project_editor_pids": [11, 22],
                    }
                }
            }
        }

        self.assertEqual([11, 22], run_multi_project.live_project_editor_pids_from_run(payload, {}))

    def test_a_genuine_failure_reports_no_live_editor(self) -> None:
        payload = {"error": {"code": "compile_player_scripts_failed", "details": {}}}

        self.assertEqual([], run_multi_project.live_project_editor_pids_from_run(payload, {}))
        self.assertNotEqual(
            run_multi_project.BLOCKED_BY_LIVE_EDITOR_VERDICT,
            run_multi_project.batch_error_code(payload),
        )


class UiTargetScopeSourceContractTests(unittest.TestCase):
    """UI reads must be able to leave the active scene, and must say so when a target is merely out of scope."""

    def test_all_loaded_scenes_is_a_declared_target_kind(self) -> None:
        models = read_source("Core/XUUnityLightMcpUiReadModels.cs")

        self.assertIn('TargetAllLoadedScenes = "all_loaded_scenes"', models)

    def test_every_ui_tool_offers_the_wider_scope(self) -> None:
        ui_tools = [
            name
            for name, tool in server_specs.TOOLS.items()
            if str(tool.get("bridgeOperation") or "").startswith("unity.ui.")
        ]
        self.assertTrue(ui_tools)

        for name in ui_tools:
            with self.subTest(tool=name):
                properties = server_specs.TOOLS[name]["inputSchema"]["properties"]
                self.assertIn("all_loaded_scenes", properties["targetKind"]["enum"])
                self.assertIn("sceneName", properties)
                self.assertIn("includeDontDestroyOnLoad", properties)

    def test_the_target_block_reports_whether_dont_destroy_on_load_was_searched(self) -> None:
        models = read_source("Core/XUUnityLightMcpUiReadModels.cs")

        for field in (
            "public bool dont_destroy_on_load_included;",
            "public List<string> searched_scenes",
            "public List<string> loaded_scenes",
        ):
            self.assertIn(field, models)

    def test_dont_destroy_on_load_status_never_contradicts_the_included_flag(self) -> None:
        """The DontDestroyOnLoad scene is discovered for `loaded_scenes` under every scope, but only *searched*
        under some. Reporting `included` while `dont_destroy_on_load_included` is false read as a contradiction
        on a live consumer-project run: `active_scene` said included=False / status=included."""

        models = read_source("Core/XUUnityLightMcpUiReadModels.cs")
        builder = read_source("Helpers/XUUnityLightMcpUiTreeBuilder.cs")

        self.assertIn('DontDestroyOnLoadOutOfScope = "out_of_scope_for_target_kind"', models)
        self.assertIn("ResolveDontDestroyOnLoadStatus(scope)", builder)
        self.assertIn("scope.DontDestroyOnLoadSearched", builder)

    def test_out_of_scope_is_distinct_from_not_found(self) -> None:
        builder = read_source("Helpers/XUUnityLightMcpUiTreeBuilder.cs")

        self.assertIn('"ui_target_out_of_scope"', builder)
        self.assertIn('"ui_target_not_found"', builder)
        self.assertIn("Retry with targetKind=all_loaded_scenes", builder)

    def test_a_zero_match_selector_probes_the_wider_scope_before_answering(self) -> None:
        """A live consumer-project run exposed the real gap: `unity.ui.query` with a selector returned
        `match_count: 0` and no diagnostic at all for a node sitting in an additively loaded scene —
        indistinguishable from "no such object", which is the exact failure the retro reported. Resolving
        the *root* out of scope was covered; resolving the *selector* out of scope was not."""

        query = read_source("Operations/XUUnityLightMcpUiQueryOperations.cs")

        self.assertIn("FindOwningScenesOutsideScope", query)
        self.assertIn("BuildZeroMatchDiagnostic", query)
        self.assertIn("IsWidestScope", query)
        self.assertIn('"ui_target_out_of_scope"', query)
        self.assertIn('"ui_node_not_found"', query)

    def test_the_wider_scope_probe_only_runs_on_a_zero_match(self) -> None:
        """The probe is a second full tree walk; it must stay on the diagnostic path, never the hot path."""

        query = read_source("Operations/XUUnityLightMcpUiQueryOperations.cs")

        self.assertIn("if (payload.match_count == 0 && payload.success)", query)
        self.assertIn("if (payload.target == null || IsWidestScope(payload.target))", query)

    def test_out_of_scope_is_a_first_class_payload_field(self) -> None:
        models = read_source("Core/XUUnityLightMcpUiReadModels.cs")

        self.assertIn("public bool out_of_scope;", models)

    def test_the_click_target_is_not_re_resolved_by_name_lookup(self) -> None:
        """GameObject.Find cannot address every additive/DontDestroyOnLoad object the tree can now reach."""

        click = read_source("Ugui/XUUnityLightMcpUiClickOperation.cs")

        self.assertNotIn("GameObject.Find(", click)
        self.assertIn("before.ResolveTransform(node)", click)

    def test_the_tree_builder_keeps_transforms_in_lockstep_with_nodes(self) -> None:
        builder = read_source("Helpers/XUUnityLightMcpUiTreeBuilder.cs")

        self.assertIn("result.Nodes.Add(node);", builder)
        self.assertIn("result.NodeTransforms.Add(transform);", builder)


class PlayModeRefusalSourceContractTests(unittest.TestCase):
    """"Editor is busy" hid the one thing the operator needed to know: it is in Play Mode."""

    def test_the_guard_names_play_mode_and_both_valid_next_actions(self) -> None:
        guard = read_source("Helpers/XUUnityLightMcpEditorBusyGuard.cs")

        self.assertIn('EditorInPlayModeCode = "editor_in_play_mode"', guard)
        self.assertIn("unity.playmode.set action=stop", guard)
        self.assertIn("closed-project batch lane", guard)

    def test_no_operation_still_raises_the_bare_busy_string(self) -> None:
        offenders = []
        for source in sorted(PACKAGE_EDITOR_ROOT.rglob("*.cs")):
            if source.name == "XUUnityLightMcpEditorBusyGuard.cs":
                continue
            if re.search(r'"Unity editor is busy', source.read_text(encoding="utf-8")):
                offenders.append(str(source.relative_to(REPO_ROOT)))

        self.assertEqual([], offenders, "route editor-busy refusals through XUUnityLightMcpEditorBusyGuard")

    def test_the_refusing_operations_map_the_typed_code_onto_the_response(self) -> None:
        for relative in (
            "Operations/XUUnityLightMcpCompilePlayerScriptsOperation.cs",
            "Operations/XUUnityLightMcpCompileMatrixOperation.cs",
        ):
            with self.subTest(source=relative):
                self.assertIn("XUUnityLightMcpEditorBusyGuard.ResolveErrorCode", read_source(relative))


class ScreenshotBudgetSourceContractTests(unittest.TestCase):
    """One includeImage call returned 184,659 characters and wasted the whole call."""

    def test_the_budget_is_checked_before_base64_is_built(self) -> None:
        utility = read_source("Helpers/XUUnityLightMcpGameViewUtility.cs")

        encode_at = utility.index("EncodeToPNG();\n                    imageBytes")
        base64_at = utility.index("Convert.ToBase64String(inlineBytes)")
        self.assertLess(encode_at, base64_at, "size must be known before the base64 string is allocated")
        self.assertIn("imageBytes <= budget", utility)

    def test_the_payload_explains_an_omitted_image(self) -> None:
        models = read_source("Core/XUUnityLightMcpGameViewProjectResolveModels.cs")

        self.assertIn('ImageOmittedPayloadBudget = "payload_budget"', models)
        self.assertIn("public string image_omitted_reason", models)
        self.assertIn("public int image_budget_bytes;", models)

    def test_the_tool_documents_the_file_path_first_path(self) -> None:
        tool = server_specs.TOOLS["unity_game_view_screenshot"]

        self.assertIn("file_path", tool["description"])
        self.assertIn("imageBudgetBytes", tool["inputSchema"]["properties"])


if __name__ == "__main__":
    unittest.main()
