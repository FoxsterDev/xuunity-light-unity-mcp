from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from server_core import ToolInvocationError, read_json


UI_FIXTURE_SCHEMA_VERSION = "xuunity.ui-fixture.v1"

DATA_SOURCES = ("fixture", "live", "mixed")
EVIDENCE_SOURCES = ("scenario_result", "hook_payload", "caller_asserted", "none")
HOOK_STEP_KINDS = ("project_defined_hook", "project_defined_hook_poll_until")

DETERMINISM_PROVEN = "proven"
DETERMINISM_UNPROVEN = "unproven"
DETERMINISM_NOT_REPORTED = "not_reported"

GAP_MESSAGES = {
    "evidence_absent": "No ui_fixture evidence was reported for this capture.",
    "evidence_not_receipt_backed": (
        "ui_fixture evidence was asserted by the caller instead of read from a scenario result "
        "written by the editor, so nothing verifies that the state was actually established."
    ),
    "unsupported_or_missing_schema_version": (
        f"ui_fixture must declare schema_version '{UI_FIXTURE_SCHEMA_VERSION}'."
    ),
    "missing_fixture_id": "ui_fixture must name the fixture that established the UI state.",
    "invalid_data_source": f"ui_fixture data_source must be one of {', '.join(DATA_SOURCES)}.",
    "live_data_without_payload_hash": (
        "The screen was rendered from live data, so the capture is not reproducible unless the "
        "project records an immutable payload hash for the response it rendered."
    ),
    "clock_not_frozen": "The clock was not frozen, so timers and dates can differ between captures.",
    "locale_not_pinned": "The locale was not pinned, so displayed strings can differ between captures.",
    "ready_predicate_unsatisfied": "The fixture's ready predicate was not satisfied before the capture.",
    "ready_predicate_timed_out": "The fixture's ready predicate timed out before the capture.",
    "hook_step_failed": "The scenario step that reported the fixture did not pass.",
    "fixture_id_mismatch": "The reported fixture differs from the fixture the reference declares.",
    "viewport_mismatch": "The reported fixture viewport differs from the reference viewport.",
}


def ui_fixture_contract() -> dict[str, Any]:
    return {
        "schema_version": UI_FIXTURE_SCHEMA_VERSION,
        "emitted_by": "project_defined_hook_payload_field_ui_fixture",
        "consumed_by": ["unity_ui_reference_compare", "unity_ui_fixture_validate"],
        "ownership": "the base MCP owns the envelope and the safety rules; projects own their fixtures",
        "required_fields": ["schema_version", "fixture_id", "data_source", "ready"],
        "fields": {
            "schema_version": f"must be '{UI_FIXTURE_SCHEMA_VERSION}'",
            "fixture_id": "canonical fixture that established this UI state",
            "state_id": "semantic state within the fixture, for example available_with_timer",
            "data_source": f"one of {', '.join(DATA_SOURCES)}",
            "payload_hash": "immutable hash of the rendered payload; required when data_source is live or mixed",
            "clock": "{frozen: bool, value_utc: string}",
            "locale": "{id: string, pinned: bool}",
            "viewport": "{width: int, height: int} actually resolved at capture time",
            "safe_area": "resolved safe-area descriptor, for example full_screen",
            "ready": "{predicate: string, satisfied: bool, waited_ms: int, timeout_ms: int, timed_out: bool}",
        },
        "rules": [
            "Live or mixed data without a recorded payload hash downgrades visual_determinism to unproven.",
            "An unfrozen clock or unpinned locale downgrades visual_determinism to unproven.",
            "Caller-asserted evidence is never receipt-backed and never proves determinism.",
            "An unsatisfied or timed-out ready predicate means the fixture was not established.",
        ],
        "example": {
            "ui_fixture": {
                "schema_version": UI_FIXTURE_SCHEMA_VERSION,
                "fixture_id": "example_popup_available",
                "state_id": "available_with_timer",
                "data_source": "fixture",
                "payload_hash": "",
                "clock": {"frozen": True, "value_utc": "2026-01-01T00:00:00Z"},
                "locale": {"id": "en", "pinned": True},
                "viewport": {"width": 1080, "height": 2400},
                "safe_area": "full_screen",
                "ready": {
                    "predicate": "popup_visible_and_idle",
                    "satisfied": True,
                    "waited_ms": 240,
                    "timeout_ms": 5000,
                },
            }
        },
    }


