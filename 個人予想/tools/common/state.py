from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import (
    ALLOWED_CONFIDENCE,
    ALLOWED_STATUS,
    ALLOWED_TARGETS,
    DEFAULT_START_DATE,
    MISS_REASONS,
    SPORTS,
    STATE_TIMEZONE,
    STATE_VERSION,
)
from .tickets import ValidationError, count_tickets, expand_tickets


def new_state(sport: str, start_date: str = DEFAULT_START_DATE) -> dict[str, Any]:
    """既存構造に合わせた空の正規state。examples からは作らない。"""
    if sport not in SPORTS:
        raise ValidationError(f"未対応の競技です: {sport}")
    return {
        "version": STATE_VERSION,
        "sport": sport,
        "start_date": validate_date(start_date),
        "timezone": STATE_TIMEZONE,
        "records": [],
        "processed": {},
        "fetch_failures": [],
    }


def is_canonical_state(data: Any, sport: str) -> bool:
    if sport not in SPORTS or not isinstance(data, dict):
        return False
    if data.get("version") != STATE_VERSION:
        return False
    if data.get("sport") != sport:
        return False
    if data.get("timezone") != STATE_TIMEZONE:
        return False
    if not isinstance(data.get("records"), list):
        return False
    if not isinstance(data.get("processed"), dict):
        return False
    failures = data.get("fetch_failures", [])
    if not isinstance(failures, list):
        return False
    if data.get("source") in {"sample", "examples", "test_fixture"}:
        return False
    try:
        validate_date(data.get("start_date"))
    except ValidationError:
        return False
    return True


def canonical_state_problems(base_dir: Path) -> list[str]:
    problems: list[str] = []
    for sport in SPORTS:
        rel = f"data/{sport}/state.json"
        path = base_dir / rel
        if not path.exists():
            problems.append(f"{rel}（無い）")
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            problems.append(f"{rel}（JSONとして読めない）")
            continue
        if not is_canonical_state(data, sport):
            problems.append(f"{rel}（正規stateではない）")
    return problems


def production_state_problems(
    base_dir: Path, *, required_start_date: str = DEFAULT_START_DATE
) -> list[str]:
    """3競技の正規stateと開始日（既定 2026-09-03 JST）を検査する。"""
    required_start_date = validate_date(required_start_date)
    problems = canonical_state_problems(base_dir)
    dates: dict[str, str] = {}
    for sport in SPORTS:
        rel = f"data/{sport}/state.json"
        path = base_dir / rel
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not is_canonical_state(data, sport):
            continue
        start = data.get("start_date")
        dates[sport] = str(start)
        if start != required_start_date:
            problems.append(f"{rel}（start_dateが{required_start_date}ではない: {start}）")
    if len(dates) == len(SPORTS):
        unique = set(dates.values())
        if len(unique) != 1:
            problems.append(
                "3競技のstart_dateが一致しません: "
                + ", ".join(f"{sport}={dates[sport]}" for sport in SPORTS)
            )
    return problems


def load_canonical_state(base_dir: Path, sport: str) -> dict[str, Any]:
    """正規stateファイルだけを読む。無い・不正なら仮stateでは続けない。"""
    if sport not in SPORTS:
        raise ValidationError(f"未対応の競技です: {sport}")
    rel = f"data/{sport}/state.json"
    path = base_dir / rel
    if not path.exists():
        raise ValidationError(
            f"{rel} がありません。init-state で正規stateを作ってから実行してください。"
            " Excelは変更していません。"
        )
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{rel} を読めません。処理していません。") from exc
    if not is_canonical_state(data, sport):
        raise ValidationError(
            f"{rel} は正規stateではありません。処理していません。Excelは変更していません。"
        )
    if data.get("timezone") != STATE_TIMEZONE:
        raise ValidationError(
            f"{rel} のtimezoneは{STATE_TIMEZONE}にしてください。処理していません。"
        )
    if data.get("start_date") != DEFAULT_START_DATE:
        raise ValidationError(
            f"{rel} のstart_dateは{DEFAULT_START_DATE}にしてください。処理していません。"
        )
    return data


