#!/usr/bin/env python3
"""競輪予想の検証・記録・Chatwork。Cursorは予想せず、ChatGPT最終予想だけを転記する。"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
import keirin_drive_state as drive_state  # noqa: E402


PICK_RE = re.compile(r"^([1-9])-([1-9])-([1-9]+)$")
TRIFECTA_RE = re.compile(r"^[1-9]-[1-9]-[1-9]$")
ALLOWED_TARGETS = {"鉄板", "中穴", "大穴"}
ALLOWED_CONFIDENCE = {"A", "B", "C"}
ALLOWED_TICKET_TYPES = {"本線", "抑え"}
ALLOWED_STATUS = {"的中", "ハズレ"}
RACE_COUNT = 3
MAX_COMBINATIONS = 10
MIN_CLOSE_TIME = "18:00"
MISS_REASONS = {
    "axis_miss",
    "second_place_miss",
    "third_place_miss",
    "line_collapse",
    "unexpected_position",
    "upset",
    "accident",
    "other",
}


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExpandedTicket:
    kind: str
    compact: str
    combinations: tuple[str, ...]


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValidationError("JSONの最上位はオブジェクトにしてください")
    return data


def validate_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("dateはYYYY-MM-DD形式の文字列が必要です")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError("dateはYYYY-MM-DD形式にしてください") from exc
    return value


def validate_time(value: Any, field: str = "close_time") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field}はHH:MM形式の文字列が必要です")
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValidationError(f"{field}はHH:MM形式にしてください: {value}") from exc
    return parsed.strftime("%H:%M")


def expand_pick(compact: str) -> tuple[str, ...]:
    match = PICK_RE.fullmatch(compact)
    if not match:
        raise ValidationError(f"買い目の形式が不正です: {compact}")
    first, second, candidates = match.groups()
    if first == second:
        raise ValidationError(f"1着と2着が重複しています: {compact}")
    if len(set(candidates)) != len(candidates):
        raise ValidationError(f"3着候補に重複があります: {compact}")
    if first in candidates or second in candidates:
        raise ValidationError(f"同じ選手が複数着に含まれています: {compact}")
    return tuple(f"{first}-{second}-{third}" for third in candidates)


def check_hit(trifecta: str, tickets: list[dict[str, Any]]) -> bool:
    combinations: set[str] = set()
    for ticket in tickets:
        pick = ticket.get("pick")
        if isinstance(pick, str):
            combinations.update(expand_pick(pick))
    return trifecta in combinations


def extract_axis(tickets: list[dict[str, Any]]) -> str:
    if not isinstance(tickets, list) or not tickets:
        raise ValidationError("本線買い目からaxisを抽出できません")
    firsts: set[str] = set()
    for ticket in tickets:
        if not isinstance(ticket, dict) or ticket.get("type") != "本線":
            continue
        compact = ticket.get("pick")
        if not isinstance(compact, str):
            raise ValidationError("本線買い目の形式が不正です")
        match = PICK_RE.fullmatch(compact)
        if not match:
            raise ValidationError(f"買い目の形式が不正です: {compact}")
        firsts.add(match.group(1))
    if not firsts:
        raise ValidationError("本線買い目が無いためaxisを抽出できません")
    if len(firsts) > 1:
        raise ValidationError("本線の1着番号が複数あるためaxisを特定できません")
    return firsts.pop()


def second_candidates(tickets: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for ticket in tickets:
        pick = ticket.get("pick")
        if not isinstance(pick, str):
            continue
        parts = pick.split("-")
        if len(parts) >= 2:
            result.add(parts[1])
    return result


def third_candidates(tickets: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for ticket in tickets:
        pick = ticket.get("pick")
        if not isinstance(pick, str):
            continue
        parts = pick.split("-")
        if len(parts) >= 3:
            result.update(parts[2])
    return result


def compute_close_miss(
    *,
    status: str,
    axis: str,
    tickets: list[dict[str, Any]],
    trifecta: str,
) -> bool:
    if status != "ハズレ":
        return False
    if not isinstance(trifecta, str) or not TRIFECTA_RE.fullmatch(trifecta):
        raise ValidationError("close_miss判定には正規の三連単が必要です")
    if not isinstance(axis, str) or not axis:
        raise ValidationError("close_miss判定にはaxisが必要です")
    first, second, third = trifecta.split("-")
    axis_ok = axis == first
    second_ok = second in second_candidates(tickets)
    third_ok = third in third_candidates(tickets)
    return bool(axis_ok and (second_ok or third_ok))


def validate_predictions(data: dict[str, Any]) -> list[list[ExpandedTicket]]:
    validate_date(data.get("date"))
    predictions = data.get("predictions")
    if not isinstance(predictions, list) or len(predictions) != RACE_COUNT:
        raise ValidationError("predictionsは3レース分必要です")

    seen_numbers: set[int] = set()
    seen_races: set[tuple[str, int]] = set()
    all_expanded: list[list[ExpandedTicket]] = []

    for prediction in predictions:
        if not isinstance(prediction, dict):
            raise ValidationError("各予想はオブジェクトにしてください")
        number = prediction.get("number")
        if number not in {1, 2, 3} or number in seen_numbers:
            raise ValidationError("予想番号は重複なしの1、2、3にしてください")
        seen_numbers.add(number)
        if prediction.get("target") not in ALLOWED_TARGETS:
            raise ValidationError(f"予想{number}: 狙いは鉄板・中穴・大穴のいずれかです")
        if prediction.get("confidence") not in ALLOWED_CONFIDENCE:
            raise ValidationError(f"予想{number}: 自信度はA・B・Cのいずれかです")
        venue = prediction.get("venue")
        race = prediction.get("race")
        if not isinstance(venue, str) or not venue.strip():
            raise ValidationError(f"予想{number}: 競輪場が必要です")
        if not isinstance(race, int) or not 1 <= race <= 12:
            raise ValidationError(f"予想{number}: Rは1〜12の半角整数にしてください")
        race_key = (venue.strip(), race)
        if race_key in seen_races:
            raise ValidationError(f"同じレースが重複しています: {venue}{race}R")
        seen_races.add(race_key)
        close_time = validate_time(prediction.get("close_time"))
        if close_time < MIN_CLOSE_TIME:
            raise ValidationError(f"予想{number}: 締切時刻は18:00以降が必要です")
        explanation = prediction.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValidationError(f"予想{number}: 解説が必要です")

        tickets = prediction.get("tickets")
        if not isinstance(tickets, list) or not tickets:
            raise ValidationError(f"予想{number}: 買い目が必要です")
        prediction_expanded: list[ExpandedTicket] = []
        seen_combinations: set[str] = set()
        for ticket in tickets:
            if not isinstance(ticket, dict) or ticket.get("type") not in ALLOWED_TICKET_TYPES:
                raise ValidationError(f"予想{number}: 本線/抑えの指定が不正です")
            compact = ticket.get("pick")
            if not isinstance(compact, str):
                raise ValidationError(f"予想{number}: 買い目は文字列が必要です")
            combinations = expand_pick(compact)
            duplicates = seen_combinations.intersection(combinations)
            if duplicates:
                raise ValidationError(
                    f"予想{number}: 展開後の買い目が重複しています: {', '.join(sorted(duplicates))}"
                )
            seen_combinations.update(combinations)
            prediction_expanded.append(ExpandedTicket(ticket["type"], compact, combinations))
        if len(seen_combinations) > MAX_COMBINATIONS:
            raise ValidationError(
                f"予想{number}: {len(seen_combinations)}点です。上限{MAX_COMBINATIONS}点を超えています"
            )
        all_expanded.append(prediction_expanded)
    return all_expanded


def format_predictions(data: dict[str, Any]) -> str:
    expanded = validate_predictions(data)
    sections: list[str] = []
    predictions = sorted(data["predictions"], key=lambda item: item["number"])
    expanded_by_number = {
        prediction["number"]: tickets
        for prediction, tickets in zip(data["predictions"], expanded)
    }
    for prediction in predictions:
        tickets = expanded_by_number[prediction["number"]]
        lines = [
            f"【予想{prediction['number']}】",
            "",
            f"狙い：{prediction['target']}",
            f"自信度：{prediction['confidence']}",
            "",
            f"{prediction['venue']}{prediction['race']}R 締切時刻{prediction['close_time']}",
            "",
            "●本線",
        ]
        main = [ticket for ticket in tickets if ticket.kind == "本線"]
        cover = [ticket for ticket in tickets if ticket.kind == "抑え"]
        lines.extend(
            [f"{ticket.compact} 　{len(ticket.combinations)}点" for ticket in main] or ["なし"]
        )
        lines.extend(["", "●抑え"])
        lines.extend(
            [f"{ticket.compact} 　{len(ticket.combinations)}点" for ticket in cover] or ["なし"]
        )
        total = sum(len(ticket.combinations) for ticket in tickets)
        lines.extend(["", f"計{total}点", "", "●解説", prediction["explanation"].strip()])
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def validate_results(data: dict[str, Any]) -> None:
    validate_date(data.get("date"))
    results = data.get("results")
    if not isinstance(results, list) or len(results) != RACE_COUNT:
        raise ValidationError("resultsは3レース分必要です")
    numbers: set[int] = set()
    for result in results:
        if not isinstance(result, dict):
            raise ValidationError("各結果はオブジェクトにしてください")
        number = result.get("number")
        if number not in {1, 2, 3} or number in numbers:
            raise ValidationError("結果番号は重複なしの1、2、3にしてください")
        numbers.add(number)
        trifecta = result.get("trifecta")
        if not isinstance(trifecta, str) or not TRIFECTA_RE.fullmatch(trifecta):
            raise ValidationError(f"結果{number}: 三連単は1-2-3形式にしてください")
        legs = trifecta.split("-")
        if len(set(legs)) != 3:
            raise ValidationError(f"結果{number}: 三連単の選手番号が重複しています")
        status = result.get("status")
        if status not in ALLOWED_STATUS:
            raise ValidationError(f"結果{number}: statusは的中またはハズレです")
        payout = result.get("payout")
        points = result.get("points")
        if not isinstance(payout, int) or payout < 0:
            raise ValidationError(f"結果{number}: payoutは0以上の半角整数にしてください")
        if status == "ハズレ" and payout != 0:
            raise ValidationError(f"結果{number}: ハズレ時のpayoutは0です")
        if status == "的中" and payout <= 0:
            raise ValidationError(f"結果{number}: 的中時のpayoutが必要です")
        if not isinstance(points, int) or not 1 <= points <= MAX_COMBINATIONS:
            raise ValidationError(f"結果{number}: pointsは1〜10の半角整数にしてください")


def format_results(data: dict[str, Any]) -> str:
    validate_results(data)
    results = sorted(data["results"], key=lambda item: item["number"])
    hits = sum(item["status"] == "的中" for item in results)
    total_points = sum(item["points"] for item in results)
    total_return = sum(item["payout"] for item in results)
    hit_rate = hits / len(results) * 100
    return_rate = total_return / (total_points * 100) * 100
    lines = [f"【{data['date']} 競輪予想結果】"]
    for item in results:
        lines.append(
            f"予想{item['number']}：{item['status']}／3連単 {item['trifecta']}／払戻 {item['payout']}円／{item['points']}点"
        )
    lines.extend(
        [
            "",
            f"当日的中率：{hit_rate:.2f}%（{hits}/{len(results)}）",
            f"当日回収率：{return_rate:.2f}%（払戻{total_return}円／購入{total_points * 100}円、1点100円換算）",
        ]
    )
    return "\n".join(lines)


def load_rules() -> dict[str, Any]:
    return load_json(Path(__file__).resolve().parents[1] / "current_rules.json")


def _race_key(item: dict[str, Any]) -> tuple[str, int]:
    venue = item.get("venue")
    race = item.get("race")
    if not isinstance(venue, str) or not venue.strip():
        raise ValidationError("内部state: venueが必要です")
    if not isinstance(race, int) or not 1 <= race <= 12:
        raise ValidationError("内部state: raceは1〜12の半角整数にしてください")
    return venue.strip(), race


def _validate_scored_item(
    item: dict[str, Any], weights: dict[str, int], penalty_codes: set[str]
) -> None:
    score = item.get("prediction_score")
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise ValidationError("内部state: prediction_scoreは0〜100の整数が必要です")
    breakdown = item.get("score_breakdown")
    if not isinstance(breakdown, dict) or set(breakdown) != set(weights):
        raise ValidationError("内部state: score_breakdownの項目がscoring_rubricと一致しません")
    for key, maximum in weights.items():
        value = breakdown[key]
        if not isinstance(value, int) or not 0 <= value <= maximum:
            raise ValidationError(f"内部state: {key}は0〜{maximum}の整数が必要です")
    penalties = item.get("penalties")
    if not isinstance(penalties, list):
        raise ValidationError("内部state: penaltiesは配列が必要です")
    penalty_total = 0
    for penalty in penalties:
        if not isinstance(penalty, dict) or penalty.get("code") not in penalty_codes:
            raise ValidationError("内部state: penalty codeが不正です")
        points = penalty.get("points")
        if not isinstance(points, int) or points < 0:
            raise ValidationError("内部state: penalty pointsは0以上の整数が必要です")
        penalty_total += points
    calculated = max(0, min(100, sum(breakdown.values()) - penalty_total))
    if score != calculated:
        raise ValidationError(
            f"内部state: prediction_score={score}ですが内訳・減点からの計算値は{calculated}です"
        )


def _validate_internal_result(result: dict[str, Any]) -> None:
    status = result.get("status")
    if status not in ALLOWED_STATUS:
        raise ValidationError("内部state: result.statusは的中またはハズレです")
    stake = result.get("stake")
    payout = result.get("payout")
    if not isinstance(stake, int) or stake <= 0:
        raise ValidationError("内部state: result.stakeは1以上の整数が必要です")
    if not isinstance(payout, int) or payout < 0:
        raise ValidationError("内部state: result.payoutは0以上の整数が必要です")
    primary = result.get("primary_miss_reason")
    secondary = result.get("secondary_miss_reasons")
    if not isinstance(secondary, list) or len(secondary) != len(set(secondary)):
        raise ValidationError("内部state: secondary_miss_reasonsは重複のない配列が必要です")
    if status == "的中":
        if primary is not None or secondary:
            raise ValidationError("内部state: 的中時にmiss_reasonは保存しません")
    else:
        if primary not in MISS_REASONS:
            raise ValidationError("内部state: ハズレ時はprimary_miss_reasonが必要です")
        if payout != 0:
            raise ValidationError("内部state: ハズレ時のpayoutは0です")
        if primary in secondary or any(reason not in MISS_REASONS for reason in secondary):
            raise ValidationError("内部state: secondary_miss_reasonsが不正です")
    trifecta = result.get("trifecta")
    if trifecta is not None:
        if not isinstance(trifecta, str) or not TRIFECTA_RE.fullmatch(trifecta):
            raise ValidationError("内部state: result.trifectaは1-2-3形式にしてください")
        if len(set(trifecta.split("-"))) != 3:
            raise ValidationError("内部state: result.trifectaの選手番号が重複しています")
    close_miss = result.get("close_miss")
    if close_miss is not None and not isinstance(close_miss, bool):
        raise ValidationError("内部state: result.close_missはtrueまたはfalseです")


def _validate_optional_learning_fields(prediction: dict[str, Any]) -> None:
    tickets = prediction.get("tickets")
    axis = prediction.get("axis")
    if tickets is not None:
        if not isinstance(tickets, list) or not tickets:
            raise ValidationError("内部state: ticketsは空でない配列が必要です")
        seen: set[str] = set()
        total = 0
        for ticket in tickets:
            if not isinstance(ticket, dict) or ticket.get("type") not in ALLOWED_TICKET_TYPES:
                raise ValidationError("内部state: ticketsのtypeが不正です")
            compact = ticket.get("pick")
            if not isinstance(compact, str):
                raise ValidationError("内部state: ticketsのpickが不正です")
            combinations = expand_pick(compact)
            if seen.intersection(combinations):
                raise ValidationError("内部state: ticketsの買い目が重複しています")
            seen.update(combinations)
            total += len(combinations)
        if prediction.get("ticket_count") != total:
            raise ValidationError("内部state: ticket_countとticketsの点数が一致しません")
        if axis is not None and axis != extract_axis(tickets):
            raise ValidationError("内部state: axisが本線先頭と一致しません")
    if axis is not None and (not isinstance(axis, str) or not re.fullmatch(r"[1-9]", axis)):
        raise ValidationError("内部state: axisは1〜9の文字列が必要です")


def validate_state(data: dict[str, Any], rules: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rules = rules or load_rules()
    rubric = rules["scoring_rubric"]
    weights = rubric["initial_weights"]
    if sum(weights.values()) != 100:
        raise ValidationError("scoring_rubric.initial_weightsの合計は100が必要です")
    penalty_codes = set(rubric["penalty_codes"])
    threshold = rubric["low_quality_day_threshold"]
    days = data.get("days")
    if data.get("version") != 1 or not isinstance(days, list):
        raise ValidationError("内部stateはversion=1とdays配列が必要です")

    completed: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for day in days:
        if not isinstance(day, dict):
            raise ValidationError("内部state: daysの各要素はオブジェクトが必要です")
        date = validate_date(day.get("date"))
        if date in seen_dates:
            raise ValidationError(f"内部state: 日付が重複しています: {date}")
        seen_dates.add(date)
        candidates = day.get("candidates")
        predictions = day.get("predictions")
        if not isinstance(candidates, list) or len(candidates) < RACE_COUNT:
            raise ValidationError("内部state: candidatesは3レース以上必要です")
        if not isinstance(predictions, list) or len(predictions) != RACE_COUNT:
            raise ValidationError("内部state: predictionsは3レース分必要です")

        candidate_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValidationError("内部state: candidateはオブジェクトが必要です")
            key = _race_key(candidate)
            if key in candidate_by_key:
                raise ValidationError(f"内部state: candidateが重複しています: {key}")
            validate_time(candidate.get("close_time"))
            if candidate["close_time"] < MIN_CLOSE_TIME:
                raise ValidationError("内部state: candidateは締切18:00以降が必要です")
            _validate_scored_item(candidate, weights, penalty_codes)
            candidate_by_key[key] = candidate

        prediction_keys: dict[tuple[str, int], int] = {}
        numbers: set[int] = set()
        for prediction in predictions:
            if not isinstance(prediction, dict):
                raise ValidationError("内部state: predictionはオブジェクトが必要です")
            number = prediction.get("number")
            if number not in {1, 2, 3} or number in numbers:
                raise ValidationError("内部state: prediction.numberは重複なしの1〜3が必要です")
            numbers.add(number)
            key = _race_key(prediction)
            if key not in candidate_by_key or key in prediction_keys:
                raise ValidationError("内部state: predictionsはcandidates内のレースである必要があります")
            prediction_keys[key] = number

        selected_scores = [candidate_by_key[key]["prediction_score"] for key in prediction_keys]
        expected_low_quality = min(selected_scores) < threshold
        if day.get("low_quality_day") is not expected_low_quality:
            raise ValidationError(
                f"内部state: low_quality_dayは選定3Rの最低スコア{min(selected_scores)}に対して{expected_low_quality}です"
            )
        for candidate in candidates:
            key = _race_key(candidate)
            if key in prediction_keys:
                expected_selected, expected_rank = True, prediction_keys[key]
            else:
                expected_selected, expected_rank = False, None
            if candidate.get("selected") is not expected_selected or candidate.get("selection_rank") != expected_rank:
                raise ValidationError(
                    "内部state: selected/selection_rankはChatGPTが選んだ3レースと一致が必要です"
                )

        for prediction in predictions:
            key = _race_key(prediction)
            _validate_scored_item(prediction, weights, penalty_codes)
            candidate = candidate_by_key[key]
            for field in ("prediction_score", "score_breakdown", "penalties"):
                if prediction.get(field) != candidate.get(field):
                    raise ValidationError(f"内部state: predictionとcandidateの{field}が一致しません")
            if prediction.get("target") not in ALLOWED_TARGETS:
                raise ValidationError("内部state: targetが不正です")
            if prediction.get("confidence") not in ALLOWED_CONFIDENCE:
                raise ValidationError("内部state: confidenceはA・B・Cが必要です")
            first_count = prediction.get("first_place_candidate_count")
            if first_count not in {1, 2}:
                raise ValidationError("内部state: 1着候補数は1または2が必要です")
            ticket_count = prediction.get("ticket_count")
            if not isinstance(ticket_count, int) or not 1 <= ticket_count <= MAX_COMBINATIONS:
                raise ValidationError("内部state: ticket_countは1〜10が必要です")
            _validate_optional_learning_fields(prediction)
            result = prediction.get("result")
            if result is not None:
                if not isinstance(result, dict):
                    raise ValidationError("内部state: resultはオブジェクトが必要です")
                _validate_internal_result(result)
                completed.append(
                    {
                        **prediction,
                        "date": date,
                        "low_quality_day": day["low_quality_day"],
                    }
                )
    return completed


def _performance(records: list[dict[str, Any]]) -> dict[str, Any]:
    stake = sum(item["result"]["stake"] for item in records)
    payout = sum(item["result"]["payout"] for item in records)
    hits = sum(item["result"]["status"] == "的中" for item in records)
    return {
        "n": len(records),
        "hits": hits,
        "hit_rate": hits / len(records) if records else None,
        "stake": stake,
        "payout": payout,
        "return_rate": payout / stake if stake else None,
    }


def _group_performance(records: list[dict[str, Any]], key_function: Any) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        groups.setdefault(str(key_function(item)), []).append(item)
    return {key: _performance(groups[key]) for key in sorted(groups)}


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)
    )
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _score_band(score: int) -> str:
    if score < 60:
        return "0-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def _recommended_weights(
    initial: dict[str, int], correlations: dict[str, dict[str, Any]], sample_size: int
) -> dict[str, Any]:
    if sample_size < 5:
        return {
            "status": "insufficient_data",
            "sample_size": sample_size,
            "weights": dict(initial),
            "auto_applied": False,
        }
    raw: dict[str, float] = {}
    for key, weight in initial.items():
        values = [
            value
            for value in (
                correlations[key]["hit_rate_correlation"],
                correlations[key]["return_rate_correlation"],
            )
            if value is not None
        ]
        signal = sum(values) / len(values) if values else 0.0
        raw[key] = weight * max(0.5, 1 + 0.35 * signal)
    scale = 100 / sum(raw.values())
    scaled = {key: raw[key] * scale for key in raw}
    proposed = {key: math.floor(value) for key, value in scaled.items()}
    remainder = 100 - sum(proposed.values())
    for key in sorted(scaled, key=lambda name: scaled[name] - proposed[name], reverse=True)[:remainder]:
        proposed[key] += 1
    return {
        "status": "stable" if sample_size >= 15 else "provisional",
        "sample_size": sample_size,
        "weights": proposed,
        "auto_applied": False,
    }


def build_learning_report(
    data: dict[str, Any], rules: dict[str, Any] | None = None
) -> dict[str, Any]:
    rules = rules or load_rules()
    records = validate_state(data, rules)
    initial = rules["scoring_rubric"]["initial_weights"]
    correlations: dict[str, dict[str, Any]] = {}
    hit_values = [1.0 if item["result"]["status"] == "的中" else 0.0 for item in records]
    return_values = [
        item["result"]["payout"] / item["result"]["stake"] for item in records
    ]
    for key in initial:
        scores = [float(item["score_breakdown"][key]) for item in records]
        correlations[key] = {
            "n": len(records),
            "hit_rate_correlation": _pearson(scores, hit_values),
            "return_rate_correlation": _pearson(scores, return_values),
            "performance_by_item_score": _group_performance(
                records, lambda item, score_key=key: item["score_breakdown"][score_key]
            ),
        }

    miss_reason: dict[str, dict[str, int]] = {
        reason: {"primary_count": 0, "secondary_count": 0, "loss_amount": 0}
        for reason in sorted(MISS_REASONS)
    }
    for item in records:
        result = item["result"]
        if result["status"] == "的中":
            continue
        primary = result["primary_miss_reason"]
        miss_reason[primary]["primary_count"] += 1
        miss_reason[primary]["loss_amount"] += result["stake"]
        for secondary in result["secondary_miss_reasons"]:
            miss_reason[secondary]["secondary_count"] += 1

    return {
        "version": 1,
        "initial_weights": dict(initial),
        "overall": _performance(records),
        "prediction_score_band_performance": _group_performance(
            records, lambda item: _score_band(item["prediction_score"])
        ),
        "low_quality_day_performance": _group_performance(
            records, lambda item: str(item["low_quality_day"]).lower()
        ),
        "miss_reason_summary": miss_reason,
        "scoring_item_relationships": correlations,
        "first_place_candidate_count_performance": _group_performance(
            records, lambda item: item["first_place_candidate_count"]
        ),
        "ticket_count_performance": _group_performance(
            records, lambda item: item["ticket_count"]
        ),
        "recommended_weights": _recommended_weights(initial, correlations, len(records)),
        "weights_auto_applied": False,
    }


def chatwork_request(method: str, url: str, token: str, body: dict[str, str] | None = None) -> Any:
    encoded = urllib.parse.urlencode(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers={"X-ChatWorkToken": token, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8")
            if response.status != 200:
                raise RuntimeError(f"Chatwork API HTTP {response.status}: {payload}")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Chatwork API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Chatwork APIへ接続できません: {exc.reason}") from exc


def send_chatwork(message: str, token: str, room_id: str) -> dict[str, Any]:
    base_url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    recent = chatwork_request("GET", f"{base_url}?force=1", token)
    if isinstance(recent, list) and any(item.get("body") == message for item in recent[-20:]):
        return {"skipped": True, "reason": "同一本文が直近メッセージに存在します"}
    response = chatwork_request("POST", base_url, token, {"body": message, "self_unread": "0"})
    if not isinstance(response, dict) or not response.get("message_id"):
        raise RuntimeError(f"Chatwork APIの成功応答にmessage_idがありません: {response}")
    return response


PREDICTION_STATE_FIELDS = (
    "number",
    "venue",
    "race",
    "target",
    "confidence",
    "prediction_score",
    "score_breakdown",
    "penalties",
    "first_place_candidate_count",
)


def default_state_path() -> Path:
    return Path(__file__).resolve().parents[1] / "state" / "state.json"


def load_state_for_update(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "days": []}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"既存のstate.jsonが壊れているため上書きしません: {path}") from exc
    except OSError as exc:
        raise ValidationError(f"state.jsonを読めません: {path}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("days"), list):
        raise ValidationError(f"既存のstate.jsonが正規形式ではないため上書きしません: {path}")
    return data


def save_state_atomic(path: Path, data: dict[str, Any]) -> None:
    validate_state(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    writing = path.with_name(path.name + ".writing")
    bak = path.with_name(path.name + ".bak")
    try:
        with writing.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        loaded = json.loads(writing.read_text(encoding="utf-8"))
        validate_state(loaded)
        if path.exists():
            shutil.copy2(path, bak)
        os.replace(writing, path)
    except Exception:
        if writing.exists():
            try:
                writing.unlink()
            except OSError:
                pass
        raise


def _prediction_state_record(raw: dict[str, Any], ticket_count: int, axis: str) -> dict[str, Any]:
    missing = [field for field in PREDICTION_STATE_FIELDS if field not in raw]
    if missing:
        raise ValidationError(f"予想の必須項目が不足しています: {', '.join(missing)}")
    record = {field: copy.deepcopy(raw[field]) for field in PREDICTION_STATE_FIELDS}
    record["venue"] = raw["venue"].strip()
    record["ticket_count"] = ticket_count
    record["axis"] = axis
    record["tickets"] = copy.deepcopy(raw["tickets"])
    record["result"] = None
    return record


def _candidate_state_record(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue": raw["venue"].strip(),
        "race": raw["race"],
        "close_time": raw["close_time"],
        "prediction_score": raw["prediction_score"],
        "score_breakdown": copy.deepcopy(raw["score_breakdown"]),
        "penalties": copy.deepcopy(raw["penalties"]),
        "selected": raw["selected"],
        "selection_rank": raw["selection_rank"],
    }


def _find_day(state: dict[str, Any], date: str) -> dict[str, Any] | None:
    for day in state.get("days", []):
        if day.get("date") == date:
            return day
    return None


def upsert_day(state: dict[str, Any], new_day: dict[str, Any]) -> None:
    days = state.setdefault("days", [])
    date = new_day["date"]
    for index, existing in enumerate(days):
        if existing.get("date") != date:
            continue
        preserved = {
            (pred.get("venue"), pred.get("race")): pred.get("result")
            for pred in existing.get("predictions", [])
            if pred.get("result") is not None
        }
        for pred in new_day["predictions"]:
            key = (pred["venue"], pred["race"])
            if key in preserved:
                pred["result"] = copy.deepcopy(preserved[key])
        days[index] = new_day
        return
    days.append(new_day)


def build_day_from_predictions(
    data: dict[str, Any], rules: dict[str, Any] | None = None
) -> dict[str, Any]:
    rules = rules or load_rules()
    rubric = rules["scoring_rubric"]
    weights = rubric["initial_weights"]
    penalty_codes = set(rubric["penalty_codes"])
    threshold = rubric["low_quality_day_threshold"]
    date = validate_date(data.get("date"))
    expanded = validate_predictions(data)
    candidates_raw = data.get("candidates")
    if not isinstance(candidates_raw, list) or len(candidates_raw) < RACE_COUNT:
        raise ValidationError("candidatesは3レース以上必要です")

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, int]] = set()
    for raw in candidates_raw:
        if not isinstance(raw, dict):
            raise ValidationError("candidateはオブジェクトが必要です")
        item = {
            "venue": raw.get("venue"),
            "race": raw.get("race"),
            "close_time": raw.get("close_time"),
            "prediction_score": raw.get("prediction_score"),
            "score_breakdown": copy.deepcopy(raw.get("score_breakdown")),
            "penalties": copy.deepcopy(raw.get("penalties")),
        }
        key = _race_key(item)
        if key in seen_keys:
            raise ValidationError(f"candidateが重複しています: {key}")
        seen_keys.add(key)
        item["close_time"] = validate_time(item.get("close_time"))
        if item["close_time"] < MIN_CLOSE_TIME:
            raise ValidationError("candidateは締切18:00以降が必要です")
        _validate_scored_item(item, weights, penalty_codes)
        if "selected" in raw:
            item["selected"] = raw["selected"]
        if "selection_rank" in raw:
            item["selection_rank"] = raw["selection_rank"]
        candidates.append(item)

    prediction_keys = {_race_key(raw): raw["number"] for raw in data["predictions"]}
    selected_items = [item for item in candidates if _race_key(item) in prediction_keys]
    if len(selected_items) != RACE_COUNT:
        raise ValidationError("predictionsはcandidates内のレースである必要があります")
    expected_low_quality = min(item["prediction_score"] for item in selected_items) < threshold
    if "low_quality_day" in data and data.get("low_quality_day") is not expected_low_quality:
        raise ValidationError(
            f"low_quality_dayは選定3Rの最低スコア{min(item['prediction_score'] for item in selected_items)}に対して{expected_low_quality}です"
        )
    for candidate in candidates:
        key = _race_key(candidate)
        if key in prediction_keys:
            expected_selected, expected_rank = True, prediction_keys[key]
        else:
            expected_selected, expected_rank = False, None
        if "selected" in candidate and candidate["selected"] is not expected_selected:
            raise ValidationError("selected/selection_rankはChatGPTが選んだ3レースと一致が必要です")
        if "selection_rank" in candidate and candidate.get("selection_rank") != expected_rank:
            raise ValidationError("selected/selection_rankはChatGPTが選んだ3レースと一致が必要です")
        candidate["selected"] = expected_selected
        candidate["selection_rank"] = expected_rank

    predictions: list[dict[str, Any]] = []
    for raw, tickets in zip(data["predictions"], expanded):
        key = _race_key(raw)
        if key not in prediction_keys:
            raise ValidationError("predictionsはcandidates内のレースである必要があります")
        candidate = next(item for item in candidates if _race_key(item) == key)
        _validate_scored_item(raw, weights, penalty_codes)
        for field in ("prediction_score", "score_breakdown", "penalties"):
            if raw.get(field) != candidate.get(field):
                raise ValidationError(f"predictionとcandidateの{field}が一致しません")
        first_count = raw.get("first_place_candidate_count")
        if first_count not in {1, 2}:
            raise ValidationError("1着候補数は1または2が必要です")
        ticket_count = sum(len(ticket.combinations) for ticket in tickets)
        if "ticket_count" in raw and raw["ticket_count"] != ticket_count:
            raise ValidationError("ticket_countが買い目点数と一致しません")
        axis = extract_axis(raw["tickets"])
        if "axis" in raw and raw["axis"] != axis:
            raise ValidationError("axisが本線先頭と一致しません")
        predictions.append(_prediction_state_record(raw, ticket_count, axis))

    return {
        "date": date,
        "low_quality_day": expected_low_quality,
        "candidates": [_candidate_state_record(item) for item in candidates],
        "predictions": predictions,
    }


def record_predictions(data: dict[str, Any], state_path: str | Path) -> dict[str, Any]:
    state_path = Path(state_path)
    day = build_day_from_predictions(data)
    state = load_state_for_update(state_path)
    upsert_day(state, day)
    validate_state(state)
    save_state_atomic(state_path, state)
    return {"date": day["date"], "races": RACE_COUNT, "path": str(state_path)}


def pull_state(
    state_path: str | Path,
    *,
    store: drive_state.DriveStateStore | None = None,
    file_id: str | None = None,
) -> dict[str, Any]:
    state_path = Path(state_path)
    resolved_id = drive_state.require_state_file_id(file_id)
    client = store if store is not None else drive_state.default_drive_store()
    drive_state.verify_state_file_metadata(client, resolved_id)
    raw = client.download(resolved_id)
    data = drive_state.parse_remote_state_bytes(raw)
    validate_state(data)
    save_state_atomic(state_path, data)
    return data


def push_state(
    state_path: str | Path,
    *,
    store: drive_state.DriveStateStore | None = None,
    file_id: str | None = None,
) -> dict[str, Any]:
    state_path = Path(state_path)
    resolved_id = drive_state.require_state_file_id(file_id)
    client = store if store is not None else drive_state.default_drive_store()
    drive_state.verify_state_file_metadata(client, resolved_id)
    local_data = load_state_for_update(state_path)
    validate_state(local_data)
    remote_raw = client.download(resolved_id)
    remote_data = drive_state.parse_remote_state_bytes(remote_raw)
    validate_state(remote_data)
    drive_state.guard_against_destructive_overwrite(local_data, remote_data)
    client.upload_replace(resolved_id, drive_state.encode_state_bytes(local_data))
    return {"path": str(state_path), "file_id_env": drive_state.FILE_ID_ENV}


def _require_drive_pair(from_drive: bool, to_drive: bool) -> None:
    if from_drive ^ to_drive:
        raise ValidationError(
            "record-predictions / record-results では --from-drive と --to-drive をセットで指定してください（または --drive）"
        )


def run_record_predictions(
    data: dict[str, Any],
    state_path: str | Path,
    *,
    from_drive: bool = False,
    to_drive: bool = False,
    drive_store: drive_state.DriveStateStore | None = None,
    drive_file_id: str | None = None,
    sheets_hook: Callable[..., Any] | None = None,
    chatwork_hook: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    _require_drive_pair(from_drive, to_drive)
    if from_drive:
        pull_state(state_path, store=drive_store, file_id=drive_file_id)
    result = record_predictions(data, state_path)
    if to_drive:
        push_state(state_path, store=drive_store, file_id=drive_file_id)
    if sheets_hook is not None:
        sheets_hook()
    if chatwork_hook is not None:
        chatwork_hook()
    return result


def run_record_results(
    data: dict[str, Any],
    state_path: str | Path,
    *,
    from_drive: bool = False,
    to_drive: bool = False,
    drive_store: drive_state.DriveStateStore | None = None,
    drive_file_id: str | None = None,
    sheets_hook: Callable[..., Any] | None = None,
    chatwork_hook: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    _require_drive_pair(from_drive, to_drive)
    if from_drive:
        pull_state(state_path, store=drive_store, file_id=drive_file_id)
    result = record_results(data, state_path)
    if to_drive:
        push_state(state_path, store=drive_store, file_id=drive_file_id)
    if sheets_hook is not None:
        sheets_hook()
    if chatwork_hook is not None:
        chatwork_hook()
    return result


def record_results(data: dict[str, Any], state_path: str | Path) -> dict[str, Any]:
    validate_results(data)
    state_path = Path(state_path)
    state = load_state_for_update(state_path)
    date = validate_date(data.get("date"))
    day = _find_day(state, date)
    if day is None:
        raise ValidationError(
            f"{date} の予想レコードがstateにありません。先にrecord-predictionsを実行してください。"
        )
    predictions = {item.get("number"): item for item in day.get("predictions", [])}
    for item in data["results"]:
        number = item["number"]
        pred = predictions.get(number)
        if pred is None:
            raise ValidationError(
                f"予想{number}がstateにありません。先にrecord-predictionsを実行してください。"
            )
        if item.get("venue") and str(item["venue"]).strip() != pred.get("venue"):
            raise ValidationError(f"予想{number}: venueがstateと一致しません")
        if item.get("race") is not None and item["race"] != pred.get("race"):
            raise ValidationError(f"予想{number}: raceがstateと一致しません")
        tickets = pred.get("tickets")
        axis = pred.get("axis")
        if not tickets or not axis:
            raise ValidationError(f"予想{number}: axis/ticketsが無いため結果を追記できません")
        if item["points"] != pred.get("ticket_count"):
            raise ValidationError(f"予想{number}: pointsがticket_countと一致しません")
        stake = item.get("stake", pred["ticket_count"] * 100)
        if not isinstance(stake, int) or stake <= 0:
            raise ValidationError(f"予想{number}: stakeは1以上の整数が必要です")
        status = item["status"]
        primary = item.get("primary_miss_reason")
        secondary = item.get("secondary_miss_reasons", [])
        if not isinstance(secondary, list) or len(secondary) != len(set(secondary)):
            raise ValidationError(f"予想{number}: secondary_miss_reasonsは重複のない配列が必要です")
        if status == "的中":
            if primary is not None or secondary:
                raise ValidationError(f"予想{number}: 的中時にmiss_reasonは保存しません")
        else:
            if primary not in MISS_REASONS:
                raise ValidationError(f"予想{number}: ハズレ時はprimary_miss_reasonが必要です")
            if primary in secondary or any(reason not in MISS_REASONS for reason in secondary):
                raise ValidationError(f"予想{number}: secondary_miss_reasonsが不正です")
        close_miss = compute_close_miss(
            status=status,
            axis=str(axis),
            tickets=tickets,
            trifecta=item["trifecta"],
        )
        if "close_miss" in item and item["close_miss"] is not close_miss:
            raise ValidationError(f"予想{number}: close_missの指定が自動判定と一致しません")
        pred["result"] = {
            "status": status,
            "stake": stake,
            "payout": item["payout"],
            "trifecta": item["trifecta"],
            "primary_miss_reason": None if status == "的中" else primary,
            "secondary_miss_reasons": [] if status == "的中" else list(secondary),
            "close_miss": close_miss,
        }
    validate_state(state)
    save_state_atomic(state_path, state)
    completed = [item for item in day["predictions"] if item.get("result")]
    return {"date": date, "completed": len(completed), "path": str(state_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "validate-predictions",
        "format-predictions",
        "validate-results",
        "format-results",
        "validate-state",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("json_file")
    learning = subparsers.add_parser("build-learning-report")
    learning.add_argument("json_file")
    learning.add_argument("--output", help="内部learning-reportの保存先")
    send = subparsers.add_parser("send-predictions")
    send.add_argument("json_file")
    send.add_argument(
        "--confirm-send",
        action="store_true",
        help="Chatworkへ実送信する明示確認。指定がなければ送信しない",
    )
    for name in ("record-predictions", "record-results"):
        command = subparsers.add_parser(name)
        command.add_argument("json_file")
        command.add_argument(
            "--state",
            dest="state_path",
            default=None,
            help="内部state.jsonの保存先。省略時は state/state.json",
        )
        command.add_argument(
            "--from-drive",
            action="store_true",
            help="開始時に KEIRIN_STATE_DRIVE_FILE_ID の既存ファイルを取得する",
        )
        command.add_argument(
            "--to-drive",
            action="store_true",
            help="upsert成功後に同じDriveファイルIDを上書きする（新規作成しない）",
        )
        command.add_argument(
            "--drive",
            action="store_true",
            help="--from-drive と --to-drive の両方（定期実行用）",
        )
    for name in ("pull-state", "push-state"):
        command = subparsers.add_parser(name)
        command.add_argument(
            "--state",
            dest="state_path",
            default=None,
            help="内部state.jsonの保存先。省略時は state/state.json",
        )
    prepare = subparsers.add_parser(
        "prepare-today",
        help="当日データを集め、候補5〜10RをChatGPT入力JSONにする。予想しない",
    )
    prepare.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は今日・JST）")
    prepare.add_argument("--races-file", type=Path, help="ネット無し検証用のレースJSON")
    ingest = subparsers.add_parser(
        "ingest-final",
        help="ChatGPT最終予想を取り込む。無ければ停止し、Cursorは予想しない",
    )
    ingest.add_argument("json_file", nargs="?", help="最終予想JSON。省略時は data/inbox/日付.final.json")
    ingest.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は今日・JST）")
    ingest.add_argument("--skip-sheets", action="store_true", help="シート転記をせずJSONとガードだけ検証")
    ingest.add_argument(
        "--confirm-send",
        action="store_true",
        help="再読一致後にChatworkへ送る。無いときは送らない",
    )
    results_cmd = subparsers.add_parser(
        "results-yesterday",
        help="公式結果を取り、既存シートの結果欄・集計欄だけ更新し学習JSONへ保存",
    )
    results_cmd.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は昨日・JST）")
    results_cmd.add_argument("--results-file", type=Path, help="ネット無し検証用の結果JSON")
    results_cmd.add_argument("--skip-sheets", action="store_true", help="シート更新をせず学習JSONだけ")
    today = subparsers.add_parser(
        "predict-today",
        help="互換用。収集と候補抽出だけ行い、最終予想が無ければ停止する",
    )
    today.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は今日・JST）")
    today.add_argument("--races-file", type=Path, help="ネット無し検証用のレースJSON")
    today.add_argument("json_file", nargs="?", help="あればChatGPT最終予想として取り込む")
    today.add_argument("--skip-sheets", action="store_true")
    today.add_argument("--confirm-send", action="store_true")
    return parser


def _resolve_record_drive_flags(args: argparse.Namespace) -> tuple[bool, bool]:
    from_drive = bool(getattr(args, "from_drive", False) or getattr(args, "drive", False))
    to_drive = bool(getattr(args, "to_drive", False) or getattr(args, "drive", False))
    return from_drive, to_drive


def _resolve_state_path_for_record(args: argparse.Namespace) -> Path:
    from_drive, to_drive = _resolve_record_drive_flags(args)
    if args.state_path:
        return Path(args.state_path)
    if from_drive and to_drive:
        return default_state_path()
    raise ValidationError(
        "定期実行では --from-drive --to-drive（または --drive）が必要です。"
        "ローカル検証は --state で一時ファイルを指定してください。"
    )


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_cursor_command(args: argparse.Namespace) -> str:
    import keirin_cursor_flow as flow
    from keirin_jst import today_str, yesterday_str

    root = _root()
    if args.command == "prepare-today":
        return flow.prepare_today(
            root,
            args.date,
            races_file=getattr(args, "races_file", None),
        )
    if args.command == "ingest-final":
        final_file = Path(args.json_file) if getattr(args, "json_file", None) else None
        send_fn = None
        if args.confirm_send:
            def send_fn(data: dict[str, Any]) -> Any:
                message = format_predictions(data)
                token = os.environ.get("CHATWORK_API_TOKEN")
                room_id = os.environ.get("CHATWORK_ROOM_ID")
                if not token or not room_id:
                    raise ValidationError("CHATWORK_API_TOKENとCHATWORK_ROOM_IDが必要です")
                return send_chatwork(message, token, room_id)

        return flow.ingest_final(
            root,
            args.date,
            final_file=final_file,
            write_sheets=not args.skip_sheets,
            confirm_send=args.confirm_send,
            send_fn=send_fn,
        )
    if args.command == "results-yesterday":
        return flow.process_results(
            root,
            args.date or yesterday_str(),
            results_file=getattr(args, "results_file", None),
            write_sheets=not args.skip_sheets,
        )
    if args.command == "predict-today":
        return flow.run_today_or_stop(
            root,
            args.date or today_str(),
            races_file=getattr(args, "races_file", None),
            final_file=Path(args.json_file) if getattr(args, "json_file", None) else None,
            write_sheets=not getattr(args, "skip_sheets", False),
            confirm_send=bool(getattr(args, "confirm_send", False)),
        )
    raise ValidationError(f"未対応のコマンドです: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"prepare-today", "ingest-final", "results-yesterday", "predict-today"}:
            print(_run_cursor_command(args))
            return 0
        if args.command == "pull-state":
            state_path = Path(args.state_path) if args.state_path else default_state_path()
            pull_state(state_path)
            print(f"OK: Driveからstateを取得しました: {state_path}")
            return 0
        if args.command == "push-state":
            state_path = Path(args.state_path) if args.state_path else default_state_path()
            push_state(state_path)
            print(f"OK: 同じDriveファイルIDへstateを上書きしました: {state_path}")
            return 0
        data = load_json(args.json_file)
        if args.command == "validate-predictions":
            expanded = validate_predictions(data)
            counts = [sum(len(ticket.combinations) for ticket in group) for group in expanded]
            print(f"OK: 3レース、点数={counts}、各10点以内、締切18:00以降")
        elif args.command == "format-predictions":
            print(format_predictions(data))
        elif args.command == "validate-results":
            validate_results(data)
            print("OK: 3レース分の結果形式を確認しました")
        elif args.command == "format-results":
            print(format_results(data))
        elif args.command == "validate-state":
            completed = validate_state(data)
            print(f"OK: 内部stateを確認しました（結果確定{len(completed)}レース）")
        elif args.command == "build-learning-report":
            report = build_learning_report(data)
            rendered = json.dumps(report, ensure_ascii=False, indent=2)
            if args.output:
                output = Path(args.output)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(rendered + "\n", encoding="utf-8")
                print(f"OK: learning-reportを{output}へ保存しました")
            else:
                print(rendered)
        elif args.command == "send-predictions":
            message = format_predictions(data)
            if not args.confirm_send:
                raise ValidationError("実送信には--confirm-sendが必要です")
            token = os.environ.get("CHATWORK_API_TOKEN")
            room_id = os.environ.get("CHATWORK_ROOM_ID")
            if not token or not room_id:
                raise ValidationError("CHATWORK_API_TOKENとCHATWORK_ROOM_IDが必要です")
            result = send_chatwork(message, token, room_id)
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "record-predictions":
            state_path = _resolve_state_path_for_record(args)
            from_drive, to_drive = _resolve_record_drive_flags(args)
            result = run_record_predictions(
                data,
                state_path,
                from_drive=from_drive,
                to_drive=to_drive,
            )
            print(
                f"OK: {result['date']} の予想{result['races']}レースをstateへ保存しました: {result['path']}"
            )
        elif args.command == "record-results":
            state_path = _resolve_state_path_for_record(args)
            from_drive, to_drive = _resolve_record_drive_flags(args)
            result = run_record_results(
                data,
                state_path,
                from_drive=from_drive,
                to_drive=to_drive,
            )
            print(
                f"OK: {result['date']} の結果を{result['completed']}レース分追記しました: {result['path']}"
            )
        return 0
    except (
        ValidationError,
        RuntimeError,
        OSError,
        json.JSONDecodeError,
        drive_state.DriveStateError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
