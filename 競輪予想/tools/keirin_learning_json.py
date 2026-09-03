"""学習用JSON。既存シートには書かない。保存先は競輪学習inbox。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from keirin_chatgpt_io import (
    learning_inbox_path,
    predictions_inbox_path,
    results_inbox_path,
    save_json,
)


def axis_place(axis: str | None, trifecta: str | None) -> int | None:
    if not axis or not trifecta:
        return None
    parts = str(trifecta).split("-")
    if axis in parts:
        return parts.index(axis) + 1
    return 0


def return_rate(payout: int, stake: int) -> float | None:
    if not stake:
        return None
    return round(payout / stake, 4)


def build_learning_records(
    *,
    date: str,
    predictions: list[dict[str, Any]],
    results: list[dict[str, Any]],
    low_quality_day: bool,
) -> dict[str, Any]:
    by_number = {int(item["number"]): item for item in results}
    races: list[dict[str, Any]] = []
    for pred in predictions:
        number = int(pred["number"])
        result = by_number.get(number) or {}
        stake = int(result.get("stake") or pred.get("ticket_count") or 0) * (
            1 if result.get("stake") else 100
        )
        if result.get("stake"):
            stake = int(result["stake"])
        else:
            stake = int(pred.get("ticket_count") or 0) * 100
        payout = int(result.get("payout") or 0)
        trifecta = result.get("trifecta")
        races.append(
            {
                "number": number,
                "venue": pred.get("venue"),
                "race": pred.get("race"),
                "prediction_score": pred.get("prediction_score"),
                "confidence": pred.get("confidence"),
                "actual_order": trifecta,
                "status": result.get("status"),
                "payout": payout,
                "stake": stake,
                "return_rate": return_rate(payout, stake),
                "axis": pred.get("axis"),
                "axis_place": axis_place(pred.get("axis"), trifecta),
                "primary_miss_reason": result.get("primary_miss_reason"),
                "secondary_miss_reasons": result.get("secondary_miss_reasons") or [],
                "close_miss": result.get("close_miss"),
                "scenario_materialized": result.get("scenario_materialized"),
                "low_quality_day": low_quality_day,
            }
        )
    return {
        "schema_version": 1,
        "date": date,
        "sport": "keirin",
        "sheet_structure_changed": False,
        "races": races,
    }


def save_predictions_inbox(root: Path, payload: dict[str, Any]) -> Path:
    path = predictions_inbox_path(root, payload["date"])
    return save_json(path, payload)


def save_results_inbox(root: Path, payload: dict[str, Any]) -> Path:
    path = results_inbox_path(root, payload["date"])
    return save_json(path, payload)


def save_learning_inbox(root: Path, payload: dict[str, Any]) -> Path:
    path = learning_inbox_path(root, payload["date"])
    return save_json(path, payload)
