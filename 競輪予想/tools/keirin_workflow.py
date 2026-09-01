#!/usr/bin/env python3
"""競輪予想の形式検証、Chatwork本文生成、明示確認付き送信。"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


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

        ranked = sorted(
            candidates,
            key=lambda item: (
                -item["prediction_score"],
                -item["score_breakdown"]["axis_reliability"],
                -item["score_breakdown"]["scenario_simplicity"],
                -item["score_breakdown"]["recent_form"],
                item["venue"],
                item["race"],
            ),
        )
        top_three = ranked[:RACE_COUNT]
        top_keys = {_race_key(item) for item in top_three}
        expected_low_quality = top_three[-1]["prediction_score"] < threshold
        if day.get("low_quality_day") is not expected_low_quality:
            raise ValidationError(
                f"内部state: low_quality_dayは3位スコア{top_three[-1]['prediction_score']}に対して{expected_low_quality}です"
            )
        for rank, candidate in enumerate(top_three, start=1):
            if candidate.get("selected") is not True or candidate.get("selection_rank") != rank:
                raise ValidationError("内部state: 上位3候補のselected/selection_rankが不正です")
        for candidate in ranked[RACE_COUNT:]:
            if candidate.get("selected") is not False or candidate.get("selection_rank") is not None:
                raise ValidationError("内部state: 4位以下の候補をselectedにできません")

        prediction_keys: set[tuple[str, int]] = set()
        numbers: set[int] = set()
        for prediction in predictions:
            if not isinstance(prediction, dict):
                raise ValidationError("内部state: predictionはオブジェクトが必要です")
            number = prediction.get("number")
            if number not in {1, 2, 3} or number in numbers:
                raise ValidationError("内部state: prediction.numberは重複なしの1〜3が必要です")
            numbers.add(number)
            key = _race_key(prediction)
            if key not in top_keys or key in prediction_keys:
                raise ValidationError("内部state: predictionsはcandidates上位3レースと一致が必要です")
            prediction_keys.add(key)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
        return 0
    except (ValidationError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
