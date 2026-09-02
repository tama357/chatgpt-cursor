"""ChatGPT入力JSONと最終予想JSONのスキーマ。Cursorは最終予想を作らない。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keirin_jst import today_str

SCHEMA_VERSION = 1
INPUT_ROLE = "chatgpt_input"
FINAL_ROLE = "chatgpt_final"
REQUIRED_FINAL_FIELDS = (
    "number",
    "venue",
    "race",
    "close_time",
    "target",
    "confidence",
    "tickets",
    "ticket_count",
    "explanation",
)
ALLOWED_TARGETS = {"鉄板", "中穴", "大穴"}
ALLOWED_CONFIDENCE = {"A", "B", "C"}


class SchemaError(ValueError):
    pass


def data_dir(root: Path) -> Path:
    return root / "data" / "inbox"


def chatgpt_input_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"{date}.chatgpt_input.json"


def chatgpt_final_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"{date}.final.json"


def predictions_inbox_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"{date}.predictions.json"


def results_inbox_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"{date}.results.json"


def learning_inbox_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"{date}.learning.json"


def save_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if loaded != payload:
        raise SchemaError(f"再読不一致: {path}")
    return path


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SchemaError("JSONの最上位はオブジェクトにしてください")
    return data


def build_chatgpt_input(
    *,
    date: str,
    candidates: list[dict[str, Any]],
    skipped: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = rules or {}
    items = [_candidate_for_chatgpt(item, index) for index, item in enumerate(candidates, start=1)]
    return {
        "schema_version": SCHEMA_VERSION,
        "role": INPUT_ROLE,
        "date": date,
        "timezone": "Asia/Tokyo",
        "cursor_role": "data_collection_only",
        "chatgpt_role": "final_prediction",
        "rules": {
            "final_race_count": 3,
            "minimum_close_time": rules.get("minimum_close_time") or "18:00",
            "max_combinations_per_race": rules.get("max_combinations_per_race") or 10,
            "bet_type": "trifecta",
            "notation": "4-2-1357（カッコ・カンマ・全角数字は使わない）",
            "targets": ["鉄板", "中穴", "大穴"],
            "confidence": ["A", "B", "C"],
        },
        "notes": (
            "これは候補レースのデータです。Cursorは最終3Rも買い目も決めていません。"
            "ChatGPTはこのJSONだけを見て、選定3レース・狙い・confidence・本線・抑え・合計点数・解説を返してください。"
        ),
        "candidates": items,
        "skipped_count": len(skipped or []),
    }


def _candidate_for_chatgpt(item: dict[str, Any], extract_rank: int) -> dict[str, Any]:
    venue = str(item.get("venue") or "").strip()
    race_number = int(item.get("race_number") or item.get("race") or 0)
    deadline = str(item.get("deadline") or item.get("close_time") or "")
    riders = item.get("riders") or item.get("entries") or []
    return {
        "extract_rank": extract_rank,
        "race": f"{venue}{race_number}R",
        "venue": venue,
        "race_number": race_number,
        "deadline": deadline,
        "close_time": deadline,
        "class_name": item.get("class_name"),
        "prediction_score": item.get("prediction_score"),
        "score_breakdown": item.get("score_breakdown"),
        "penalties": item.get("penalties"),
        "riders": riders,
        "score": [
            {"number": rider.get("number"), "name": rider.get("name"), "score": rider.get("score")}
            for rider in riders
            if isinstance(rider, dict)
        ],
        "recent_results": [
            {"number": rider.get("number"), "recent_results": rider.get("recent_results")}
            for rider in riders
            if isinstance(rider, dict)
        ],
        "line": item.get("line"),
        "winning_style": item.get("winning_style"),
        "B_count": item.get("B_count"),
        "current_meeting_results": item.get("current_meeting_results"),
        "previous_meeting_results": item.get("previous_meeting_results"),
        "odds": item.get("odds"),
        "risk_factors": item.get("risk_factors") or [],
        "source": item.get("source") or "keirin.jp",
        "fetched_data": item.get("fetched_data") or {},
    }


def missing_final_prediction_fields(data: dict[str, Any] | None) -> list[str]:
    if not data or not isinstance(data, dict):
        return ["最終予想JSON自体が無い"]
    missing: list[str] = []
    if data.get("date") is None:
        missing.append("date")
    predictions = data.get("predictions")
    if not isinstance(predictions, list) or len(predictions) != 3:
        missing.append("選定3レース")
        return missing
    for index, pred in enumerate(predictions, start=1):
        if not isinstance(pred, dict):
            missing.append(f"予想{index}がオブジェクトではない")
            continue
        for field in REQUIRED_FINAL_FIELDS:
            if field == "tickets":
                continue
            if pred.get(field) in (None, ""):
                missing.append(f"予想{index}.{field}")
        tickets = pred.get("tickets")
        if not isinstance(tickets, list):
            missing.append(f"予想{index}.tickets")
            continue
        if not any(isinstance(t, dict) and t.get("type") == "本線" and t.get("pick") for t in tickets):
            missing.append(f"予想{index}.本線")
        if not any(isinstance(t, dict) and t.get("type") == "抑え" for t in tickets):
            missing.append(f"予想{index}.抑え")
        if pred.get("target") not in ALLOWED_TARGETS:
            missing.append(f"予想{index}.狙い")
        if pred.get("confidence") not in ALLOWED_CONFIDENCE:
            missing.append(f"予想{index}.confidence")
        if not isinstance(pred.get("ticket_count"), int):
            missing.append(f"予想{index}.合計点数")
    return missing


def require_chatgpt_final(data: dict[str, Any] | None) -> dict[str, Any]:
    missing = missing_final_prediction_fields(data)
    if missing:
        raise SchemaError(
            "ChatGPTの最終予想が揃っていないため、提出処理を停止します。"
            "Cursorは代わりに予想しません。欠けている項目: "
            + "、".join(missing)
        )
    assert data is not None
    return data


def find_final_prediction(
    root: Path,
    date: str,
    *,
    json_file: Path | None = None,
) -> dict[str, Any] | None:
    path = json_file or chatgpt_final_path(root, date)
    if not path.exists():
        return None
    return load_json(path)


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_date(value: str | None) -> str:
    return value or today_str()
