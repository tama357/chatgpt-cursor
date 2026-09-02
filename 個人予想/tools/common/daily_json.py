"""日次学習JSON（inbox正本）。正規stateは日次ジョブから書かない。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import (
    COMPLETED_RESULT_STATUSES,
    DAILY_JSON_SCHEMA_VERSION,
    DAY_STATUS_FETCH_FAILED,
    DAY_STATUS_NO_MEETING,
    DAY_STATUS_PREDICTED,
    DEFAULT_START_DATE,
    STATE_TIMEZONE,
)
from .state import validate_date
from .tickets import ValidationError


def is_before_learning_start(date: str) -> bool:
    return validate_date(date) < DEFAULT_START_DATE


def inbox_local_dir(base_dir: Path, sport: str) -> Path:
    return base_dir / "data" / "inbox" / sport


def predictions_path(base_dir: Path, sport: str, date: str) -> Path:
    return inbox_local_dir(base_dir, sport) / f"{date}.predictions.json"


def results_path(base_dir: Path, sport: str, date: str) -> Path:
    return inbox_local_dir(base_dir, sport) / f"{date}.results.json"


def make_race_id(record: dict[str, Any]) -> str:
    sport = str(record.get("sport") or "")
    fetched = record.get("fetched_data") if isinstance(record.get("fetched_data"), dict) else {}
    official = fetched.get("race_id")
    if official:
        return f"{sport}:{official}"
    if sport == "kyotei" and fetched.get("jcd") and fetched.get("rno") and fetched.get("hd"):
        return f"kyotei:{fetched['hd']}:{fetched['jcd']}:{fetched['rno']}"
    date = record.get("date")
    venue = str(record.get("venue") or "").strip()
    race = record.get("race")
    return f"{sport}:{date}:{venue}:{race}"


def axis_from_tickets(tickets: Any) -> str | None:
    if not isinstance(tickets, list):
        return None
    for ticket in tickets:
        if not isinstance(ticket, dict) or ticket.get("type") != "本線":
            continue
        pick = ticket.get("pick")
        if isinstance(pick, str) and "-" in pick:
            axis = pick.split("-", 1)[0]
            if axis:
                return axis
    return None


def is_completed_race(race: dict[str, Any]) -> bool:
    if race.get("skipped"):
        return False
    status = race.get("status")
    result = race.get("result")
    if isinstance(result, dict):
        status = result.get("status", status)
    return status in COMPLETED_RESULT_STATUSES


def count_completed_races(races: list[dict[str, Any]] | None) -> int:
    return sum(1 for race in races or [] if is_completed_race(race))


def count_completed_from_inbox(base_dir: Path, sport: str) -> int:
    folder = inbox_local_dir(base_dir, sport)
    if not folder.exists():
        return 0
    total = 0
    for path in sorted(folder.glob("*.results.json")):
        try:
            data = load_daily_json(path)
        except (OSError, json.JSONDecodeError, ValidationError):
            continue
        total += count_completed_races(data.get("races") if isinstance(data.get("races"), list) else [])
    return total


def remaining_to_100(completed: int, *, threshold: int = 100) -> int:
    return max(0, threshold - completed)


def load_daily_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValidationError(f"{path.name}: JSONの最上位はオブジェクトにしてください")
    return data


def save_daily_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".writing")
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def load_predictions_doc(base_dir: Path, sport: str, date: str) -> dict[str, Any] | None:
    path = predictions_path(base_dir, sport, date)
    if not path.exists():
        return None
    return load_daily_json(path)


def load_results_doc(base_dir: Path, sport: str, date: str) -> dict[str, Any] | None:
    path = results_path(base_dir, sport, date)
    if not path.exists():
        return None
    return load_daily_json(path)


def empty_day_payload(
    *,
    date: str,
    sport: str,
    day_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": DAILY_JSON_SCHEMA_VERSION,
        "date": validate_date(date),
        "sport": sport,
        "timezone": STATE_TIMEZONE,
        "day_status": day_status,
        "races": [],
    }


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def prediction_race_from_record(record: dict[str, Any]) -> dict[str, Any]:
    race = _copy_json(record)
    race["sport"] = record["sport"]
    race["date"] = record["date"]
    race["race_id"] = record.get("race_id") or make_race_id(record)
    if not race.get("axis"):
        derived = axis_from_tickets(race.get("tickets"))
        if derived:
            race["axis"] = derived
    return race


def build_predictions_payload(
    *,
    date: str,
    sport: str,
    races: list[dict[str, Any]],
    skipped: list[dict[str, Any]] | None = None,
    day_status: str = DAY_STATUS_PREDICTED,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": DAILY_JSON_SCHEMA_VERSION,
        "date": validate_date(date),
        "sport": sport,
        "timezone": STATE_TIMEZONE,
        "day_status": day_status,
        "races": [prediction_race_from_record(item) for item in races],
    }
    if skipped:
        payload["skipped"] = _copy_json(skipped)
    return payload


def result_race_from_record(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    race: dict[str, Any] = {
        "race_id": record.get("race_id") or make_race_id(record),
        "venue": record.get("venue"),
        "race": record.get("race"),
        "number": record.get("number"),
        "trifecta": result.get("trifecta"),
        "status": result.get("status"),
        "stake": result.get("stake"),
        "payout": result.get("payout"),
        "points": result.get("points", record.get("ticket_count")),
        "primary_miss_reason": result.get("primary_miss_reason"),
        "secondary_miss_reasons": list(result.get("secondary_miss_reasons") or []),
        "close_miss": result.get("close_miss"),
    }
    sport_fields: dict[str, Any] = {}
    if record.get("review"):
        sport_fields["review"] = _copy_json(record["review"])
    if result.get("scenario_realized") is not None:
        sport_fields["scenario_realized"] = result.get("scenario_realized")
    if sport_fields:
        race["sport_fields"] = sport_fields
    return race


def build_results_payload(
    *,
    date: str,
    sport: str,
    races: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = [result_race_from_record(item) for item in races if is_completed_race(item)]
    return {
        "schema_version": DAILY_JSON_SCHEMA_VERSION,
        "date": validate_date(date),
        "sport": sport,
        "timezone": STATE_TIMEZONE,
        "races": completed,
    }


def merge_result_races(
    existing: list[dict[str, Any]], newly: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in existing:
        key = str(row.get("race_id") or "")
        if key:
            merged[key] = _copy_json(row)
    for row in newly:
        key = str(row.get("race_id") or "")
        if not key:
            continue
        current = merged.get(key)
        if current and is_completed_race(current):
            continue
        merged[key] = _copy_json(row)
    return list(merged.values())


def records_from_predictions_doc(doc: dict[str, Any]) -> list[dict[str, Any]]:
    races = doc.get("races")
    if not isinstance(races, list):
        return []
    records: list[dict[str, Any]] = []
    for item in races:
        if not isinstance(item, dict) or item.get("skipped") or not item.get("tickets"):
            continue
        record = _copy_json(item)
        record["date"] = doc.get("date") or record.get("date")
        record["sport"] = doc.get("sport") or record.get("sport")
        record["race_id"] = record.get("race_id") or make_race_id(record)
        records.append(record)
    return records


def apply_results_doc_to_records(
    records: list[dict[str, Any]], results_doc: dict[str, Any] | None
) -> None:
    if not results_doc:
        return
    by_id = {
        str(row.get("race_id")): row
        for row in results_doc.get("races") or []
        if isinstance(row, dict) and row.get("race_id")
    }
    for record in records:
        row = by_id.get(str(record.get("race_id")))
        if not row or not is_completed_race(row):
            continue
        if (record.get("result") or {}).get("trifecta"):
            continue
        sport_fields = row.get("sport_fields") if isinstance(row.get("sport_fields"), dict) else {}
        record["result"] = {
            "trifecta": row.get("trifecta"),
            "status": row.get("status"),
            "stake": row.get("stake"),
            "payout": row.get("payout"),
            "points": row.get("points", record.get("ticket_count")),
            "primary_miss_reason": row.get("primary_miss_reason"),
            "secondary_miss_reasons": list(row.get("secondary_miss_reasons") or []),
            "close_miss": row.get("close_miss"),
            "scenario_realized": sport_fields.get("scenario_realized"),
        }
        if sport_fields.get("review"):
            record["review"] = _copy_json(sport_fields["review"])


def _require_keys(obj: dict[str, Any], keys: list[str], *, label: str) -> list[str]:
    missing = [key for key in keys if key not in obj]
    if missing:
        return [f"{label}に {', '.join(missing)} がありません"]
    return []


def prediction_reread_problems(
    loaded: dict[str, Any], expected: dict[str, Any]
) -> list[str]:
    problems: list[str] = []
    problems.extend(_require_keys(loaded, ["schema_version", "date", "sport", "races"], label="予想JSON"))
    if loaded.get("date") != expected.get("date"):
        problems.append(f"dateが一致しません: {loaded.get('date')} != {expected.get('date')}")
    if loaded.get("sport") != expected.get("sport"):
        problems.append(f"sportが一致しません: {loaded.get('sport')} != {expected.get('sport')}")
    loaded_races = loaded.get("races")
    expected_races = expected.get("races") or []
    if not isinstance(loaded_races, list):
        problems.append("racesが配列ではありません")
        return problems
    if len(loaded_races) != len(expected_races):
        problems.append(f"race数が一致しません: {len(loaded_races)} != {len(expected_races)}")
    if loaded.get("day_status") in {DAY_STATUS_NO_MEETING, DAY_STATUS_FETCH_FAILED}:
        return problems
    for index, race in enumerate(loaded_races):
        label = f"予想レース{index + 1}"
        if not isinstance(race, dict):
            problems.append(f"{label}がオブジェクトではありません")
            continue
        problems.extend(
            _require_keys(
                race,
                ["race_id", "prediction_score", "confidence", "tickets", "ticket_count"],
                label=label,
            )
        )
        if not race.get("axis") and not axis_from_tickets(race.get("tickets")):
            problems.append(f"{label}: axisを算出できる情報がありません")
        if not isinstance(race.get("tickets"), list) or not race.get("tickets"):
            problems.append(f"{label}: ticketsがありません")
    return problems


def results_reread_problems(loaded: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    problems.extend(_require_keys(loaded, ["schema_version", "date", "sport", "races"], label="結果JSON"))
    if loaded.get("date") != expected.get("date"):
        problems.append(f"dateが一致しません: {loaded.get('date')} != {expected.get('date')}")
    if loaded.get("sport") != expected.get("sport"):
        problems.append(f"sportが一致しません: {loaded.get('sport')} != {expected.get('sport')}")
    loaded_races = loaded.get("races")
    expected_races = expected.get("races") or []
    if not isinstance(loaded_races, list):
        problems.append("racesが配列ではありません")
        return problems
    loaded_ids = {str(row.get("race_id")) for row in loaded_races if isinstance(row, dict)}
    for row in expected_races:
        race_id = str(row.get("race_id"))
        if race_id not in loaded_ids:
            problems.append(f"race_id {race_id} が再読結果にありません")
    for index, race in enumerate(loaded_races):
        label = f"結果レース{index + 1}"
        if not isinstance(race, dict):
            problems.append(f"{label}がオブジェクトではありません")
            continue
        problems.extend(
            _require_keys(
                race,
                ["race_id", "status", "stake", "payout"],
                label=label,
            )
        )
        if race.get("status") not in COMPLETED_RESULT_STATUSES:
            problems.append(f"{label}: statusは的中またはハズレにしてください")
        if race.get("trifecta") in (None, ""):
            problems.append(f"{label}: 結果（三連単）がありません")
        if race.get("status") == "ハズレ" and not race.get("primary_miss_reason"):
            problems.append(f"{label}: ハズレ時のmiss_reasonがありません")
        if race.get("status") == "的中" and (race.get("payout") or 0) <= 0:
            problems.append(f"{label}: 的中時のpayoutがありません")
    return problems


def has_predicted_races(doc: dict[str, Any] | None) -> bool:
    if not doc:
        return False
    if doc.get("day_status") != DAY_STATUS_PREDICTED:
        return False
    races = doc.get("races")
    return isinstance(races, list) and any(
        isinstance(row, dict) and row.get("tickets") for row in races
    )


def results_cover_predictions(
    pred_doc: dict[str, Any], results_doc: dict[str, Any] | None
) -> bool:
    predicted = records_from_predictions_doc(pred_doc)
    if not predicted:
        return False
    done_ids = {
        str(row.get("race_id"))
        for row in (results_doc or {}).get("races") or []
        if isinstance(row, dict) and is_completed_race(row)
    }
    return all(str(record.get("race_id")) in done_ids for record in predicted)