def require_production_states(base_dir: Path) -> None:
    """3競技すべての正規state（開始日 2026-09-03 JST）を処理前に揃える。"""
    problems = production_state_problems(base_dir)
    if problems:
        raise ValidationError(
            "3競技の正規stateが揃っていないため処理を開始しません: "
            + ", ".join(problems)
            + " 公式取得・Excel・state・Driveは変更していません。"
        )


def get_start_date(state: dict[str, Any]) -> str:
    raw = state.get("start_date")
    if isinstance(raw, str):
        try:
            return validate_date(raw)
        except ValidationError:
            pass
    return DEFAULT_START_DATE


def is_before_start_date(state: dict[str, Any], date: str) -> bool:
    return validate_date(date) < get_start_date(state)


def records_since_start(
    state: dict[str, Any],
    *,
    with_result: bool | None = None,
) -> list[dict[str, Any]]:
    start = get_start_date(state)
    out: list[dict[str, Any]] = []
    for record in get_records(state, with_result=with_result):
        raw = record.get("date")
        if not isinstance(raw, str):
            continue
        try:
            if validate_date(raw) < start:
                continue
        except ValidationError:
            continue
        out.append(record)
    return out


def skip_before_start_message(state: dict[str, Any], date: str, *, kind: str) -> str:
    start = get_start_date(state)
    if kind == "results":
        return (
            f"{date} は開始日 {start}（{STATE_TIMEZONE}）より前のため、"
            "結果取得・集計・復習・学習の対象外です。Excelは変更していません。"
        )
    return (
        f"{date} は開始日 {start}（{STATE_TIMEZONE}）より前のため、"
        "予想の対象外です。Excelは変更していません。"
    )


def _place_state_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    sidecar = dest.with_name(dest.name + ".writing")
    try:
        shutil.copyfile(src, sidecar)
        os.replace(sidecar, dest)
    except Exception:
        if sidecar.exists():
            sidecar.unlink()
        raise


def _remove_created_states(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        sidecar = path.with_name(path.name + ".writing")
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            pass


def init_personal_states(
    base_dir: Path,
    *,
    start_date: str = DEFAULT_START_DATE,
    confirm: bool = False,
) -> str:
    """3競技の正規stateを新規作成する。既存ファイルは上書きしない。全成功または全失敗。"""
    if not confirm:
        raise ValidationError(
            "初期化には --i-confirm-init-state が必要です。実行していません。"
        )
    start_date = validate_date(start_date)
    if start_date != DEFAULT_START_DATE:
        raise ValidationError(
            f"start_dateは{DEFAULT_START_DATE}（JST）にしてください。初期化していません。"
        )
    existing = [
        f"data/{sport}/state.json"
        for sport in SPORTS
        if (base_dir / "data" / sport / "state.json").exists()
    ]
    if existing:
        raise ValidationError(
            "既存の state を上書きしません: "
            + ", ".join(existing)
            + "。初期化していません。"
        )

    tmp_root = Path(tempfile.mkdtemp(prefix="personal-init-state-"))
    created: list[Path] = []
    try:
        for sport in SPORTS:
            payload = new_state(sport, start_date)
            if not is_canonical_state(payload, sport):
                raise ValidationError(f"{sport} の正規stateを組み立てられませんでした。")
            tmp_path = tmp_root / f"{sport}.json"
            save_json(tmp_path, payload)
            loaded = json.loads(tmp_path.read_text(encoding="utf-8"))
            if not is_canonical_state(loaded, sport) or loaded.get("start_date") != start_date:
                raise ValidationError(f"{sport} の一時stateが正規ではありません。")

        for sport in SPORTS:
            dest = base_dir / "data" / sport / "state.json"
            if dest.exists():
                raise ValidationError(
                    f"既存の state を上書きしません: data/{sport}/state.json。初期化していません。"
                )
            _place_state_file(tmp_root / f"{sport}.json", dest)
            created.append(dest)

        written = [f"data/{sport}/state.json" for sport in SPORTS]
        return (
            "## 個人予想 state 初期化\n\n"
            f"開始日: {start_date}（{STATE_TIMEZONE}）\n"
            + "\n".join(f"- {name}" for name in written)
            + "\nExcel・Drive・提出用競輪は変更していません。"
        )
    except Exception as exc:
        _remove_created_states(created)
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(
            "初期化に失敗したため、この実行で作ったstateは残していません。"
            f" {exc}"
        ) from exc
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "sport": "", "records": [], "processed": {}}
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
