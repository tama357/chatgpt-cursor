"""原田さん向けワンショット実行（JSON作成・Excel記入・報告をCursor側で完結）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.constants import EXCEL_FILENAMES, SPORT_LABELS, SPORTS
from common.jst import today_str, yesterday_str
from common.state import is_before_start_date, load_json, skip_before_start_message
from fetch import jra as fetch_jra_mod
from fetch import nar as fetch_nar_mod
from fetch import kyotei as fetch_kyotei_mod
from fetch.kyotei_auto import fetch_results_for_predictions
from fetch.netkeiba import fetch_results_for_predictions as fetch_keiba_results
from fetch.base import is_sample_payload
from fetch.race_builder import (
    is_official_result_file,
    load_official_results,
    load_results_payload,
    result_data_path,
    race_data_path,
    save_results_json,
    save_races_json,
)

from excel.drive_sync import DriveAuthError, sync_excel_files  # noqa: E402

FETCHERS = {"jra": fetch_jra_mod, "nar": fetch_nar_mod, "kyotei": fetch_kyotei_mod}


def _header(title: str, target_date: str) -> str:
    return f"# {title}\n\n対象日: **{target_date}**\n"


def ensure_race_data(base_dir: Path, sport: str, target_date: str) -> tuple[list[dict[str, Any]], str]:
    path = race_data_path(base_dir, sport, target_date)
    if sport not in FETCHERS:
        return [], f"⚠ 未対応の競技です: {sport}"
    fetcher = FETCHERS[sport]
    outcome_fn = getattr(fetcher, "fetch_races_outcome", None)
    if outcome_fn:
        outcome = outcome_fn(base_dir, target_date, allow_sample=False, try_auto=True)
        races = list(outcome.get("races") or [])
        status_code = outcome.get("status") or ("ok" if races else "fetch_failed")
    else:
        races = fetcher.fetch_races(base_dir, target_date, allow_sample=False, try_auto=True)
        status_code = "ok" if races else "fetch_failed"
    label = SPORT_LABELS[sport]

    if races:
        if not path.exists():
            source = (races[0].get("fetched_data") or {}).get("source", "auto")
            save_races_json(base_dir, sport, target_date, races, source=str(source))
        return races, f"✅ {label}: {len(races)}レース分の出走情報を確認（{path.name}）"

    if sport == "jra" and status_code != "fetch_failed":
        return [], (
            f"【開催なし】{target_date} は中央競馬（JRA）の開催日ではありません。"
            "開催日のみ予想します。"
        )
    if status_code == "no_meeting":
        return [], f"【開催なし】{target_date} の{label}は公式一覧上で開催がありません。"
    return [], (
        f"【取得失敗】{label}の出走情報を取得できませんでした。サンプルデータは使いません。"
        " この競技の予想は中止します。"
    )


def _result_key(row: dict[str, Any]) -> tuple[Any, Any]:
    race = row.get("race")
    try:
        race = int(race)
    except (TypeError, ValueError):
        pass
    return (row.get("venue"), race)


def _merge_result_rows(
    existing: list[dict[str, Any]], newly: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in existing:
        merged[_result_key(row)] = row
    for row in newly:
        key = _result_key(row)
        if key not in merged:
            merged[key] = row
    return list(merged.values())


def ensure_result_data(
    base_dir: Path,
    sport: str,
    target_date: str,
    day_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    path = result_data_path(base_dir, sport, target_date)
    existing: list[dict[str, Any]] = []
    if is_official_result_file(path):
        existing = load_official_results(path)
    elif path.exists():
        leftover = load_results_payload(path)
        if is_sample_payload(leftover, path):
            pass

    have = {_result_key(r) for r in existing}
    pending = []
    for record in day_records:
        if record.get("skipped") or not record.get("tickets"):
            continue
        if (record.get("result") or {}).get("trifecta"):
            continue
        if _result_key(record) in have:
            continue
        pending.append(record)

    newly: list[dict[str, Any]] = []
    if pending:
        if sport == "kyotei":
            newly = fetch_results_for_predictions(pending)
        elif sport in {"jra", "nar"}:
            circuit = "nar" if sport == "nar" else "jra"
            newly = fetch_keiba_results(pending, circuit)

    merged = _merge_result_rows(existing, newly)
    if newly:
        save_results_json(base_dir, sport, target_date, merged, source="auto_fetch")

    label = SPORT_LABELS.get(sport, sport)
    needed = [
        r
        for r in day_records
        if not r.get("skipped") and r.get("tickets")
    ]
    needed_keys = {_result_key(r) for r in needed}
    got_keys = {_result_key(r) for r in merged}
    missing = needed_keys - got_keys

    if not needed:
        return [], f"ℹ {label}: 結果反映待ちの予想がありません。"
    if not merged:
        return [], (
            f"【取得失敗】{label}の正式結果を取得できませんでした。"
            " 推測では記入しません。この競技の結果処理は中止します。"
        )
    if missing:
        names = ", ".join(f"{venue}{race}R" for venue, race in sorted(missing, key=lambda x: str(x)))
        return merged, f"✅ {label}: {len(merged)}レース取得。未取得あり: {names}"
    return merged, f"✅ {label}: {len(merged)}レースの正式結果を確認（{path.name}）"


def _append_drive_sync(base_dir: Path, lines: list[str], *, keys: list[str] | None = None) -> None:
    lines.append(
        "\n\n## Google Drive\n\n"
        "この段階ではExcelをDriveへ送っていません。"
        " クラウド実行（GitHub Actions）では、ジョブ終了時に既存6ファイルをID指定で上書き保存します。"
        " 日々のExcel更新ではPRを作りません。"
    )


def _excel_list(base_dir: Path) -> str:
    lines = ["\n\n## Excelファイル（ローカル）"]
    for key, name in EXCEL_FILENAMES.items():
        lines.append(f"- {key}: `{base_dir / 'excel' / name}`")
    lines.append("\n詳細は `個人予想/CHATGPT_EXCEL.md` を参照。")
    return "\n".join(lines)


def run_predict_today(
    base_dir: Path,
    *,
    target_date: str | None = None,
    force: bool = False,
    run_predict_fn,
) -> str:
    """「今日の中央競馬と地方競馬と競艇を予想して」用。"""
    date = target_date or today_str()
    lines = [_header("今日の予想（中央競馬＋地方競馬＋競艇）", date)]

    for sport in SPORTS:
        label = SPORT_LABELS[sport]
        lines.append(f"\n---\n\n## {label}\n")
        state = load_json(base_dir / "data" / sport / "state.json")
        if is_before_start_date(state, date):
            lines.append(skip_before_start_message(state, date, kind="predict"))
            continue
        races, status = ensure_race_data(base_dir, sport, date)
        lines.append(status)
        if not races:
            if "開催なし" in status:
                lines.append(f"\n{label}は開催なしとして正常終了します。")
            else:
                lines.append(f"\n{label}予想はこの競技だけ中止します。")
            continue
        lines.append("\n" + run_predict_fn(sport, date, force=force, sync_drive=False))

    lines.append(_excel_list(base_dir))
    _append_drive_sync(base_dir, lines)
    return "\n".join(lines)


def run_results_yesterday(
    base_dir: Path,
    *,
    target_date: str | None = None,
    force: bool = False,
    run_predict_fn=None,
    apply_results_fn=None,
    run_results_fn=None,
    run_learning_fn=None,
    find_day_records_fn=None,
    load_state_fn=None,
) -> str:
    """「昨日の結果を確認して」用。3競技を別々に反映。"""
    date = target_date or yesterday_str()
    lines = [_header("昨日の結果確認（中央競馬＋地方競馬＋競艇）", date)]

    for sport in SPORTS:
        label = SPORT_LABELS[sport]
        lines.append(f"\n## {label}\n")
        state = load_state_fn(sport)
        if is_before_start_date(state, date):
            lines.append(skip_before_start_message(state, date, kind="results"))
            continue
        day_records = find_day_records_fn(state, date)
        if not day_records:
            lines.append(f"{date} の{label}予想記録がありません。")
            continue

        results, status = ensure_result_data(base_dir, sport, date, day_records)
        lines.append(status)

        result_path = result_data_path(base_dir, sport, date)
        if results and apply_results_fn is not None and is_official_result_file(result_path):
            lines.append(apply_results_fn(sport, date, result_path, sync_drive=False))
        elif run_results_fn is not None:
            lines.append(run_results_fn(sport, date, force=force, sync_drive=False))

        still_pending = [
            r
            for r in find_day_records_fn(load_state_fn(sport), date)
            if not r.get("skipped") and r.get("tickets") and not (r.get("result") or {}).get("trifecta")
        ]
        if run_learning_fn is not None and not still_pending:
            lines.append(f"\n### {label} 学習レポート（他競技と混ぜない）\n")
            lines.append(run_learning_fn(sport))
        elif still_pending:
            lines.append(f"\n{label}は未取得があるため、この日付を処理済みにも学習確定にもしません。")

    lines.append(_excel_list(base_dir))
    _append_drive_sync(base_dir, lines)
    return "\n".join(lines)
