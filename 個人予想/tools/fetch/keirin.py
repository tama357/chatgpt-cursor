"""競輪レースデータ取得（個人検証用。提出用とは分離）。

1. data/races/keirin/YYYY-MM-DD.json
2. keirin.jp 自動取得
3. examples（テスト用のみ）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data
from fetch.keirin_auto import fetch_races_for_date as auto_fetch
from fetch.race_builder import race_data_path, save_races_json


def fetch_races(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = True,
    try_auto: bool = True,
) -> list[dict[str, Any]]:
    path = race_data_path(base_dir, "keirin", target_date)
    if path.exists():
        return load_race_data(base_dir, "keirin", target_date, allow_sample=False)

    if try_auto:
        try:
            races = auto_fetch(target_date)
        except Exception:
            races = []
        if races:
            save_races_json(base_dir, "keirin", target_date, races, source="keirin.jp")
            return races

    return load_race_data(base_dir, "keirin", target_date, allow_sample=allow_sample)
