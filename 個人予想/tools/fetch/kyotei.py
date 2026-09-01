"""競艇レースデータ取得（個人利用）。

1. data/races/kyotei/YYYY-MM-DD.json（本番JSON。source=sample は無視）
2. boatrace.jp 公式サイト自動取得
3. examples は allow_sample=True のテスト時のみ
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data, reject_dummy_races
from fetch.kyotei_auto import fetch_races_outcome as auto_outcome
from fetch.race_builder import race_data_path, save_races_json


def fetch_races_outcome(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> dict[str, Any]:
    path = race_data_path(base_dir, "kyotei", target_date)
    if path.exists():
        saved = reject_dummy_races(load_race_data(base_dir, "kyotei", target_date, allow_sample=False))
        if saved:
            return {"races": saved, "status": "ok", "error": None}

    if try_auto:
        try:
            outcome = auto_outcome(target_date)
        except Exception as exc:
            outcome = {"races": [], "status": "fetch_failed", "error": str(exc)}
        races = reject_dummy_races(list(outcome.get("races") or []))
        if races:
            save_races_json(base_dir, "kyotei", target_date, races, source="boatrace.jp")
            return {"races": races, "status": "ok", "error": None}
        if not allow_sample:
            status = "no_meeting" if outcome.get("status") == "no_meeting" else "fetch_failed"
            return {
                "races": [],
                "status": status,
                "error": outcome.get("error") or "公式出走を取得できませんでした",
            }

    if allow_sample:
        sample = load_race_data(base_dir, "kyotei", target_date, allow_sample=True)
        if sample:
            return {"races": sample, "status": "ok", "error": None}
    return {"races": [], "status": "fetch_failed", "error": "公式出走を取得できませんでした"}


def fetch_races(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> list[dict[str, Any]]:
    return list(
        fetch_races_outcome(
            base_dir, target_date, allow_sample=allow_sample, try_auto=try_auto
        ).get("races")
        or []
    )
