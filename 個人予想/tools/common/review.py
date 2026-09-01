from __future__ import annotations

from typing import Any

from .tickets import check_hit, expand_tickets


def analyze_review(record: dict[str, Any], official_trifecta: str | None = None) -> dict[str, Any]:
    trifecta = official_trifecta or (record.get("result") or {}).get("trifecta")
    tickets = record.get("tickets", [])
    expanded = expand_tickets(tickets) if tickets else []
    all_combos = {c for t in expanded for c in t.combinations}
    hit = check_hit(trifecta, tickets) if trifecta and tickets else False

    axis = record.get("axis", "")
    axis_first = axis.split("-")[0] if axis else ""
    actual_first = trifecta.split("-")[0] if trifecta else ""
    actual_second = trifecta.split("-")[1] if trifecta and len(trifecta.split("-")) > 1 else ""
    actual_third = trifecta.split("-")[2] if trifecta and len(trifecta.split("-")) > 2 else ""

    axis_ok = axis_first == actual_first if axis_first and actual_first else None
    second_candidates = _second_candidates(tickets)
    third_candidates = _third_candidates(tickets)
    second_ok = actual_second in second_candidates if actual_second else None
    third_ok = actual_third in third_candidates if actual_third else None

    primary_miss, secondary = _classify_miss(
        hit=hit,
        axis_ok=axis_ok,
        second_ok=second_ok,
        third_ok=third_ok,
        record=record,
    )
    close_miss = (
        not hit
        and axis_ok is True
        and (second_ok is True or third_ok is True)
    )
    review = {
        "axis_selection_ok": axis_ok,
        "second_candidates_ok": second_ok,
        "third_candidates_ok": third_ok,
        "scenario_realized": record.get("scenario_realized"),
        "no_waste_in_tickets": hit or (axis_ok and second_ok),
        "tickets_sufficient": hit or close_miss,
        "confidence_appropriate": _confidence_check(record, hit),
        "prediction_score_appropriate": None,
        "hit_but_issues": hit and not (axis_ok and second_ok and third_ok),
        "miss_but_read_ok": (not hit) and (axis_ok or second_ok),
        "improvements": _improvements(record, hit, axis_ok, second_ok, third_ok, close_miss),
        "primary_miss_reason": primary_miss,
        "secondary_miss_reasons": secondary,
        "close_miss": close_miss,
        "close_miss_detail": _close_miss_detail(trifecta, all_combos, close_miss),
    }
    return review


def _second_candidates(tickets: list[dict[str, str]]) -> set[str]:
    result: set[str] = set()
    for ticket in tickets:
        parts = ticket["pick"].split("-")
        if len(parts) >= 2:
            result.add(parts[1])
    return result


def _third_candidates(tickets: list[dict[str, str]]) -> set[str]:
    result: set[str] = set()
    for ticket in tickets:
        parts = ticket["pick"].split("-")
        if len(parts) >= 3:
            result.update(parts[2])
    return result


def _classify_miss(
    *,
    hit: bool,
    axis_ok: bool | None,
    second_ok: bool | None,
    third_ok: bool | None,
    record: dict[str, Any],
) -> tuple[str | None, list[str]]:
    if hit:
        return None, []
    secondary: list[str] = []
    if axis_ok is False:
        return "axis_miss", secondary
    if second_ok is False:
        primary = "second_place_miss"
        if record.get("scenario_realized") is False:
            secondary.append("scenario_miss")
        return primary, secondary
    if third_ok is False:
        primary = "third_place_miss"
        ticket_count = record.get("ticket_count", 0)
        max_pts = 10
        if ticket_count >= max_pts:
            secondary.append("too_many_combinations")
        elif ticket_count <= 3:
            secondary.append("too_few_combinations")
        return primary, secondary
    if record.get("confidence") == "A" and not hit:
        return "overconfidence", ["scenario_miss"]
    return "other", secondary


def _confidence_check(record: dict[str, Any], hit: bool) -> bool | None:
    conf = record.get("confidence")
    if conf == "A":
        return hit
    if conf == "C" and hit:
        return False
    return True


def _improvements(
    record: dict[str, Any],
    hit: bool,
    axis_ok: bool | None,
    second_ok: bool | None,
    third_ok: bool | None,
    close_miss: bool,
) -> list[str]:
    items: list[str] = []
    if not hit and axis_ok is False:
        items.append("軸候補の再評価（能力・展開・脚質）")
    if not hit and second_ok is False:
        items.append("2着候補の幅を見直す")
    if not hit and third_ok is False:
        items.append("3着の穴候補を1〜2頭追加検討")
    if close_miss:
        items.append("惜しいレース：抑えの3着厚みを微調整")
    if hit and record.get("confidence") == "C":
        items.append("的中したが自信度C：根拠の言語化を強化")
    if record.get("ticket_count", 0) >= 10 and not hit:
        items.append("10点フル時は本線絞り込みを検討")
    if not items:
        items.append("大きな改善点なし。同方針で継続")
    return items


def _close_miss_detail(
    trifecta: str | None, combos: set[str], close_miss: bool
) -> dict[str, Any] | None:
    if not close_miss or not trifecta:
        return None
    parts = trifecta.split("-")
    partials = [
        c
        for c in combos
        if c.startswith(f"{parts[0]}-") or c.endswith(f"-{parts[2]}")
    ]
    return {
        "official": trifecta,
        "partially_covered": partials[:5],
        "missing_note": "1着または2着まで一致した買い目があった",
    }
