from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from server_core import ToolInvocationError, read_json
from server_ui_reference_manifest import TOLERANCE_PROFILES

UI_VISION_SCHEMA_VERSION = "xuunity.ui-vision-review.v1"
RUBRIC_VERSION = "recognisably-the-same-screen.v1"

CRITERIA = ("layout", "sizing", "color", "typography", "imagery", "content")
CRITERION_INTENT = {
    "layout": "Are the same elements in the same places, in the same order and alignment?",
    "sizing": "Are elements the same relative size and proportion versus the screen and each other?",
    "color": "Is the palette, contrast, and theme the same?",
    "typography": "Is the type family, weight, case, and relative size the same?",
    "imagery": "Are the icons, illustrations, and sprites the same artwork?",
    "content": "Does the screen show the same strings, numbers, and states?",
}

SCALE = {
    0: "absent",
    1: "wrong",
    2: "noticeably_off",
    3: "close",
    4: "indistinguishable",
}
SCALE_INTENT = {
    0: "The element the reference shows is not present at all.",
    1: "Present, but a visibly different design decision.",
    2: "Same intent, visibly different; a reviewer would raise it.",
    3: "A reviewer would accept it; differences need a side-by-side to spot.",
    4: "No perceivable difference.",
}
SCALE_MAX = max(SCALE)

JUDGE_ROLES = ("authoring_agent", "independent_agent", "human")
VISION_STATUSES = ("passed", "failed", "blocked", "not_evaluated")

# Pixel equality is never the bar. These are "is this recognisably the same screen"
# bars, and they move with the same profile dial as the numeric comparison.
VISION_POLICY_PROFILES: dict[str, dict[str, Any]] = {
    "strict": {"min_criterion": 3, "min_overall": 3},
    "balanced": {"min_criterion": 2, "min_overall": 3},
    "lenient": {"min_criterion": 1, "min_overall": 2},
}
DEFAULT_VISION_POLICY: dict[str, Any] = {
    "min_criterion": 2,
    "min_overall": 3,
    "required_criteria": list(CRITERIA),
    "judges_required": 1,
    "allow_self_review": True,
}


def vision_rubric() -> dict[str, Any]:
    return {
        "schema_version": UI_VISION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "question": (
            "Is the candidate recognisably the same screen as the reference, in style, placement, "
            "and size? Pixel equality is explicitly not the bar."
        ),
        "scale": [
            {"score": score, "name": SCALE[score], "means": SCALE_INTENT[score]} for score in sorted(SCALE)
        ],
        "criteria": [{"id": key, "asks": CRITERION_INTENT[key]} for key in CRITERIA],
        "rules": [
            "Score only what the two images show; do not infer from code you wrote.",
            "Every criterion needs a one-line observation naming what you actually saw.",
            "The overall score is clamped to the worst required criterion plus one, so a strong "
            "overall claim cannot outrun a weak part.",
            "A review is an attested judgement, never a receipt; it records who judged and in what role.",
            "A review is bound to one exact image pair by packet_hash and expires when either image changes.",
        ],
        "submission_example": {
            "schema_version": UI_VISION_SCHEMA_VERSION,
            "packet_hash": "<from the packet>",
            "judge": {"id": "claude-opus", "role": "independent_agent", "model": "claude-opus-5"},
            "overall": 3,
            "criteria": {
                "layout": {"score": 3, "observation": "Same stack order; CTA sits ~2% lower."},
                "sizing": {"score": 3, "observation": "Title one step smaller than the reference."},
                "color": {"score": 4, "observation": "Palette matches."},
                "typography": {"score": 3, "observation": "Same family and weight."},
                "imagery": {"score": 4, "observation": "Same icon set."},
                "content": {"score": 4, "observation": "Same strings and counters."},
            },
            "defects": [
                {"severity": "minor", "criterion": "layout", "region_id": "cta", "note": "CTA baseline low."}
            ],
        },
    }


