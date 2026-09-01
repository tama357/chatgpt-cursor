"""中央競馬（JRA）出走取得。開催日のみ。地方競馬とは分離。

本番の既定は allow_sample=False。examples へは落とさない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data, reject_dummy_races
from fetch.netkeiba import fetch_races_outcome as auto_outcome
from fetch.race_builder import race_data_path, save_races_json

SPORT = "jra"


def fetch_races_outcome(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> dict[str, Any]:
    path = race_data_path(base_dir, SPORT, target_date)
    if path.exists():
        saved = reject_dummy_races(load_race_data(base_dir, SPORT, target_date, allow_sample=False))
        if saved:
            return {"races": saved, "status": "ok", "error": None}

    if try_auto:
        outcome = auto_outcome(target_date, circuit="jra")
        races = reject_dummy_races(list(outcome.get("races") or []))
        if races:
            save_races_json(base_dir, SPORT, target_date, races, source="netkeiba-jra")
            return {"races": races, "status": "ok", "error": None}
        if outcome.get("status") == "no_meeting":
            return {"races": [], "status": "no_meeting", "error": None}
        if not allow_sample:
            return {
                "races": [],
                "status": "fetch_failed" if outcome.get("status") == "fetch_failed" else "no_meeting",
                "error": outcome.get("error"),
            }

    if allow_sample:
        sample = load_race_data(base_dir, SPORT, target_date, allow_sample=True)
        if sample:
            return {"races": sample, "status": "ok", "error": None}
    return {"races": [], "status": "no_meeting", "error": None}


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
