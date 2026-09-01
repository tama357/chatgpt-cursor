"""原田さん向けワンショット実行（JSON作成・Excel記入・報告をCursor側で完結）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from common.constants import EXCEL_FILENAMES, SPORT_LABELS, SPORTS
from fetch import jra as fetch_jra_mod
from fetch import nar as fetch_nar_mod
from fetch import kyotei as fetch_kyotei_mod
from fetch.kyotei_auto import fetch_results_for_predictions
from fetch.netkeiba import fetch_result_trifecta
from fetch.race_builder import (
    result_data_path,
    race_data_path,
    save_results_json,
    save_races_json,
)
from fetch.base import today_str

from excel.drive_sync import DriveAuthError, sync_excel_files  # noqa: E402

FETCHERS = {"jra": fetch_jra_mod, "nar": fetch_nar_mod, "kyotei": fetch_kyotei_mod}


def _yesterday_str() -> str:
    tz = ZoneInfo("Asia/Tokyo")
    return (datetime.now(tz).date() - timedelta(days=1)).isoformat()


def _header(title: str, target_date: str) -> str:
    return f"# {title}\n\n対象日: **{target_date}**\n"


def ensure_race_data(base_dir: Path, sport: str, target_date: str) -> tuple[list[dict[str, Any]], str]:
    path = race_data_path(base_dir, sport, target_date)
    if sport not in FETCHERS:
        return [], f"⚠ 未対応の競技です: {sport}"
    fetcher = FETCHERS[sport]
    races = fetcher.fetch_races(base_dir, target_date, allow_sample=False, try_auto=True)
    label = SPORT_LABELS[sport]

    if races:
        if not path.exists():
            source = (races[0].get("fetched_data") or {}).get("source", "auto")
            save_races_json(base_dir, sport, target_date, races, source=str(source))
        return races, f"✅ {label}: {len(races)}レース分の出走情報を確認（{path.name}）"

    if sport == "jra":
        return [], f"ℹ {label}: 本日はJRA開催がありません。開催日のみ予想します。"
    return [], (
        f"⚠ {label}: 自動取得に失敗しました。サンプルデータは使いません。\n"
        f"  CursorがWebで出走情報を調査し、`data/races/{sport}/{target_date}.json` を作成します。\n"
        f"  原田さんの手作業は不要です。"
    )


def ensure_result_data(
    base_dir: Path,
    sport: str,
    target_date: str,
    day_records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    path = result_data_path(base_dir, sport, target_date)
    if path.exists():
        return [], f"✅ {SPORT_LABELS.get(sport, sport)}: 結果JSONあり（{path.name}）"

    pending = [
        r
        for r in day_records
        if not r.get("skipped") and r.get("tickets") and not r.get("result")
    ]
    if not pending:
        return [], f"ℹ {SPORT_LABELS.get(sport, sport)}: 結果反映待ちの予想がありません。"

    if sport == "kyotei":
        results = fetch_results_for_predictions(pending)
    elif sport in {"jra", "nar"}:
        results = []
        circuit = "nar" if sport == "nar" else "jra"
        for record in pending:
            race_id = (record.get("fetched_data") or {}).get("race_id")
            if not race_id:
                continue
            parsed = fetch_result_trifecta(str(race_id), circuit=circuit)
            if not parsed:
                continue
            results.append(
                {
                    "venue": record.get("venue"),
                    "race": record.get("race"),
                    "trifecta": parsed["trifecta"],
                    "payout": parsed.get("payout", 0),
                    "scenario_realized": None,
                }
            )
    else:
        results = []

    if not results:
        return [], (
            f"⚠ {SPORT_LABELS.get(sport, sport)}: 結果を自動取得できませんでした。\n"
            f"  CursorがWebで正式結果を確認し、`data/results/{sport}/{target_date}.json` を作成します。"
        )

    save_results_json(base_dir, sport, target_date, results, source="auto_fetch")
    return results, f"✅ {SPORT_LABELS.get(sport, sport)}: {len(results)}レースの結果JSONを作成（{path.name}）"


def _append_drive_sync(base_dir: Path, lines: list[str], *, keys: list[str] | None = None) -> None:
    # この修正では Drive へアップロードしない。認証があっても報告はローカル接続のみ。
    lines.append("\n\n## Google Drive\n\n今回は Drive を更新していません。ローカルExcelのみ接続・記入しています。")


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
        races, status = ensure_race_data(base_dir, sport, date)
        lines.append(status)
        if not races:
            if sport == "jra":
                lines.append("\n中央競馬は開催日のみ予想します。")
            else:
                lines.append(f"\n{label}予想は出走情報取得後に実行します。")
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
    date = target_date or _yesterday_str()
    lines = [_header("昨日の結果確認（中央競馬＋地方競馬＋競艇）", date)]

    for sport in SPORTS:
        label = SPORT_LABELS[sport]
        lines.append(f"\n## {label}\n")
        state = load_state_fn(sport)
        day_records = find_day_records_fn(state, date)
        if not day_records:
            lines.append(f"{date} の{label}予想記録がありません。")
            continue

        _, status = ensure_result_data(base_dir, sport, date, day_records)
        lines.append(status)

        result_path = result_data_path(base_dir, sport, date)
        if result_path.exists() and apply_results_fn is not None:
            lines.append(apply_results_fn(sport, date, result_path, sync_drive=False))
        elif run_results_fn is not None:
            lines.append(run_results_fn(sport, date, force=force, sync_drive=False))

        if run_learning_fn is not None:
            lines.append(f"\n### {label} 学習レポート（他競技と混ぜない）\n")
            lines.append(run_learning_fn(sport))

    lines.append(_excel_list(base_dir))
    _append_drive_sync(base_dir, lines)
    return "\n".join(lines)