def extract_ui_fixture_block(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("ui_fixture")
    if raw is None:
        raw = payload.get("uiFixture")
    if raw is None:
        return None
    return raw if isinstance(raw, dict) else {"__invalid__": True}


def normalize_ui_fixture_evidence(
    raw: Any,
    *,
    evidence_source: str = "caller_asserted",
    receipt: dict[str, Any] | None = None,
    declared_fixture: str = "",
    declared_viewport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = evidence_source if evidence_source in EVIDENCE_SOURCES else "caller_asserted"
    record: dict[str, Any] = {
        "contract_version": UI_FIXTURE_SCHEMA_VERSION,
        "evidence_source": source,
        "receipt": dict(receipt or {}),
        "declared_fixture": str(declared_fixture or ""),
        "reported": raw is not None,
    }

    if raw is None:
        record.update(
            {
                "proof_status": "absent",
                "schema_version": "",
                "fixture_id": "",
                "state_id": "",
                "data_source": "",
                "payload_hash": "",
                "clock": {"frozen": False, "value_utc": ""},
                "locale": {"id": "", "pinned": False},
                "viewport": {},
                "safe_area": "",
                "ready": {},
                "established": False,
                "visual_determinism": DETERMINISM_NOT_REPORTED,
                "determinism_gaps": ["evidence_absent"],
                "validation_errors": [],
                "messages": [GAP_MESSAGES["evidence_absent"]],
            }
        )
        return record

    if not isinstance(raw, dict) or raw.get("__invalid__"):
        record.update(
            {
                "proof_status": "invalid",
                "schema_version": "",
                "fixture_id": "",
                "state_id": "",
                "data_source": "",
                "payload_hash": "",
                "clock": {"frozen": False, "value_utc": ""},
                "locale": {"id": "", "pinned": False},
                "viewport": {},
                "safe_area": "",
                "ready": {},
                "established": False,
                "visual_determinism": DETERMINISM_UNPROVEN,
                "determinism_gaps": ["unsupported_or_missing_schema_version"],
                "validation_errors": ["ui_fixture_must_be_an_object"],
                "messages": ["The reported ui_fixture block is not a JSON object."],
            }
        )
        return record

    gaps: list[str] = []
    validation_errors: list[str] = []

    schema_version = _text(raw, "schema_version", "schemaVersion")
    if schema_version != UI_FIXTURE_SCHEMA_VERSION:
        validation_errors.append("unsupported_or_missing_schema_version")
        gaps.append("unsupported_or_missing_schema_version")

    fixture_id = _text(raw, "fixture_id", "fixtureId")
    if not fixture_id:
        validation_errors.append("missing_fixture_id")
        gaps.append("missing_fixture_id")

    data_source = _text(raw, "data_source", "dataSource").lower()
    if data_source not in DATA_SOURCES:
        validation_errors.append("invalid_data_source")
        gaps.append("invalid_data_source")

    payload_hash = _text(raw, "payload_hash", "payloadHash")
    if data_source in ("live", "mixed") and not payload_hash:
        gaps.append("live_data_without_payload_hash")

    clock = _normalize_clock(raw.get("clock"))
    if not clock["frozen"]:
        gaps.append("clock_not_frozen")

    locale = _normalize_locale(raw.get("locale"))
    if not locale["pinned"]:
        gaps.append("locale_not_pinned")

    ready = _normalize_ready(raw.get("ready"))
    if ready["timed_out"]:
        gaps.append("ready_predicate_timed_out")
    if not ready["satisfied"]:
        gaps.append("ready_predicate_unsatisfied")

    viewport = _normalize_viewport(raw.get("viewport"))
    if declared_viewport and viewport and not _viewport_matches(viewport, declared_viewport):
        gaps.append("viewport_mismatch")

    if declared_fixture and fixture_id and declared_fixture != fixture_id:
        gaps.append("fixture_id_mismatch")

    if source == "caller_asserted":
        gaps.append("evidence_not_receipt_backed")

    step_status = str((receipt or {}).get("step_status") or "")
    if step_status and step_status != "passed":
        gaps.append("hook_step_failed")

    established = (
        not validation_errors
        and ready["satisfied"]
        and not ready["timed_out"]
        and step_status in ("", "passed")
    )
    determinism = DETERMINISM_PROVEN if established and not gaps else DETERMINISM_UNPROVEN

    record.update(
        {
            "proof_status": "invalid" if validation_errors else "valid",
            "schema_version": schema_version,
            "fixture_id": fixture_id,
            "state_id": _text(raw, "state_id", "stateId"),
            "data_source": data_source,
            "payload_hash": payload_hash,
            "clock": clock,
            "locale": locale,
            "viewport": viewport,
            "safe_area": _text(raw, "safe_area", "safeArea"),
            "ready": ready,
            "established": established,
            "visual_determinism": determinism,
            "determinism_gaps": _dedupe(gaps),
            "validation_errors": _dedupe(validation_errors),
        }
    )
    record["messages"] = [GAP_MESSAGES[code] for code in record["determinism_gaps"] if code in GAP_MESSAGES]
    return record


def read_scenario_ui_fixture(result_path: Path) -> tuple[Any, dict[str, Any]]:
    try:
        payload = read_json(result_path)
    except Exception as exc:
        raise ToolInvocationError(
            "ui_fixture_result_unreadable",
            f"Scenario result '{result_path}' could not be read as JSON: {exc}",
            {"result_path": str(result_path)},
        ) from exc
    if not isinstance(payload, dict):
        raise ToolInvocationError(
            "ui_fixture_result_unreadable",
            f"Scenario result '{result_path}' is not a JSON object.",
            {"result_path": str(result_path)},
        )

    receipt: dict[str, Any] = {
        "result_path": str(result_path),
        "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "run_id": str(payload.get("run_id") or ""),
        "scenario_name": str(payload.get("scenario_name") or ""),
        "scenario_status": str(payload.get("status") or ""),
    }

    for step in _hook_steps(payload):
        raw = extract_ui_fixture_block(scenario_step_payload(step))
        if raw is None:
            continue
        receipt.update(
            {
                "step_id": str(step.get("stepId") or step.get("step_id") or ""),
                "hook_name": str(step.get("hookName") or step.get("hook_name") or ""),
                "step_kind": str(step.get("kind") or ""),
                "step_status": str(step.get("status") or ""),
            }
        )
        return raw, receipt

    return None, receipt


def resolve_ui_fixture_evidence(
    *,
    workspace: Path,
    fixture_evidence: dict[str, Any] | None = None,
    fixture_result_path: str = "",
    declared_fixture: str = "",
    declared_viewport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested = str(fixture_result_path or "").strip()
    if requested:
        resolved = resolve_result_path(requested, workspace)
        raw, receipt = read_scenario_ui_fixture(resolved)
        return normalize_ui_fixture_evidence(
            raw,
            evidence_source="scenario_result",
            receipt=receipt,
            declared_fixture=declared_fixture,
            declared_viewport=declared_viewport,
        )

    if not fixture_evidence:
        return normalize_ui_fixture_evidence(
            None,
            evidence_source="none",
            declared_fixture=declared_fixture,
            declared_viewport=declared_viewport,
        )

    raw = extract_ui_fixture_block(fixture_evidence)
    return normalize_ui_fixture_evidence(
        fixture_evidence if raw is None else raw,
        evidence_source="caller_asserted",
        declared_fixture=declared_fixture,
        declared_viewport=declared_viewport,
    )


def resolve_result_path(value: str, workspace: Path) -> Path:
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        path = (workspace / path).resolve()
    if not path.is_file():
        raise ToolInvocationError(
            "ui_fixture_result_not_found",
            f"Scenario result '{path}' was not found.",
            {"result_path": str(path)},
        )
    return path


def validate_ui_fixture(
    *,
    project_root: Path,
    workspace: Path,
    fixture_evidence: dict[str, Any] | None = None,
    fixture_result_path: str = "",
    declared_fixture: str = "",
    declared_viewport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = resolve_ui_fixture_evidence(
        workspace=workspace,
        fixture_evidence=fixture_evidence,
        fixture_result_path=fixture_result_path,
        declared_fixture=declared_fixture,
        declared_viewport=declared_viewport,
    )
    return {
        "action": "unity_ui_fixture_validate",
        "project_root": str(project_root),
        "schema_version": UI_FIXTURE_SCHEMA_VERSION,
        "fixture": record,
        "visual_determinism": record["visual_determinism"],
        "established": record["established"],
        "succeeded": record["visual_determinism"] == DETERMINISM_PROVEN,
        "next_actions": fixture_next_actions(record),
        "contract": ui_fixture_contract(),
    }


def fixture_next_actions(record: dict[str, Any]) -> list[str]:
    gaps = list(record.get("determinism_gaps") or [])
    actions: list[str] = []
    if "evidence_absent" in gaps:
        actions.append(
            "Have the project hook emit a ui_fixture block and pass the scenario result as fixtureResultPath."
        )
    if "evidence_not_receipt_backed" in gaps:
        actions.append(
            "Pass fixtureResultPath instead of fixtureEvidence so the fixture report is read from the "
            "scenario result the editor wrote."
        )
    if "live_data_without_payload_hash" in gaps:
        actions.append(
            "Record an immutable payload hash for the live response, or switch the state to a fixture."
        )
    if "clock_not_frozen" in gaps:
        actions.append("Freeze the clock in the fixture before capturing.")
    if "locale_not_pinned" in gaps:
        actions.append("Pin the locale in the fixture before capturing.")
    if "ready_predicate_unsatisfied" in gaps or "ready_predicate_timed_out" in gaps:
        actions.append("Make the ready predicate pass before the capture step runs.")
    if "fixture_id_mismatch" in gaps:
        actions.append(
            "The capture was taken under a different fixture than the reference declares; align them "
            "before treating the comparison as evidence."
        )
    if "viewport_mismatch" in gaps:
        actions.append("Resolve the fixture at the reference viewport, or re-register the reference.")
    if "hook_step_failed" in gaps:
        actions.append("Fix the failing scenario step; a failed hook cannot establish a fixture.")
    return actions


def _hook_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for group in ("steps", "cleanupSteps", "cleanup_steps"):
        for step in list(payload.get(group) or []):
            if isinstance(step, dict) and str(step.get("kind") or "") in HOOK_STEP_KINDS:
                steps.append(step)
    return steps


def scenario_step_payload(step: dict[str, Any]) -> dict[str, Any]:
    """Shared scenario-result plumbing; the interaction contract reads steps the same way."""

    for key in ("payload_json", "payloadJson", "terminal_payload_json"):
        text = str(step.get(key) or "")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    payload = step.get("payload")
    return payload if isinstance(payload, dict) else {}


def _normalize_clock(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"frozen": False, "value_utc": ""}
    return {
        "frozen": bool(raw.get("frozen", False)),
        "value_utc": _text(raw, "value_utc", "valueUtc"),
    }


def _normalize_locale(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"id": raw.strip(), "pinned": bool(raw.strip())}
    if not isinstance(raw, dict):
        return {"id": "", "pinned": False}
    locale_id = _text(raw, "id", "locale")
    return {"id": locale_id, "pinned": bool(raw.get("pinned", bool(locale_id)))}


def _normalize_ready(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"predicate": "", "satisfied": False, "waited_ms": 0, "timeout_ms": 0, "timed_out": False}
    waited_ms = _non_negative_int(raw.get("waited_ms", raw.get("waitedMs")))
    timeout_ms = _non_negative_int(raw.get("timeout_ms", raw.get("timeoutMs")))
    satisfied = bool(raw.get("satisfied", False))
    timed_out = bool(raw.get("timed_out", raw.get("timedOut", False)))
    if not timed_out and not satisfied and timeout_ms > 0 and waited_ms >= timeout_ms:
        timed_out = True
    return {
        "predicate": _text(raw, "predicate"),
        "satisfied": satisfied,
        "waited_ms": waited_ms,
        "timeout_ms": timeout_ms,
        "timed_out": timed_out,
    }


def _normalize_viewport(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    width = _non_negative_int(raw.get("width"))
    height = _non_negative_int(raw.get("height"))
    if width <= 0 or height <= 0:
        return {}
    return {"width": width, "height": height}


def _viewport_matches(reported: dict[str, Any], declared: dict[str, Any]) -> bool:
    declared_width = _non_negative_int(declared.get("width"))
    declared_height = _non_negative_int(declared.get("height"))
    if declared_width <= 0 or declared_height <= 0:
        return True
    return (reported["width"], reported["height"]) == (declared_width, declared_height)


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _text(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
