from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

SAMPLE_SOURCES = frozenset({"sample", "example", "examples"})


def is_sample_payload(data: Any, path: Path | None = None) -> bool:
    if path is not None and ("examples" in path.parts or path.name.endswith(".sample.json")):
        return True
    if not isinstance(data, dict):
        return False
    source = str(data.get("source", "")).strip().lower()
    return source in SAMPLE_SOURCES or source.endswith("-sample") or source.startswith("sample")


def load_race_data(
    base_dir: Path,
    sport: str,
    target_date: str,
    *,
    allow_sample: bool = False,
) -> list[dict[str, Any]]:
    """レースデータを読み込む。

    本番（allow_sample=False）は data/races の本番JSONのみ。
    examples と source=sample の残りファイルは使わない。
    """
    data_path = base_dir / "data" / "races" / sport / f"{target_date}.json"
    if data_path.exists():
        with data_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if allow_sample or not is_sample_payload(data, data_path):
            return _races_from_payload(data, target_date)

    if allow_sample:
        sample_path = base_dir / "examples" / f"{sport}_races.sample.json"
        if sample_path.exists():
            with sample_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
            return _races_from_payload(data, target_date)
    return []


def _races_from_payload(data: Any, target_date: str) -> list[dict[str, Any]]:
    races = data.get("races", data if isinstance(data, list) else [])
    for race in races:
        if isinstance(race, dict):
            race.setdefault("date", target_date)
    return races if isinstance(races, list) else []


def today_str() -> str:
    return date.today().isoformat()
