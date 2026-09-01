"""Cursor が Web 調査後にレースJSONを保存するためのヘルパー。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .http import save_json as write_json


def race_data_path(base_dir: Path, sport: str, target_date: str) -> Path:
    return base_dir / "data" / "races" / sport / f"{target_date}.json"


def result_data_path(base_dir: Path, sport: str, target_date: str) -> Path:
    return base_dir / "data" / "results" / sport / f"{target_date}.json"


def save_races_json(
    base_dir: Path,
    sport: str,
    target_date: str,
    races: list[dict[str, Any]],
    *,
    source: str = "cursor_web",
) -> Path:
    path = race_data_path(base_dir, sport, target_date)
    payload = {"date": target_date, "source": source, "races": races}
    write_json(path, payload)
    return path


def save_results_json(
    base_dir: Path,
    sport: str,
    target_date: str,
    results: list[dict[str, Any]],
    *,
    source: str = "cursor_auto",
) -> Path:
    path = result_data_path(base_dir, sport, target_date)
    payload = {"date": target_date, "source": source, "results": results}
    write_json(path, payload)
    return path


def load_races_from_file(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    races = data.get("races", [])
    if not isinstance(races, list):
        raise ValueError(f"{path}: races が配列ではありません")
    return races


def load_results_payload(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: 結果JSONがオブジェクトではありません")
    return data


def is_official_result_file(path: Path) -> bool:
    """examples / sample / test_fixture の結果は公式として扱わない。"""
    if not path.exists():
        return False
    from .base import is_sample_payload

    data = load_results_payload(path)
    if is_sample_payload(data, path):
        return False
    results = data.get("results")
    return isinstance(results, list) and bool(results)


def load_official_results(path: Path) -> list[dict[str, Any]]:
    if not is_official_result_file(path):
        return []
    results = load_results_payload(path).get("results") or []
    return list(results) if isinstance(results, list) else []
