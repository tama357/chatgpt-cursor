from __future__ import annotations

from typing import Any


def score_candidate(candidate: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    weights = rules["scoring_rubric"]["initial_weights"]
    penalty_codes = set(rules["scoring_rubric"]["penalty_codes"])
    factors = candidate.get("factors", {})
    breakdown: dict[str, int] = {}
    for key, maximum in weights.items():
        raw = factors.get(key, maximum * 0.6)
        if isinstance(raw, (int, float)):
            breakdown[key] = max(0, min(maximum, int(round(raw))))
        else:
            breakdown[key] = max(0, min(maximum, maximum // 2))
    penalties = candidate.get("penalties", [])
    penalty_total = 0
    normalized_penalties: list[dict[str, Any]] = []
    for penalty in penalties:
        code = penalty.get("code", "other")
        if code not in penalty_codes:
            code = "other"
        pts = int(penalty.get("points", 0))
        penalty_total += pts
        normalized_penalties.append({"code": code, "points": pts})
    score = max(0, min(100, sum(breakdown.values()) - penalty_total))
    return {
        **candidate,
        "prediction_score": score,
        "score_breakdown": breakdown,
        "penalties": normalized_penalties,
    }


def select_races(
    candidates: list[dict[str, Any]], rules: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_races = rules["max_races_per_day"]
    min_score = rules["scoring_rubric"].get("selection_min_score", 60)
    min_close = rules.get("minimum_close_time")

    scored = [score_candidate(c, rules) for c in candidates]
    if min_close:
        scored = [c for c in scored if c.get("close_time", "00:00") >= min_close]

    ranked = sorted(
        scored,
        key=lambda x: (
            -x["prediction_score"],
            x.get("venue", ""),
            x.get("race", 0),
        ),
    )
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    skipped_keys: set[tuple[Any, Any]] = set()

    def _skip(item: dict[str, Any], reason: str) -> None:
        key = (item.get("venue"), item.get("race"))
        if key in skipped_keys:
            return
        skipped_keys.add(key)
        skipped.append({**item, "skip_reason": reason})

    for item in ranked:
        if len(selected) >= max_races:
            _skip(item, "1日上限5レースのため対象外")
            continue
        if item["prediction_score"] < min_score:
            _skip(item, f"予想しやすさ{min_score}点未満")
            continue
        selected.append(item)

    selected_keys = {(s.get("venue"), s.get("race")) for s in selected}
    for item in ranked:
        key = (item.get("venue"), item.get("race"))
        if key not in selected_keys and key not in skipped_keys:
            _skip(item, "選定順位外")
    return selected, skipped