def resolve_vision_policy(manifest: dict[str, Any]) -> dict[str, Any]:
    profile = str(manifest.get("tolerance_profile") or "balanced").strip().lower()
    resolved: dict[str, Any] = {
        **DEFAULT_VISION_POLICY,
        **VISION_POLICY_PROFILES.get(profile, {}),
    }
    overrides = manifest.get("vision_policy")
    if isinstance(overrides, dict):
        for key in ("min_criterion", "min_overall", "judges_required"):
            value = overrides.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                resolved[key] = int(value)
        if isinstance(overrides.get("allow_self_review"), bool):
            resolved["allow_self_review"] = bool(overrides["allow_self_review"])
        required = overrides.get("required_criteria")
        if isinstance(required, list):
            resolved["required_criteria"] = [str(item) for item in required if str(item) in CRITERIA]

    # A floor of 0 would be a bar nothing can fail: score 0 means "absent — the element the
    # reference shows is not present at all".
    resolved["min_criterion"] = max(1, min(SCALE_MAX, int(resolved["min_criterion"])))
    resolved["min_overall"] = max(1, min(SCALE_MAX, int(resolved["min_overall"])))
    resolved["judges_required"] = max(1, int(resolved["judges_required"]))
    resolved["profile"] = profile
    return resolved


