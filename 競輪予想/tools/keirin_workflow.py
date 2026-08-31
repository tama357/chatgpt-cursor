#!/usr/bin/env python3
"""競輪予想の形式検証、Chatwork本文生成、明示確認付き送信。"""

from __future__ import annotations

import argparse
import json
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
    for name in ("validate-predictions", "format-predictions", "validate-results", "format-results"):
        command = subparsers.add_parser(name)
        command.add_argument("json_file")
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

