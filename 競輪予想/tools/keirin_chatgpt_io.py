"""ChatGPT入力JSONと最終予想JSONのスキーマ。Cursorは第一予想まで。最終はChatGPT。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from keirin_jst import now_jst, today_str

SCHEMA_VERSION = 1
INPUT_ROLE = "chatgpt_input"
FINAL_ROLE = "chatgpt_final"
STATUS_READY = "ready"
STATUS_INCOMPLETE = "incomplete"
MIN_READY_CANDIDATES = 3
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

# 予想判断に必須。欠けている間は正式名へ切り替えない。
CRITICAL_INPUT_TOP_FIELDS = ("date",)
CRITICAL_CANDIDATE_FIELDS = (
    "race",
    "venue",
    "race_number",
    "deadline",
    "riders",
)


class SchemaError(ValueError):
    pass


def data_dir(root: Path) -> Path:
    return root / "data" / "inbox"


def chatgpt_input_path(root: Path, date: str) -> Path:
    """完成済み入力。この正式名があるときだけChatGPTが処理してよい。"""
    return data_dir(root) / f"prediction_input_{date}.json"


def chatgpt_input_tmp_path(root: Path, date: str) -> Path:
    """作成途中。ChatGPT入力としては未完成。"""
    return data_dir(root) / f"prediction_input_{date}.tmp.json"


def chatgpt_input_legacy_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"{date}.chatgpt_input.json"


def chatgpt_final_path(root: Path, date: str) -> Path:
    return data_dir(root) / f"prediction_final_{date}.json"


def chatgpt_final_legacy_path(root: Path, date: str) -> Path:
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


def _now_iso() -> str:
    return now_jst().isoformat(timespec="seconds")


def _candidate_race_number(item: dict[str, Any]) -> int:
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


def _candidate_deadline(item: dict[str, Any]) -> str:
    return str(item.get("deadline") or item.get("close_time") or "").strip()


def _riders_have_numbers(riders: Any) -> bool:
    if not isinstance(riders, list) or not riders:
        return False
    return any(isinstance(rider, dict) and rider.get("number") not in (None, "") for rider in riders)


def collect_missing_input_fields(payload: dict[str, Any]) -> list[str]:
    """予想判断に必須の欠損。ここが空のときだけ status=ready にする。"""
    missing: list[str] = []
    if not str(payload.get("date") or "").strip():
        missing.append("date")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < MIN_READY_CANDIDATES:
        missing.append(f"candidates（{MIN_READY_CANDIDATES}レース以上必要）")
    if not isinstance(candidates, list):
        return missing
    for index, item in enumerate(candidates, start=1):
        prefix = f"候補{index}"
        if not isinstance(item, dict):
            missing.append(f"{prefix}がオブジェクトではない")
            continue
        venue = str(item.get("venue") or "").strip()
        if not venue:
            missing.append(f"{prefix}.venue")
        race_number = _candidate_race_number(item)
        if race_number <= 0:
            missing.append(f"{prefix}.race_number")
        race_label = item.get("race")
        has_race_label = isinstance(race_label, str) and bool(race_label.strip())
        if not has_race_label and not (venue and race_number > 0):
            missing.append(f"{prefix}.race")
        if not _candidate_deadline(item):
            missing.append(f"{prefix}.deadline")
        riders = item.get("riders") or item.get("entries")
        if not _riders_have_numbers(riders):
            missing.append(f"{prefix}.riders")
    return missing


def _infer_source_updated_at(payload: dict[str, Any]) -> str | None:
    stamps: list[str] = []
    top = payload.get("source_updated_at")
    if isinstance(top, str) and top.strip():
        stamps.append(top.strip())
    for item in payload.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        fetched = item.get("fetched_data") or {}
        for key in ("updated_at", "source_updated_at", "fetched_at"):
            value = fetched.get(key) if isinstance(fetched, dict) else None
            if isinstance(value, str) and value.strip():
                stamps.append(value.strip())
        value = item.get("source_updated_at")
        if isinstance(value, str) and value.strip():
            stamps.append(value.strip())
    if not stamps:
        return None
    return max(stamps)


def apply_input_status(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
    source_updated_at: str | None = None,
) -> dict[str, Any]:
    missing = collect_missing_input_fields(payload)
    complete = not missing
    generated = generated_at or payload.get("generated_at") or _now_iso()
    payload["date"] = payload.get("date")
    payload["generated_at"] = generated
    payload["candidate_count"] = len(payload.get("candidates") or []) if isinstance(payload.get("candidates"), list) else 0
    payload["missing_fields"] = missing
    payload["data_complete"] = complete
    payload["status"] = STATUS_READY if complete else STATUS_INCOMPLETE
    payload["source_updated_at"] = (
        source_updated_at or _infer_source_updated_at(payload) or generated
    )
    return payload


def is_input_ready_payload(payload: dict[str, Any] | None) -> bool:
    if not payload or not isinstance(payload, dict):
        return False
    return payload.get("status") == STATUS_READY and payload.get("data_complete") is True


def is_chatgpt_input_ready(root: Path, date: str) -> bool:
    """正式名があり、中身が ready のときだけ ChatGPT 処理可能。tmp だけでは未完成。"""
    formal = chatgpt_input_path(root, date)
    if not formal.is_file():
        return False
    try:
        return is_input_ready_payload(load_json(formal))
    except (OSError, json.JSONDecodeError, SchemaError):
        return False


def chatgpt_input_readiness_message(root: Path, date: str) -> str:
    formal = chatgpt_input_path(root, date)
    tmp = chatgpt_input_tmp_path(root, date)
    if is_chatgpt_input_ready(root, date):
        return f"ChatGPT処理可能: {formal.name}"
    if tmp.is_file() and not formal.is_file():
        return f"未完成（一時ファイルのみ）: {tmp.name}。ChatGPTには渡さないでください。"
    if formal.is_file():
        return f"正式名はありますが未完成です: {formal.name}。ChatGPTには渡さないでください。"
    return "入力JSONがありません。"


def write_chatgpt_input(root: Path, payload: dict[str, Any]) -> Path:
    """一時ファイルへ書いて検証し、完成時だけ正式名へ原子的に切り替える。"""
    apply_input_status(payload)
    date = str(payload.get("date") or "").strip()
    if not date:
        raise SchemaError("入力JSONにdateが無いため保存できません")
    tmp = chatgpt_input_tmp_path(root, date)
    formal = chatgpt_input_path(root, date)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if formal.exists() and tmp.exists() and formal.samefile(tmp):
        raise SchemaError("一時ファイルと正式名が同じパスです")
    save_json(tmp, payload)
    loaded = load_json(tmp)
    if loaded != payload:
        raise SchemaError(f"一時ファイルの再読不一致: {tmp}")
    ready = is_input_ready_payload(loaded)
    if not ready:
        if formal.exists():
            formal.unlink()
        return tmp
    os.replace(tmp, formal)
    if not formal.is_file():
        raise SchemaError(f"正式名への切り替えに失敗しました: {formal}")
    return formal


def load_ready_chatgpt_input(root: Path, date: str) -> dict[str, Any] | None:
    if not is_chatgpt_input_ready(root, date):
        return None
    return load_json(chatgpt_input_path(root, date))


def load_chatgpt_input_for_validation(root: Path, date: str) -> dict[str, Any] | None:
    """車番確認用。正式名だけを使う。tmp は未完成なので使わない。"""
    formal = chatgpt_input_path(root, date)
    if formal.is_file():
        return load_json(formal)
    return None


def build_chatgpt_input(
    *,
    date: str,
    candidates: list[dict[str, Any]],
    skipped: list[dict[str, Any]] | None = None,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = rules or {}
    items = [_candidate_for_chatgpt(item, index) for index, item in enumerate(candidates, start=1)]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "role": INPUT_ROLE,
        "date": date,
        "timezone": "Asia/Tokyo",
        "cursor_role": "data_and_first_prediction",
        "chatgpt_role": "final_review_sheet_chatwork",
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
            "候補全体とCursor第一予想です。第一予想は最終ではありません。"
            "ChatGPTは候補全体を再確認し、レース選定・軸・買い目を変更できます。"
            "ファイル名が prediction_input_日付.json で status が ready のときだけ処理してください。"
            "prediction_input_日付.tmp.json は作成途中なので読まないでください。"
            "最終確認後に prediction_final_日付.json を書き、シート転記とChatwork送信もChatGPT側で行います。"
        ),
        "candidates": items,
        "cursor_first_prediction": _first_prediction_for_input(items, rules),
        "skipped_count": len(skipped or []),
    }
    return apply_input_status(payload)


def _first_prediction_for_input(
    candidates: list[dict[str, Any]],
    rules: dict[str, Any],
) -> dict[str, Any]:
    from keirin_first_prediction import build_cursor_first_prediction

    return build_cursor_first_prediction(candidates, rules)


def _candidate_for_chatgpt(item: dict[str, Any], extract_rank: int) -> dict[str, Any]:
    venue = str(item.get("venue") or "").strip()
    race_number = _candidate_race_number(item)
    deadline = _candidate_deadline(item)
    riders = item.get("riders") or item.get("entries") or []
    return {
        "extract_rank": extract_rank,
        "race": f"{venue}{race_number}R" if venue and race_number else (item.get("race") or ""),
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


def _pick_car_numbers(pick: str) -> set[str]:
    parts = pick.split("-")
    used: set[str] = set()
    if len(parts) >= 1 and parts[0]:
        used.add(parts[0])
    if len(parts) >= 2 and parts[1]:
        used.add(parts[1])
    if len(parts) >= 3:
        used.update(ch for ch in parts[2] if ch.isdigit())
    return used


def _candidate_rider_numbers(item: dict[str, Any]) -> set[str]:
    riders = item.get("riders") or item.get("entries") or []
    numbers: set[str] = set()
    if not isinstance(riders, list):
        return numbers
    for rider in riders:
        if isinstance(rider, dict) and rider.get("number") not in (None, ""):
            numbers.add(str(rider.get("number")))
    return numbers


def _candidate_lookup(candidates: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        venue = str(item.get("venue") or "").strip()
        out[(venue, _candidate_race_number(item))] = item
    return out


def validate_chatgpt_final_mechanically(
    data: dict[str, Any],
    *,
    expected_date: str,
    input_data: dict[str, Any] | None = None,
) -> None:
    """機械的検証のみ。レース・軸・買い目・点数・解説は直さない。"""
    from keirin_workflow import (
        MAX_COMBINATIONS,
        MIN_CLOSE_TIME,
        RACE_COUNT,
        ValidationError,
        expand_pick,
        validate_date,
        validate_predictions,
        validate_time,
    )

    errors: list[str] = []
    try:
        actual_date = validate_date(data.get("date"))
    except ValidationError:
        errors.append(f"対象日の形式が不正です: {data.get('date')}")
        actual_date = None
    if actual_date is not None and actual_date != expected_date:
        errors.append(f"対象日が一致しません（JSON={actual_date} / 対象={expected_date}）")

    predictions = data.get("predictions")
    if isinstance(predictions, list) and len(predictions) > RACE_COUNT:
        errors.append(f"選定レースが{len(predictions)}件あります。3R以内にしてください")

    try:
        validate_predictions(data)
    except ValidationError as exc:
        errors.append(str(exc))

    lookup = _candidate_lookup(list((input_data or {}).get("candidates") or []))
    if isinstance(predictions, list):
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            number = pred.get("number")
            label = f"予想{number}" if number is not None else "予想"
            close_time = pred.get("close_time")
            try:
                normalized = validate_time(close_time)
                if normalized < MIN_CLOSE_TIME:
                    errors.append(f"{label}: 締切時刻は18:00以降が必要です（{close_time}）")
            except ValidationError:
                errors.append(f"{label}: 締切時刻の形式が不正です: {close_time}")

            tickets = pred.get("tickets") if isinstance(pred.get("tickets"), list) else []
            total = 0
            expanded_ok = True
            for ticket in tickets:
                pick = ticket.get("pick") if isinstance(ticket, dict) else None
                if not isinstance(pick, str):
                    continue
                try:
                    total += len(expand_pick(pick))
                except ValidationError as exc:
                    expanded_ok = False
                    errors.append(f"{label}: {exc}")
            if expanded_ok and pred.get("ticket_count") != total:
                errors.append(
                    f"{label}: 展開後の点数が記載点数と一致しません"
                    f"（記載={pred.get('ticket_count')} / 展開={total}）。修正せず停止します。"
                )
            if total > MAX_COMBINATIONS:
                errors.append(f"{label}: {total}点です。上限{MAX_COMBINATIONS}点を超えています")

            venue = str(pred.get("venue") or "").strip()
            try:
                race_no = int(pred.get("race"))
            except (TypeError, ValueError):
                race_no = 0
            if input_data is None:
                errors.append(f"{label}: 完成済みの候補JSONが無いため車番の実在を確認できません")
            else:
                candidate = lookup.get((venue, race_no))
                if candidate is None:
                    errors.append(f"{label}: {venue}{race_no}R は候補JSONにありません")
                else:
                    numbers = _candidate_rider_numbers(candidate)
                    if not numbers:
                        errors.append(f"{label}: 候補に出走選手が無いため車番の実在を確認できません")
                    else:
                        used: set[str] = set()
                        for ticket in tickets:
                            pick = ticket.get("pick") if isinstance(ticket, dict) else None
                            if isinstance(pick, str):
                                used.update(_pick_car_numbers(pick))
                        unknown = sorted(num for num in used if num not in numbers)
                        if unknown:
                            errors.append(
                                f"{label}: 実在しない車番があります: {', '.join(unknown)}"
                                f"（出走={', '.join(sorted(numbers, key=lambda n: int(n) if n.isdigit() else n))}）"
                            )

    if errors:
        # 重複メッセージを除き、検証で直さない
        unique: list[str] = []
        for item in errors:
            if item not in unique:
                unique.append(item)
        raise ValidationError(
            "最終予想の検証に失敗したため停止します。Cursorは内容を補正しません。\n"
            + "\n".join(f"- {item}" for item in unique)
        )


def find_final_prediction(
    root: Path,
    date: str,
    *,
    json_file: Path | None = None,
) -> dict[str, Any] | None:
    if json_file is not None:
        if not json_file.exists():
            return None
        return load_json(json_file)
    for path in (chatgpt_final_path(root, date), chatgpt_final_legacy_path(root, date)):
        if path.exists():
            return load_json(path)
    return None


def default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_date(value: str | None) -> str:
    return value or today_str()
