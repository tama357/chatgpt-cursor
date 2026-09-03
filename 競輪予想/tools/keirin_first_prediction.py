"""Cursorの第一予想。最終予想ではない。ChatGPTが後から変更できる。"""

from __future__ import annotations

from typing import Any

from keirin_score import KYUHAN_RANK, _as_int, _kyuhan_rank

MIN_CLOSE_TIME = "18:00"
MAX_POINTS = 10
MAX_FIRST_RACES = 3
MIN_RIDERS_FOR_TRIFECTA = 3
MIN_RIDERS_COMFORTABLE = 4


def build_cursor_first_prediction(
    candidates: list[dict[str, Any]],
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """候補全体を見て第一予想を作る。スコア上位3Rの機械固定はしない。"""
    rules = rules or {}
    min_close = str(rules.get("minimum_close_time") or MIN_CLOSE_TIME)
    evaluated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        result = evaluate_first_pick_race(item, min_close=min_close)
        if result["adopt"]:
            evaluated.append(result)
        else:
            rejected.append(
                {
                    "venue": result["venue"],
                    "race": result["race"],
                    "prediction_score": result.get("prediction_score"),
                    "reason": result["skip_reason"],
                }
            )

    selected = _choose_races_not_by_score(evaluated)
    selected_races: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        built = _build_selected_race(item, number=index)
        if built is None:
            rejected.append(
                {
                    "venue": item["venue"],
                    "race": item["race"],
                    "prediction_score": item.get("prediction_score"),
                    "reason": "買い目を矛盾なく組めなかったため採用しない",
                }
            )
            continue
        selected_races.append(built)

    if len(selected_races) < MAX_FIRST_RACES:
        shortfall = (
            f"第一予想は{len(selected_races)}Rです。不足分は推測で埋めていません。"
            "重要データ不足・confidence C・買い目不能のレースは見送りました。"
        )
    else:
        shortfall = None

    overall = _overall_reasoning(selected_races, rejected, shortfall)
    return {
        "is_final": False,
        "chatgpt_may_revise": True,
        "selected_races": selected_races,
        "target": [item["target"] for item in selected_races],
        "confidence": [item["confidence"] for item in selected_races],
        "main_bets": [list(item["main_bets"]) for item in selected_races],
        "backup_bets": [list(item["backup_bets"]) for item in selected_races],
        "total_points": sum(int(item["total_points"]) for item in selected_races),
        "reasoning": overall,
        "shortfall_reason": shortfall,
        "rejected_races": rejected,
    }


def evaluate_first_pick_race(
    candidate: dict[str, Any],
    *,
    min_close: str = MIN_CLOSE_TIME,
) -> dict[str, Any]:
    venue = str(candidate.get("venue") or "").strip()
    race = _race_number(candidate)
    close_time = str(candidate.get("deadline") or candidate.get("close_time") or "").strip()
    riders = _usable_riders(candidate)
    breakdown = candidate.get("score_breakdown") or {}
    penalties = list(candidate.get("penalties") or [])
    risk_factors = [str(item) for item in (candidate.get("risk_factors") or [])]
    nige = [rider for rider in riders if _style(rider) == "逃"]
    styles = {_style(rider) for rider in riders if _style(rider)}

    skip_reason = None
    if not venue or race <= 0:
        skip_reason = "会場またはレース番号が無い（重要データ不足）"
    elif not close_time or close_time < min_close:
        skip_reason = "締切18:00以降ではない"
    elif len(riders) < MIN_RIDERS_FOR_TRIFECTA:
        skip_reason = "出走選手が不足しており三連単を組めない（重要データ不足）"
    elif not any(_style(rider) for rider in riders):
        skip_reason = "脚質が取れておらず無理に採用しない"
    elif len(nige) >= 3 or len(styles) >= 5:
        skip_reason = "ラインが割れすぎていて confidence C 相当のため第一予想に使わない"
    elif not nige and _ability_spread(riders) <= 1:
        skip_reason = "軸が見えず confidence C 相当のため第一予想に使わない"

    confidence = "B"
    if skip_reason is None:
        axis_rel = _as_int(breakdown.get("axis_reliability"))
        simple = _as_int(breakdown.get("scenario_simplicity"))
        line = _as_int(breakdown.get("line_clarity"))
        penalty_codes = {str(item.get("code")) for item in penalties if isinstance(item, dict)}
        strong_axis = len(nige) == 1 and len(riders) >= MIN_RIDERS_COMFORTABLE
        messy = "fragmented_race" in penalty_codes or "no_clear_axis" in penalty_codes
        if messy and not strong_axis:
            skip_reason = "penalty上も軸が弱く confidence C 相当のため第一予想に使わない"
        elif strong_axis and axis_rel >= 16 and simple >= 12 and line >= 12 and not messy:
            confidence = "A"
        else:
            confidence = "B"

    selection_quality = (
        _as_int(breakdown.get("axis_reliability"))
        + _as_int(breakdown.get("scenario_simplicity"))
        + _as_int(breakdown.get("line_clarity"))
    )
    return {
        "adopt": skip_reason is None,
        "skip_reason": skip_reason,
        "candidate": candidate,
        "venue": venue,
        "race": race,
        "close_time": close_time,
        "riders": riders,
        "confidence": confidence,
        "selection_quality": selection_quality,
        "ability_gap": _as_int(breakdown.get("ability_gap")),
        "prediction_score": candidate.get("prediction_score"),
        "nige": nige,
    }


def _choose_races_not_by_score(evaluated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """prediction_score上位3件への機械固定をしない。"""
    ranked = sorted(
        evaluated,
        key=lambda item: (
            0 if item["confidence"] == "A" else 1,
            -int(item["selection_quality"]),
            -int(item["ability_gap"]),
            str(item["venue"]),
            int(item["race"]),
        ),
    )
    picked: list[dict[str, Any]] = []
    used_venues: set[str] = set()
    for item in ranked:
        if len(picked) >= MAX_FIRST_RACES:
            break
        venue = item["venue"]
        if venue in used_venues:
            alt = next(
                (
                    other
                    for other in ranked
                    if other not in picked
                    and other["venue"] not in used_venues
                    and abs(int(other["selection_quality"]) - int(item["selection_quality"])) <= 8
                ),
                None,
            )
            if alt is not None:
                continue
        picked.append(item)
        used_venues.add(venue)
    return picked


def _build_selected_race(evaluated: dict[str, Any], *, number: int) -> dict[str, Any] | None:
    candidate = evaluated["candidate"]
    riders = evaluated["riders"]
    tickets = build_line_tickets(riders)
    if tickets is None:
        return None
    main_bets = [item["pick"] for item in tickets if item["type"] == "本線"]
    backup_bets = [item["pick"] for item in tickets if item["type"] == "抑え"]
    total = tickets_point_count(tickets)
    if total <= 0 or total > MAX_POINTS:
        return None
    if not main_bets or not backup_bets:
        return None
    target = "鉄板" if evaluated["confidence"] == "A" and total <= 6 else "中穴"
    axis = main_bets[0].split("-")[0]
    reasoning = (
        f"{evaluated['venue']}{evaluated['race']}Rは軸{axis}を1名に絞った。"
        f"ラインと買い目を合わせ、2着候補の後ろは3着から外していない。"
        f"confidence {evaluated['confidence']}。"
        "最終予想ではない。"
    )
    return {
        "number": number,
        "venue": evaluated["venue"],
        "race": evaluated["race"],
        "close_time": evaluated["close_time"],
        "target": target,
        "confidence": evaluated["confidence"],
        "main_bets": main_bets,
        "backup_bets": backup_bets,
        "total_points": total,
        "reasoning": reasoning,
        "tickets": tickets,
        "prediction_score": candidate.get("prediction_score"),
        "extract_rank": candidate.get("extract_rank"),
    }


def build_line_tickets(riders: list[dict[str, Any]]) -> list[dict[str, str]] | None:
    from keirin_workflow import ValidationError, expand_pick

    ordered = sorted(riders, key=_rider_strength, reverse=True)
    nige = [rider for rider in ordered if _style(rider) == "逃"]
    if len(nige) == 1:
        axis = nige[0]
    else:
        axis = ordered[0]
    axis_no = _num(axis)
    rest = [rider for rider in ordered if _num(rider) != axis_no]
    if not rest:
        return None

    seconds = _second_candidates(axis, rest)
    if not seconds:
        return None
    behind = _riders_behind_seconds(seconds, rest)

    main_second = seconds[0]
    main_thirds = _third_numbers(axis_no, _num(main_second), behind, rest)
    if not main_thirds:
        return None
    main_thirds = _trim_thirds(main_thirds, reserve_backup=True)
    main_pick = _compact(axis_no, _num(main_second), main_thirds)

    backup_first = main_second
    backup_thirds = _third_numbers(axis_no, _num(backup_first), behind, rest)
    backup_thirds = [no for no in backup_thirds if no != axis_no]
    if axis_no not in backup_thirds and axis_no != _num(backup_first):
        # 差し返しでも軸を3着から外しすぎない。ただし1-2と2-1の対称を優先する
        pass
    backup_pick = _compact(_num(backup_first), axis_no, _trim_thirds(backup_thirds or main_thirds, reserve_backup=False))

    tickets = [
        {"type": "本線", "pick": main_pick},
        {"type": "抑え", "pick": backup_pick},
    ]
    try:
        seen: set[str] = set()
        for ticket in tickets:
            combos = expand_pick(ticket["pick"])
            if seen.intersection(combos):
                return None
            seen.update(combos)
        if not 1 <= len(seen) <= MAX_POINTS:
            return None
    except ValidationError:
        return None
    return tickets


def tickets_point_count(tickets: list[dict[str, str]]) -> int:
    from keirin_workflow import ValidationError, expand_pick

    total = 0
    seen: set[str] = set()
    for ticket in tickets:
        try:
            combos = expand_pick(ticket["pick"])
        except ValidationError:
            return 0
        if seen.intersection(combos):
            return 0
        seen.update(combos)
        total += len(combos)
    return total


def _second_candidates(axis: dict[str, Any], rest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    axis_style = _style(axis)
    preferred = []
    others = []
    for rider in rest:
        style = _style(rider)
        if axis_style == "逃" and style in {"両", "追"}:
            preferred.append(rider)
        elif axis_style != "逃" and style in {"逃", "両"}:
            preferred.append(rider)
        else:
            others.append(rider)
    ordered = preferred + others
    return ordered[:2] if ordered else []


def _riders_behind_seconds(
    seconds: list[dict[str, Any]],
    rest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    second_nums = {_num(item) for item in seconds}
    behind = []
    for rider in rest:
        if _num(rider) in second_nums:
            continue
        style = _style(rider)
        if style in {"追", "マ", "両", ""}:
            behind.append(rider)
        else:
            behind.append(rider)
    return behind


def _third_numbers(
    first: str,
    second: str,
    behind: list[dict[str, Any]],
    rest: list[dict[str, Any]],
) -> list[str]:
    numbers: list[str] = []
    for rider in behind + rest:
        no = _num(rider)
        if no in {first, second} or no in numbers:
            continue
        numbers.append(no)
    return numbers


def _trim_thirds(thirds: list[str], *, reserve_backup: bool) -> list[str]:
    if not thirds:
        return []
    limit = 4 if reserve_backup else 5
    return thirds[:limit]


def _compact(first: str, second: str, thirds: list[str]) -> str:
    unique = [no for no in thirds if no not in {first, second}]
    unique = list(dict.fromkeys(unique))
    ordered = "".join(sorted(unique, key=lambda item: int(item) if item.isdigit() else item))
    return f"{first}-{second}-{ordered}"


def _overall_reasoning(
    selected: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    shortfall: str | None,
) -> str:
    names = "、".join(f"{item['venue']}{item['race']}R" for item in selected) or "なし"
    skipped = "、".join(
        f"{item['venue']}{item['race']}R（{item['reason']}）" for item in rejected[:6]
    )
    parts = [
        f"Cursor第一予想として {names} を選んだ。",
        "prediction_score上位3Rを機械的に選んでいない。",
        "最終予想ではない。ChatGPTが候補全体を再確認し、レース・軸・買い目を変えてよい。",
    ]
    if skipped:
        parts.append(f"見送り: {skipped}")
    if shortfall:
        parts.append(shortfall)
    return "".join(parts)


def _usable_riders(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    raw = candidate.get("riders") or candidate.get("entries") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for rider in raw:
        if not isinstance(rider, dict):
            continue
        if rider.get("number") in (None, ""):
            continue
        if rider.get("scratch") or rider.get("kessya"):
            continue
        out.append(rider)
    return out


def _race_number(item: dict[str, Any]) -> int:
    if item.get("race_number") not in (None, ""):
        try:
            return int(item["race_number"])
        except (TypeError, ValueError):
            return 0
    race = item.get("race")
    if isinstance(race, int):
        return race
    if isinstance(race, str) and race.isdigit():
        return int(race)
    return 0


def _style(rider: dict[str, Any]) -> str:
    return str(rider.get("winning_style") or rider.get("kyaku") or "").strip()


def _num(rider: dict[str, Any]) -> str:
    return str(rider.get("number"))


def _rider_strength(rider: dict[str, Any]) -> tuple[int, float, int]:
    recent = rider.get("recent_results") or {}
    first = _as_int(recent.get("first") if isinstance(recent, dict) else 0)
    second = _as_int(recent.get("second") if isinstance(recent, dict) else 0)
    third = _as_int(recent.get("third") if isinstance(recent, dict) else 0)
    form = first * 3 + second * 2 + third
    style_bonus = 4 if _style(rider) == "逃" else (2 if _style(rider) == "両" else 0)
    return (_kyuhan_rank(rider) + style_bonus, form, -int(_num(rider) or 0))


def _ability_spread(riders: list[dict[str, Any]]) -> int:
    ranks = [KYUHAN_RANK.get(str(rider.get("kyuhan") or rider.get("class") or "").upper(), 2) for rider in riders]
    if not ranks:
        return 0
    return max(ranks) - min(ranks)
