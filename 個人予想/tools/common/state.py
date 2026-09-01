from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import ALLOWED_CONFIDENCE, ALLOWED_STATUS, ALLOWED_TARGETS, MISS_REASONS
from .tickets import ValidationError, count_tickets, expand_tickets


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 2, "sport": "", "records": [], "processed": {}}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValidationError("state JSONの最上位はオブジェクトにしてください")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def is_processed(state: dict[str, Any], key: str, payload: dict[str, Any]) -> bool:
    processed = state.setdefault("processed", {})
    entry = processed.get(key)
    if not entry:
        return False
    return entry.get("hash") == _hash_payload(payload)


def mark_processed(state: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
    state.setdefault("processed", {})[key] = {
        "hash": _hash_payload(payload),
        "at": datetime.now().isoformat(timespec="seconds"),
    }


def validate_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError("dateはYYYY-MM-DD形式の文字列が必要です")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError("dateはYYYY-MM-DD形式にしてください") from exc
    return value


def validate_prediction_record(record: dict[str, Any], rules: dict[str, Any]) -> None:
    validate_date(record.get("date"))
    if record.get("sport") != rules["sport"]:
        raise ValidationError("sportが設定と一致しません")
    if record.get("target") not in ALLOWED_TARGETS:
        raise ValidationError("狙いが不正です")
    if record.get("confidence") not in ALLOWED_CONFIDENCE:
        raise ValidationError("自信度が不正です")
    score = record.get("prediction_score")
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise ValidationError("prediction_scoreは0〜100の整数が必要です")
    tickets = record.get("tickets")
    if not isinstance(tickets, list) or not tickets:
        raise ValidationError("買い目が必要です")
    max_pts = rules["max_combinations_per_race"]
    min_pts = rules.get("min_combinations_per_race", 1)
    total = count_tickets(tickets)
    if total > max_pts:
        raise ValidationError(f"買い目は{max_pts}点以内にしてください")
    record["ticket_count"] = total
    expand_tickets(tickets)


def validate_result_record(record: dict[str, Any]) -> None:
    result = record.get("result")
    if not isinstance(result, dict):
        raise ValidationError("resultが必要です")
    status = result.get("status")
    if status not in ALLOWED_STATUS:
        raise ValidationError("statusは的中・ハズレ・未実施です")
    stake = result.get("stake")
    payout = result.get("payout")
    if not isinstance(stake, int) or stake <= 0:
        raise ValidationError("stakeは1以上の整数が必要です")
    if not isinstance(payout, int) or payout < 0:
        raise ValidationError("payoutは0以上の整数が必要です")
    if status == "ハズレ" and payout != 0:
        raise ValidationError("ハズレ時のpayoutは0です")
    if status == "的中" and payout <= 0:
        raise ValidationError("的中時のpayoutが必要です")
    primary = result.get("primary_miss_reason")
    secondary = result.get("secondary_miss_reasons", [])
    if status == "的中":
        if primary or secondary:
            raise ValidationError("的中時にmiss_reasonは保存しません")
    elif status == "ハズレ":
        if primary not in MISS_REASONS:
            raise ValidationError("ハズレ時はprimary_miss_reasonが必要です")
        if not isinstance(secondary, list):
            raise ValidationError("secondary_miss_reasonsは配列が必要です")
        if primary in secondary or any(r not in MISS_REASONS for r in secondary):
            raise ValidationError("secondary_miss_reasonsが不正です")
    review = record.get("review")
    if not isinstance(review, dict):
        raise ValidationError("reviewが必要です")


def upsert_record(state: dict[str, Any], record: dict[str, Any]) -> None:
    records: list[dict[str, Any]] = state.setdefault("records", [])
    key = (record["date"], record.get("venue"), record.get("race"))
    for index, existing in enumerate(records):
        if (existing["date"], existing.get("venue"), existing.get("race")) == key:
            records[index] = record
            return
    records.append(record)


def get_records(
    state: dict[str, Any],
    *,
    with_result: bool | None = None,
) -> list[dict[str, Any]]:
    records = state.get("records", [])
    if with_result is True:
        return [r for r in records if r.get("result")]
    if with_result is False:
        return [r for r in records if not r.get("result")]
    return list(records)


def find_day_records(state: dict[str, Any], date: str) -> list[dict[str, Any]]:
    return [r for r in state.get("records", []) if r["date"] == date]
