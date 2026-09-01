"""地方競馬（NAR）出走取得。中央競馬とは分離。

本番の既定は allow_sample=False。取得失敗時に examples へは落とさない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data
from fetch.netkeiba import fetch_races_for_date as auto_fetch
from fetch.race_builder import race_data_path, save_races_json

SPORT = "nar"


def fetch_races(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> list[dict[str, Any]]:
    path = race_data_path(base_dir, SPORT, target_date)
    if path.exists():
        saved = load_race_data(base_dir, SPORT, target_date, allow_sample=False)
        if saved:
            return saved

    if try_auto:
        races = auto_fetch(target_date, circuit="nar")
        if races:
            save_races_json(base_dir, SPORT, target_date, races, source="netkeiba-nar")
            return races
        if not allow_sample:
            return []

    return load_race_data(base_dir, SPORT, target_date, allow_sample=allow_sample)
