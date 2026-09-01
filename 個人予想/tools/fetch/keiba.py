"""競馬レースデータ取得（個人利用）。

公開APIが利用できない場合は data/races/keiba/YYYY-MM-DD.json を使用する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data


def fetch_races(base_dir: Path, target_date: str) -> list[dict[str, Any]]:
    return load_race_data(base_dir, "keiba", target_date)
