"""prediction_score は候補抽出の参考。第一予想でも上位3Rへ機械固定しない。最終3RはChatGPT。"""

from __future__ import annotations

from typing import Any

KYUHAN_RANK = {
    "SS": 7,
    "S1": 6,
    "S2": 5,
    "A1": 4,
    "A2": 3,
    "A3": 2,
    "A": 3,
    "B1": 1,
    "B2": 1,
}


def score_candidate(candidate: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    weights = rules["scoring_rubric"]["initial_weights"]
    penalty_codes = set(rules["scoring_rubric"]["penalty_codes"])
    breakdown, penalties = _derive_breakdown_and_penalties(candidate, weights)
    penalty_total = 0
    normalized: list[dict[str, Any]] = []
    for penalty in penalties:
        code = penalty.get("code", "other")
        if code not in penalty_codes:
            code = "other"
        points = int(penalty.get("points", 0))
        penalty_total += points
        normalized.append({"code": code, "points": points})
    score = max(0, min(100, sum(breakdown.values()) - penalty_total))
    return {
        **candidate,
        "prediction_score": score,
        "score_breakdown": breakdown,
        "penalties": normalized,
    }


def extract_candidates(
    races: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    min_count: int = 5,
    max_count: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """締切18:00以降をスコア順に5〜10R抽出する。最終3Rは決めない。"""
    min_close = rules.get("minimum_close_time") or "18:00"
    scored = [score_candidate(race, rules) for race in races]
    eligible = [item for item in scored if str(item.get("close_time") or item.get("deadline") or "00:00") >= min_close]
    ranked = sorted(
        eligible,
        key=lambda item: (
            -int(item["prediction_score"]),
            -int((item.get("score_breakdown") or {}).get("axis_reliability") or 0),
            -int((item.get("score_breakdown") or {}).get("scenario_simplicity") or 0),
            -int((item.get("score_breakdown") or {}).get("recent_form") or 0),
            str(item.get("venue") or ""),
            int(item.get("race") or item.get("race_number") or 0),
        ),
    )
    take = min(max_count, max(len(ranked), 0))
    if take >= min_count:
        take = min(max_count, len(ranked))
    selected = ranked[:take]
    skipped = []
    selected_keys = {_race_key(item) for item in selected}
    for item in scored:
        key = _race_key(item)
        if key in selected_keys:
            continue
        reason = "締切18:00前" if str(item.get("close_time") or item.get("deadline") or "00:00") < min_close else "候補抽出の対象外"
        skipped.append({**item, "skip_reason": reason})
    return selected, skipped


def _race_key(item: dict[str, Any]) -> tuple[str, int]:
    venue = str(item.get("venue") or "").strip()
    race = item.get("race_number", item.get("race"))
    return venue, int(race or 0)


def _derive_breakdown_and_penalties(
    candidate: dict[str, Any], weights: dict[str, int]
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if isinstance(candidate.get("factors"), dict) and candidate.get("factors"):
        breakdown = _from_factors(candidate["factors"], weights)
        return breakdown, list(candidate.get("penalties") or [])

    riders = list(candidate.get("riders") or candidate.get("entries") or [])
    ranks = [_kyuhan_rank(rider) for rider in riders]
    kyaku = [str(rider.get("winning_style") or rider.get("kyaku") or "") for rider in riders]
    nige = sum(1 for item in kyaku if item == "逃")
    unique_kyaku = {item for item in kyaku if item}
    form_hits = _recent_place_rate(riders)
    scratches = list(candidate.get("scratches") or [])
    kessya = bool(candidate.get("kessya") or scratches)

    ability_spread = (max(ranks) - min(ranks)) if ranks else 0
    top_gap = 0
    if ranks:
        ordered = sorted(ranks, reverse=True)
        top_gap = ordered[0] - (ordered[1] if len(ordered) > 1 else 0)

    raw = {
        "axis_reliability": 10 + top_gap * 3 + (4 if nige == 1 else 0),
        "line_clarity": 8 + (5 if nige in {1, 2} else 0) + min(4, len(unique_kyaku)),
        "ability_gap": 8 + min(7, ability_spread * 2),
        "scenario_simplicity": 14 if nige == 1 else (10 if nige == 2 else 6),
        "recent_form": 8 + int(round(form_hits * 7)),
        "track_style_fit": 7 if candidate.get("home_bank_fit") else 5,
        "risk_absence": 4 if kessya else 9,
    }
    breakdown = {key: max(0, min(weights[key], int(raw.get(key, weights[key] * 0.6)))) for key in weights}

    penalties: list[dict[str, Any]] = list(candidate.get("penalties") or [])
    if nige == 0:
        penalties.append({"code": "no_clear_axis", "points": 5})
    if ability_spread <= 1 and ranks:
        penalties.append({"code": "evenly_matched", "points": 3})
    if nige >= 3 or len(unique_kyaku) >= 4:
        penalties.append({"code": "fragmented_race", "points": 3})
    if not riders:
        penalties.append({"code": "other", "points": 4})
    return breakdown, penalties


def _from_factors(factors: dict[str, Any], weights: dict[str, int]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for key, maximum in weights.items():
        raw = factors.get(key, maximum * 0.6)
        if isinstance(raw, (int, float)):
            breakdown[key] = max(0, min(maximum, int(round(raw))))
        else:
            breakdown[key] = max(0, min(maximum, maximum // 2))
    return breakdown


def _kyuhan_rank(rider: dict[str, Any]) -> int:
    value = str(rider.get("kyuhan") or rider.get("class") or "").upper()
    return KYUHAN_RANK.get(value, 2)


def _recent_place_rate(riders: list[dict[str, Any]]) -> float:
    hits = 0
    total = 0
    for rider in riders:
        recent = rider.get("recent_results") or {}
        if isinstance(recent, dict):
            first = _as_int(recent.get("first") or recent.get("tyo4Tyaku1st"))
            second = _as_int(recent.get("second") or recent.get("tyo4Tyaku2nd"))
            third = _as_int(recent.get("third") or recent.get("tyo4Tyaku3rd"))
            out = _as_int(recent.get("out") or recent.get("tyo4TyakuOut"))
            placed = first + second + third
            denom = placed + out
            if denom:
                hits += placed
                total += denom
    if not total:
        return 0.45
    return hits / total


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
