from __future__ import annotations

from typing import Any

from common.tickets import ValidationError, count_tickets


def build_prediction(candidate: dict[str, Any], rules: dict[str, Any], number: int) -> dict[str, Any]:
    entries = candidate.get("entries", [])
    sport = rules["sport"]
    tickets = _build_tickets(candidate, entries, rules)
    ticket_count = count_tickets(tickets)
    confidence = _confidence(candidate, ticket_count, rules)
    target = _target(candidate)
    return {
        "number": number,
        "sport": sport,
        "date": candidate.get("date"),
        "venue": candidate.get("venue"),
        "race": candidate.get("race"),
        "close_time": candidate.get("close_time"),
        "target": target,
        "confidence": confidence,
        "prediction_score": candidate["prediction_score"],
        "score_breakdown": candidate.get("score_breakdown", {}),
        "penalties": candidate.get("penalties", []),
        "axis": candidate.get("axis"),
        "tickets": tickets,
        "ticket_count": ticket_count,
        "rationale": candidate.get("rationale") or _default_rationale(candidate),
        "scenario": candidate.get("scenario") or _default_scenario(candidate),
        "risks": candidate.get("risks") or _default_risks(candidate),
        "odds_band_median": candidate.get("odds_band_median"),
        "fetched_data": candidate.get("fetched_data", {}),
        "prediction_logic_version": rules.get("prediction_logic_version"),
    }


def _build_tickets(
    candidate: dict[str, Any], entries: list[dict[str, Any]], rules: dict[str, Any]
) -> list[dict[str, str]]:
    if candidate.get("tickets"):
        return candidate["tickets"]
    axis = str(candidate.get("axis", "1"))
    rivals = candidate.get("rivals") or _top_rivals(entries, axis)
    min_pts = rules.get("min_combinations_per_race", 1)
    max_pts = rules["max_combinations_per_race"]
    if rules.get("sport") in {"jra", "nar", "kyotei", "keiba"}:
        return _build_keiba_tickets(axis, rivals, entries, min_pts, max_pts)
    return _build_keirin_tickets(axis, rivals, entries, max_pts)


def _build_keirin_tickets(
    axis: str, rivals: list[str], entries: list[dict[str, Any]], max_pts: int
) -> list[dict[str, str]]:
    third_pool = _third_pool(entries, axis, rivals)
    main_second = rivals[0] if rivals else "2"
    cover_second = rivals[1] if len(rivals) > 1 else main_second
    third_str = "".join(third_pool[:4]) or "345"
    tickets = [{"type": "本線", "pick": f"{axis}-{main_second}-{third_str}"}]
    if cover_second != main_second:
        tickets.append({"type": "抑え", "pick": f"{cover_second}-{axis}-{third_str[:3]}"})
    while count_tickets(tickets) > max_pts and len(third_str) > 1:
        third_str = third_str[:-1]
        tickets[0]["pick"] = f"{axis}-{main_second}-{third_str}"
        if len(tickets) > 1:
            tickets[1]["pick"] = f"{cover_second}-{axis}-{third_str[:3]}"
    return tickets


def _bettable_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries:
        raw = entry.get("number")
        try:
            num = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= num <= 9:
            out.append({**entry, "number": num})
    return out


def _build_keiba_tickets(
    axis: str,
    rivals: list[str],
    entries: list[dict[str, Any]],
    min_pts: int,
    max_pts: int,
) -> list[dict[str, str]]:
    entries = _bettable_entries(entries)
    if axis not in {str(e["number"]) for e in entries}:
        axis = str(entries[0]["number"]) if entries else "1"
        rivals = _top_rivals(entries, axis)
    thirds = [
        n
        for n in _third_pool(entries, axis, rivals)
        if n not in {axis}
    ]
    seconds = rivals + [n for n in thirds if n not in rivals]
    tickets: list[dict[str, str]] = []
    third_str = "".join(dict.fromkeys(thirds))
    for second in seconds:
        if second == axis:
            continue
        usable_third = "".join(n for n in third_str if n not in {axis, second})
        if not usable_third:
            continue
        pick = f"{axis}-{second}-{usable_third}"
        candidate = {"type": "本線" if len(tickets) == 0 else "抑え", "pick": pick}
        try:
            trial = tickets + [candidate]
            if count_tickets(trial) <= max_pts:
                tickets.append(candidate)
        except ValidationError:
            continue
        if count_tickets(tickets) >= min_pts:
            break

    if not tickets:
        tickets = [{"type": "本線", "pick": f"{axis}-{seconds[0]}-{third_str[:4]}"}]

    while count_tickets(tickets) > max_pts and tickets:
        tickets.pop()

    return tickets


def _next_digit(
    entries: list[dict[str, Any]], axis: str, exclude: list[str], current: str
) -> str:
    blocked = {axis, *exclude, *list(current)}
    for e in entries:
        n = str(e.get("number"))
        if n not in blocked:
            return n
    for n in "23456789":
        if n not in blocked:
            return n
    return "9"


def _top_rivals(entries: list[dict[str, Any]], axis: str) -> list[str]:
    entries = _bettable_entries(entries)
    ranked = sorted(
        [e for e in entries if str(e.get("number")) != axis],
        key=lambda e: (-float(e.get("rating", e.get("score", 0))), int(e.get("number", 99))),
    )
    return [str(e.get("number")) for e in ranked[:2]] or ["2", "3"]


def _third_pool(entries: list[dict[str, Any]], axis: str, rivals: list[str]) -> list[str]:
    entries = _bettable_entries(entries)
    exclude = {axis, *rivals}
    nums = sorted(
        [str(e.get("number")) for e in entries if str(e.get("number")) not in exclude],
        key=lambda n: int(n),
    )
    return nums[:8] or ["3", "4", "5", "6", "7", "8"]


def _confidence(candidate: dict[str, Any], ticket_count: int, rules: dict[str, Any]) -> str:
    score = candidate["prediction_score"]
    max_pts = rules["max_combinations_per_race"]
    if score >= 85 and ticket_count <= max_pts * 0.6:
        return "A"
    if score >= 70:
        return "B"
    return "C"


def _target(candidate: dict[str, Any]) -> str:
    if candidate.get("target") in {"鉄板", "中穴", "大穴"}:
        return candidate["target"]
    score = candidate.get("prediction_score", 0)
    if score >= 85:
        return "鉄板"
    if score >= 72:
        return "中穴"
    return "大穴"


def _default_rationale(candidate: dict[str, Any]) -> str:
    parts = [f"軸{candidate.get('axis')}番"]
    if candidate.get("notes"):
        parts.append(str(candidate["notes"]))
    return "。".join(parts)


def _default_scenario(candidate: dict[str, Any]) -> str:
    return candidate.get("scenario") or f"軸{candidate.get('axis')}先行〜差し切り想定"


def _default_risks(candidate: dict[str, Any]) -> str:
    penalties = candidate.get("penalties", [])
    if penalties:
        return "、".join(p["code"] for p in penalties)
    return "展開変化に注意"
