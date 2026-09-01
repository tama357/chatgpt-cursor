"""原田さん向けワンショット実行（JSON作成・Excel記入・報告をCursor側で完結）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fetch import keiba as fetch_keiba_mod
from fetch import keirin as fetch_keirin_mod
from fetch.keirin_auto import fetch_results_for_predictions
from fetch.netkeiba import fetch_result_trifecta
from fetch.race_builder import (
    result_data_path,
    race_data_path,
    save_results_json,
    save_races_json,
)
from fetch.base import today_str


def _yesterday_str() -> str:
    tz = ZoneInfo("Asia/Tokyo")
    return (datetime.now(tz).date() - timedelta(days=1)).isoformat()


def _header(title: str, target_date: str) -> str:
    return f"# {title}\n\n対象日: **{target_date}**\n"


def ensure_race_data(base_dir: Path, sport: str, target_date: str) -> tuple[list[dict[str, Any]], str]:
    path = race_data_path(base_dir, sport, target_date)
    if sport == "keiba":
        races = fetch_keiba_mod.fetch_races(
            base_dir, target_date, allow_sample=False, try_auto=True
        )
        label = "競馬"
    else:
        races = fetch_keirin_mod.fetch_races(
            base_dir, target_date, allow_sample=False, try_auto=True
        )
        label = "競輪（個人）"

    if races:
        if not path.exists():
            source = (races[0].get("fetched_data") or {}).get("source", "auto")
            save_races_json(base_dir, sport, target_date, races, source=str(source))
        return races, f"✅ {label}: {len(races)}レース分の出走情報を確認（{path.name}）"

    return [], (
        f"⚠ {label}: 自動取得できませんでした。\n"
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
        return [], f"✅ {sport}: 結果JSONあり（{path.name}）"

    pending = [
        r
        for r in day_records
        if not r.get("skipped") and r.get("tickets") and not r.get("result")
    ]
    if not pending:
        return [], f"ℹ {sport}: 結果反映待ちの予想がありません。"

    if sport == "keirin":
        results = fetch_results_for_predictions(pending)
    else:
        results = []
        for record in pending:
            race_id = (record.get("fetched_data") or {}).get("race_id")
            if not race_id:
                continue
            parsed = fetch_result_trifecta(str(race_id))
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

    if not results:
        return [], (
            f"⚠ {sport}: 結果を自動取得できませんでした。\n"
            f"  CursorがWebで正式結果を確認し、`data/results/{sport}/{target_date}.json` を作成します。"
        )

    save_results_json(base_dir, sport, target_date, results, source="auto_fetch")
    return results, f"✅ {sport}: {len(results)}レースの結果JSONを作成（{path.name}）"


def run_predict_today(
    base_dir: Path,
    *,
    target_date: str | None = None,
    force: bool = False,
    run_predict_fn,
) -> str:
    """「今日の競馬と個人競輪を予想して」用。"""
    date = target_date or today_str()
    lines = [_header("今日の予想（競馬＋個人競輪）", date)]

    kb_races, kb_status = ensure_race_data(base_dir, "keiba", date)
    lines.append(kb_status)
    if not kb_races:
        lines.append("\n---\n\n競馬予想は出走情報取得後に実行します。")
    else:
        lines.append("\n" + run_predict_fn("keiba", date, force=force))

    lines.append("\n---\n")
    kr_races, kr_status = ensure_race_data(base_dir, "keirin", date)
    lines.append(kr_status)
    if not kr_races:
        lines.append("\n個人競輪予想は出走情報取得後に実行します。")
    else:
        lines.append("\n" + run_predict_fn("keirin", date, force=force))

    lines.append(
        "\n\n## Excelファイル\n"
        f"- 競馬 予想記入: `{base_dir / 'excel' / '競馬_予想記入シート_2026年9月.xlsx'}`\n"
        f"- 競馬 集計: `{base_dir / 'excel' / '競馬_予想集計シート_2026年9月.xlsx'}`\n"
        f"- 個人競輪 予想記入: `{base_dir / 'excel' / '競輪_個人_予想記入シート.xlsx'}`\n"
        f"- 個人競輪 集計: `{base_dir / 'excel' / '競輪_個人_予想集計シート.xlsx'}`\n"
        "\n詳細は `個人予想/CHATGPT_EXCEL.md` を参照（ChatGPT共有用）。"
    )
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
    """「昨日の結果を確認して」用。"""
    date = target_date or _yesterday_str()
    lines = [_header("昨日の結果確認（競馬＋個人競輪）", date)]

    for sport, label in (("keiba", "競馬"), ("keirin", "個人競輪")):
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
            lines.append(apply_results_fn(sport, date, result_path))
        elif run_results_fn is not None:
            lines.append(run_results_fn(sport, date, force=force))

        if run_learning_fn is not None:
            lines.append("\n### 学習レポート\n")
            lines.append(run_learning_fn(sport))

    lines.append(
        "\n\n## Excelファイル（更新済み）\n"
        "個人競輪の2ファイルをChatGPTへ渡す場合は `個人予想/CHATGPT_EXCEL.md` のパスを使ってください。"
    )
    return "\n".join(lines)
