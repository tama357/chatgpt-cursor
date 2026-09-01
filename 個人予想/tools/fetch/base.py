from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common.jst import today_str as jst_today_str

SAMPLE_SOURCES = frozenset(
    {
        "sample",
        "example",
        "examples",
        "test_fixture",
        "fixture",
        "test",
    }
)


def is_sample_payload(data: Any, path: Path | None = None) -> bool:
    if path is not None and ("examples" in path.parts or path.name.endswith(".sample.json")):
        return True
    if not isinstance(data, dict):
        return False
    source = str(data.get("source", "")).strip().lower()
    if not source:
        return False
    return (
        source in SAMPLE_SOURCES
        or source.endswith("-sample")
        or source.endswith("_sample")
        or source.endswith("-fixture")
        or source.endswith("_fixture")
        or source.startswith("sample")
        or source.startswith("test")
    )


def load_race_data(
    base_dir: Path,
    sport: str,
    target_date: str,
    *,
    allow_sample: bool = False,
) -> list[dict[str, Any]]:
    """レースデータを読み込む。

    本番（allow_sample=False）は data/races の本番JSONのみ。
    examples・source=sample / test_fixture の残りファイルは使わない。
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
    return jst_today_str()


def is_dummy_entry_name(name: Any) -> bool:
    text = str(name or "").strip()
    if re.fullmatch(r"馬\d+", text):
        return True
    if re.fullmatch(r"\d+号艇", text):
        return True
    return False


def reject_dummy_races(races: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """本番用。ダミー馬名／号艇名だけのレースは公式情報とみなさない。"""
    kept: list[dict[str, Any]] = []
    for race in races:
        entries = race.get("entries") or []
        if not entries:
            continue
        if any(is_dummy_entry_name(e.get("name")) for e in entries):
            continue
        kept.append(race)
    return kept