def packet_hash(
    *,
    reference_id: str,
    expected_sha256: str,
    actual_sha256: str,
    policy: dict[str, Any],
) -> str:
    material = "|".join(
        [
            UI_VISION_SCHEMA_VERSION,
            RUBRIC_VERSION,
            str(reference_id),
            str(expected_sha256),
            str(actual_sha256),
            f"{policy.get('min_criterion')}:{policy.get('min_overall')}",
            ",".join(sorted(str(item) for item in policy.get("required_criteria") or [])),
            # The independence half of the bar belongs in the hash too, or it can be lowered
            # after the judgement while every stored review still reads as valid.
            f"{int(policy.get('judges_required') or 1)}:{bool(policy.get('allow_self_review'))}",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def normalize_vision_review(
    raw: Any,
    *,
    policy: dict[str, Any],
    expected_packet_hash: str = "",
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "contract_version": UI_VISION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "evidence_class": "attested_judgement",
        "reported": raw is not None,
        "errors": [],
        "warnings": [],
    }

    if not isinstance(raw, dict):
        record.update(
            {
                "valid": False,
                "verdict": "not_evaluated",
                "errors": ["vision_review_absent" if raw is None else "vision_review_not_an_object"],
                "judge": {},
                "criteria": {},
                "overall_reported": None,
                "overall_effective": None,
                "defects": [],
                "packet_hash": "",
            }
        )
        return record

    errors: list[str] = []
    warnings: list[str] = []

    if _text(raw, "schema_version", "schemaVersion") != UI_VISION_SCHEMA_VERSION:
        errors.append("unsupported_or_missing_schema_version")

    supplied_hash = _text(raw, "packet_hash", "packetHash")
    if not supplied_hash:
        errors.append("missing_packet_hash")
    elif expected_packet_hash and supplied_hash != expected_packet_hash:
        errors.append("vision_packet_stale")

    judge = _normalize_judge(raw.get("judge"))
    if not judge["id"]:
        errors.append("missing_judge_id")
    if judge["role"] not in JUDGE_ROLES:
        errors.append("invalid_judge_role")
    elif judge["role"] == "authoring_agent":
        if policy.get("allow_self_review", True):
            warnings.append("vision_review_is_self_reviewed")
        else:
            errors.append("vision_self_review_not_permitted")

    criteria, criteria_errors = _normalize_criteria(raw.get("criteria"), policy)
    errors.extend(criteria_errors)

    overall_reported = _score(raw.get("overall"))
    if overall_reported is None:
        errors.append("missing_overall_score")

    required = [key for key in (policy.get("required_criteria") or CRITERIA) if key in CRITERIA]
    scored = [criteria[key]["score"] for key in required if key in criteria]
    worst_required = min(scored) if scored else None
    overall_effective = overall_reported
    if overall_reported is not None and worst_required is not None:
        # Two independent bounds. The worst-criterion bound stops one catastrophic criterion from
        # being averaged away; the corroboration bound stops a claimed overall from exceeding what
        # the criteria as a whole support, which is what let every criterion sit on the bare floor
        # and still pass.
        worst_bound = min(SCALE_MAX, worst_required + 1)
        corroborated = int(sum(scored) / len(scored) + 0.5)
        overall_effective = min(overall_reported, worst_bound, corroborated)
        if overall_effective < overall_reported:
            if corroborated <= worst_bound:
                warnings.append("overall_clamped_to_criteria_corroboration")
            else:
                warnings.append("overall_clamped_to_worst_criterion")

    record.update(
        {
            "valid": not errors,
            "packet_hash": supplied_hash,
            "judge": judge,
            "criteria": criteria,
            "required_criteria": required,
            "worst_required_criterion": worst_required,
            "overall_reported": overall_reported,
            "overall_effective": overall_effective,
            "defects": _normalize_defects(raw.get("defects")),
            "notes": _text(raw, "notes"),
            "errors": _dedupe(errors),
            "warnings": _dedupe(warnings),
        }
    )
    record["verdict"] = _review_verdict(record, policy)
    record["failed_criteria"] = [
        key
        for key in required
        if key in criteria and criteria[key]["score"] < int(policy["min_criterion"])
    ]
    return record


def canonical_submission(record: dict[str, Any]) -> dict[str, Any]:
    """The raw block a stored review must round-trip back through normalize_vision_review."""

    return {
        "schema_version": UI_VISION_SCHEMA_VERSION,
        "packet_hash": str(record.get("packet_hash") or ""),
        "judge": dict(record.get("judge") or {}),
        "overall": record.get("overall_reported"),
        "criteria": {
            key: {"score": entry["score"], "observation": entry.get("observation", "")}
            for key, entry in (record.get("criteria") or {}).items()
        },
        "defects": list(record.get("defects") or []),
        "notes": str(record.get("notes") or ""),
    }


def _review_verdict(record: dict[str, Any], policy: dict[str, Any]) -> str:
    if not record["valid"]:
        return "blocked"
    overall = record.get("overall_effective")
    if overall is None:
        return "blocked"
    required = record.get("required_criteria") or []
    criteria = record.get("criteria") or {}
    minimum = int(policy["min_criterion"])
    for key in required:
        entry = criteria.get(key)
        if entry is None or int(entry["score"]) < minimum:
            return "failed"
    return "passed" if int(overall) >= int(policy["min_overall"]) else "failed"


def evaluate_vision_lane(
    *,
    reviews: list[dict[str, Any]],
    policy: dict[str, Any],
    requirement: str,
) -> dict[str, Any]:
    usable = [review for review in reviews if review.get("reported")]
    if not usable:
        return {
            "requirement": requirement,
            "status": "not_evaluated",
            "evidence": "no_vision_review_supplied",
            "rubric_version": RUBRIC_VERSION,
            "policy": policy,
            "reviews": [],
            "judges": 0,
        }

    blocked = [review for review in usable if review["verdict"] == "blocked"]
    passed = [review for review in usable if review["verdict"] == "passed"]
    failed = [review for review in usable if review["verdict"] == "failed"]
    required_judges = int(policy.get("judges_required") or 1)

    if blocked or len(usable) < required_judges:
        status = "blocked"
    elif failed and len(passed) <= len(failed):
        status = "failed"
    else:
        status = "passed"

    scores = [int(review["overall_effective"]) for review in usable if review.get("overall_effective") is not None]
    lane = {
        "requirement": requirement,
        "status": status,
        "evidence": "attested_multimodal_review_of_the_reference_candidate_pair",
        "rubric_version": RUBRIC_VERSION,
        "policy": policy,
        "judges": len(usable),
        "judges_required": required_judges,
        "unanimous": not (passed and failed),
        "median_overall": _median(scores),
        "worst_criteria": _worst_criteria(usable),
        "self_reviewed_only": bool(usable)
        and all(review.get("judge", {}).get("role") == "authoring_agent" for review in usable),
        "reviews": [_review_summary(review) for review in usable],
    }
    if len(usable) < required_judges:
        lane["blocked_reason"] = "not_enough_judges"
    if blocked:
        lane["blocked_reason"] = "invalid_review_submitted"
    return lane


def analyze_lane_disagreement(
    *,
    visual_verdict: str,
    vision_lane: dict[str, Any],
    global_metrics: dict[str, Any],
    tolerances: dict[str, float],
) -> dict[str, Any]:
    """The two lanes measure different things; when they disagree, say which one to trust."""

    vision_status = str(vision_lane.get("status") or "not_evaluated")
    if vision_status not in ("passed", "failed") or visual_verdict not in ("passed", "failed"):
        return {"disagree": False, "code": "", "message": "", "suggestion": {}}

    if visual_verdict == vision_status:
        return {"disagree": False, "code": "", "message": "", "suggestion": {}}

    if visual_verdict == "passed":
        worst = vision_lane.get("worst_criteria") or []
        named = ", ".join(str(item.get("criterion")) for item in worst[:3]) or "style"
        return {
            "disagree": True,
            "code": "vision_contradicts_similarity",
            "trust": "vision",
            "message": (
                f"The comparison grid passed but the review failed on {named}. Cell similarity cannot "
                "see a wrong icon, a wrong font at the same weight, or a mirrored arrangement that "
                "averages to the same colours; treat the review as the stronger signal here."
            ),
            "suggestion": {},
        }

    score = global_metrics.get("similarity_score")
    suggestion = _suggest_looser_profile(score, tolerances)
    return {
        "disagree": True,
        "code": "similarity_may_be_over_strict",
        "trust": "inspect_both",
        "message": (
            "The review says this is recognisably the same screen but the numeric bar rejected it. "
            "Either the tolerance profile is tighter than the intended acceptance bar, or the "
            "difference is one a reviewer waved through. Decide deliberately; do not silently widen."
        ),
        "suggestion": suggestion,
    }


def _suggest_looser_profile(score: Any, tolerances: dict[str, float]) -> dict[str, Any]:
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return {}
    current_global = float(tolerances.get("global_min_similarity") or 0.0)
    for name in ("strict", "balanced", "lenient"):
        profile = TOLERANCE_PROFILES[name]
        if float(profile["global_min_similarity"]) <= float(score):
            if float(profile["global_min_similarity"]) >= current_global:
                return {}
            return {
                "tolerance_profile": name,
                "would_pass_global": True,
                "current_global_min_similarity": current_global,
                "candidate_global_min_similarity": float(profile["global_min_similarity"]),
                "observed_global_similarity": round(float(score), 6),
            }
    return {
        "tolerance_profile": "",
        "would_pass_global": False,
        "observed_global_similarity": round(float(score), 6),
        "note": "No shipped profile is loose enough; the difference is larger than styling latitude.",
    }


def read_vision_reviews(paths: list[str], workspace: Path, *, policy: dict[str, Any], expected_hash: str) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for raw_path in paths:
        text = str(raw_path or "").strip()
        if not text:
            continue
        resolved = _resolve_path(text, workspace)
        try:
            payload = read_json(resolved)
        except Exception as exc:
            raise ToolInvocationError(
                "ui_vision_review_unreadable",
                f"Vision review '{resolved}' could not be read as JSON: {exc}",
                {"review_path": str(resolved)},
            ) from exc
        block = payload.get("vision_review") if isinstance(payload, dict) else None
        record = normalize_vision_review(
            block if isinstance(block, dict) else payload,
            policy=policy,
            expected_packet_hash=expected_hash,
        )
        record["source_path"] = str(resolved)
        reviews.append(record)
    return reviews


def vision_next_actions(lane: dict[str, Any]) -> list[str]:
    status = str(lane.get("status") or "")
    actions: list[str] = []
    if status == "not_evaluated":
        actions.append(
            "Build a review sheet with unity_ui_vision_packet, look at it, and submit a rubric "
            "judgement with unity_ui_vision_submit so style is judged and not only cell similarity."
        )
        return actions
    if lane.get("blocked_reason") == "not_enough_judges":
        actions.append(
            f"This reference requires {lane.get('judges_required')} independent judgements; "
            f"only {lane.get('judges')} were submitted."
        )
    if lane.get("blocked_reason") == "invalid_review_submitted":
        actions.append(
            "A submitted review failed rubric validation; re-read the packet and resubmit against "
            "its current packet_hash."
        )
    if lane.get("self_reviewed_only"):
        actions.append(
            "Every judgement came from the agent that authored the UI. Self-review is recorded but "
            "weak evidence; have an independent judge or a human confirm before calling it accepted."
        )
    if not lane.get("unanimous", True):
        actions.append("Judges disagreed on this pair; record which reading you accepted and why.")
    for entry in list(lane.get("worst_criteria") or [])[:2]:
        actions.append(
            f"Weakest criterion '{entry.get('criterion')}' scored {entry.get('score')} "
            f"({SCALE.get(int(entry.get('score', 0)), '')}): {entry.get('observation')}"
        )
    return actions


def _normalize_judge(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"id": "", "role": "", "model": ""}
    return {
        "id": _text(raw, "id", "judge_id", "judgeId"),
        "role": _text(raw, "role").lower(),
        "model": _text(raw, "model"),
    }


def _normalize_criteria(raw: Any, policy: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(raw, dict):
        return {}, ["missing_criteria"]

    criteria: dict[str, Any] = {}
    errors: list[str] = []
    unknown: list[str] = []
    for key, value in raw.items():
        name = str(key).strip().lower()
        if name not in CRITERIA:
            unknown.append(str(key))
            continue
        if name in criteria:
            errors.append(f"duplicate_criterion_{name}")
            continue
        if isinstance(value, dict):
            score = _score(value.get("score"))
            observation = _text(value, "observation", "note")
        else:
            score = _score(value)
            observation = ""
        if score is None:
            errors.append(f"invalid_score_{name}")
            continue
        if not observation:
            errors.append(f"missing_observation_{name}")
        criteria[name] = {"score": score, "name": SCALE[score], "observation": observation}

    errors.extend(f"unknown_criterion_{name}" for name in unknown)
    missing = [key for key in (policy.get("required_criteria") or CRITERIA) if key not in criteria]
    errors.extend(f"missing_criterion_{key}" for key in missing)
    return criteria, errors


def _normalize_defects(raw: Any) -> list[dict[str, Any]]:
    defects: list[dict[str, Any]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        defects.append(
            {
                "severity": _text(entry, "severity").lower() or "minor",
                "criterion": _text(entry, "criterion").lower(),
                "region_id": _text(entry, "region_id", "regionId"),
                "note": _text(entry, "note", "observation"),
            }
        )
    return defects


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "judge": review.get("judge", {}),
        "verdict": review.get("verdict", ""),
        "overall_reported": review.get("overall_reported"),
        "overall_effective": review.get("overall_effective"),
        "failed_criteria": review.get("failed_criteria", []),
        "errors": review.get("errors", []),
        "warnings": review.get("warnings", []),
        "source_path": review.get("source_path", ""),
    }


def _worst_criteria(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    worst: dict[str, dict[str, Any]] = {}
    for review in reviews:
        for key, entry in (review.get("criteria") or {}).items():
            score = int(entry["score"])
            current = worst.get(key)
            if current is None or score < int(current["score"]):
                worst[key] = {
                    "criterion": key,
                    "score": score,
                    "name": SCALE[score],
                    "observation": entry.get("observation", ""),
                }
    return sorted(worst.values(), key=lambda item: (int(item["score"]), str(item["criterion"])))


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _score(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = int(value)
    return score if 0 <= score <= SCALE_MAX else None


def _resolve_path(value: str, workspace: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (workspace / path).resolve()
    if not path.is_file():
        raise ToolInvocationError(
            "ui_vision_review_not_found",
            f"Vision review '{path}' was not found.",
            {"review_path": str(path)},
        )
    return path


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
