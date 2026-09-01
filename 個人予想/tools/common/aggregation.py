from __future__ import annotations

import math
from typing import Any, Callable

from .constants import MISS_REASONS


def performance(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "n": 0,
            "hits": 0,
            "hit_rate": None,
            "stake": 0,
            "payout": 0,
            "return_rate": None,
        }
    stake = sum(r["result"]["stake"] for r in records if r.get("result"))
    payout = sum(r["result"]["payout"] for r in records if r.get("result"))
    completed = [r for r in records if r.get("result") and r["result"]["status"] != "未実施"]
    hits = sum(r["result"]["status"] == "的中" for r in completed)
    n = len(completed)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": hits / n if n else None,
        "stake": stake,
        "payout": payout,
        "return_rate": payout / stake if stake else None,
    }


def group_performance(
    records: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if not record.get("result") or record["result"]["status"] == "未実施":
            continue
        key = key_fn(record)
        groups.setdefault(key, []).append(record)
    return {key: performance(groups[key]) for key in sorted(groups)}


def score_band(score: int) -> str:
    if score < 60:
        return "0-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def odds_band(odds: float | None) -> str:
    if odds is None:
        return "unknown"
    if odds < 10:
        return "0-9.9"
    if odds < 30:
        return "10-29.9"
    if odds < 100:
        return "30-99.9"
    if odds < 300:
        return "100-299.9"
    return "300+"


def axis_type(record: dict[str, Any]) -> str:
    axis = record.get("axis")
    if not isinstance(axis, str) or not axis:
        return "unknown"
    return axis.split("-")[0] if "-" in axis else axis[:1]


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys))
    if den == 0:
        return None
    return round(num / den, 4)


def aggregate_periods(records: list[dict[str, Any]], today: str) -> dict[str, Any]:
    completed = [
        r
        for r in records
        if r.get("result") and r["result"]["status"] in {"的中", "ハズレ"}
    ]
    completed_sorted = sorted(completed, key=lambda r: (r["date"], r.get("venue", ""), r.get("race", 0)))
    today_records = [r for r in completed_sorted if r["date"] == today]
    last_30 = completed_sorted[-30:]
    last_100 = completed_sorted[-100:]
    return {
        "today": performance(today_records),
        "last_30": performance(last_30),
        "last_100": performance(last_100),
        "all": performance(completed_sorted),
    }


def build_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [
        r
        for r in records
        if r.get("result") and r["result"]["status"] in {"的中", "ハズレ"}
    ]
    return {
        "prediction_score_band": group_performance(completed, lambda r: score_band(r["prediction_score"])),
        "confidence": group_performance(completed, lambda r: str(r["confidence"])),
        "venue": group_performance(completed, lambda r: str(r.get("venue", "unknown"))),
        "ticket_count": group_performance(completed, lambda r: str(r.get("ticket_count", 0))),
        "odds_band": group_performance(completed, lambda r: odds_band(r.get("odds_band_median"))),
        "axis_type": group_performance(completed, lambda r: axis_type(r)),
        "target": group_performance(completed, lambda r: str(r.get("target", "unknown"))),
        "miss_reason": _miss_reason_summary(completed),
        "skip_reason": group_performance(
            [r for r in records if r.get("skipped")],
            lambda r: str(r.get("skip_reason", "unknown")),
        ),
    }


def _miss_reason_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        reason: {"primary_count": 0, "secondary_count": 0, "loss_amount": 0}
        for reason in sorted(MISS_REASONS)
    }
    for record in records:
        result = record.get("result")
        if not result or result["status"] != "ハズレ":
            continue
        primary = result.get("primary_miss_reason")
        if primary in summary:
            summary[primary]["primary_count"] += 1
            summary[primary]["loss_amount"] += result.get("stake", 0)
        for secondary in result.get("secondary_miss_reasons", []):
            if secondary in summary:
                summary[secondary]["secondary_count"] += 1
    return summary
