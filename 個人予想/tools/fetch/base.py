from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def load_race_data(base_dir: Path, sport: str, target_date: str) -> list[dict[str, Any]]:
    """レースデータを読み込む。優先: data/races/{sport}/{date}.json → examples"""
    paths = [
        base_dir / "data" / "races" / sport / f"{target_date}.json",
        base_dir / "examples" / f"{sport}_races.sample.json",
    ]
    for path in paths:
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            races = data.get("races", data if isinstance(data, list) else [])
            for race in races:
                race.setdefault("date", target_date)
            return races
    return []


def today_str() -> str:
    return date.today().isoformat()
