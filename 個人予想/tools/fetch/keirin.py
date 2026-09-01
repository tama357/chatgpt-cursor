"""競輪レースデータ取得（個人検証用。提出用とは分離）。

公開APIが利用できない場合は data/races/keirin/YYYY-MM-DD.json を使用する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.base import load_race_data


def fetch_races(base_dir: Path, target_date: str) -> list[dict[str, Any]]:
    return load_race_data(base_dir, "keirin", target_date)
