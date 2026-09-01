"""中央競馬（JRA）出走取得。開催日のみ。地方競馬とは分離。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data
from fetch.netkeiba import fetch_races_for_date as auto_fetch
from fetch.race_builder import race_data_path, save_races_json

SPORT = "jra"


def fetch_races(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = True,
    try_auto: bool = True,
) -> list[dict[str, Any]]:
    path = race_data_path(base_dir, SPORT, target_date)
    if path.exists():
        return load_race_data(base_dir, SPORT, target_date, allow_sample=False)

    if try_auto:
        races = auto_fetch(target_date, circuit="jra")
        if races:
            save_races_json(base_dir, SPORT, target_date, races, source="netkeiba-jra")
            return races
        # 開催なしも空リスト。サンプルへ落とさない（本番）。
        if not allow_sample:
            return []

    return load_race_data(base_dir, SPORT, target_date, allow_sample=allow_sample)
