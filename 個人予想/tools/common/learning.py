from __future__ import annotations

import math
from typing import Any

from .aggregation import pearson, performance
from .constants import MISS_REASONS


def build_learning_report(
    records: list[dict[str, Any]], rules: dict[str, Any]
) -> dict[str, Any]:
    completed = [
        r
        for r in records
        if r.get("result") and r["result"]["status"] in {"的中", "ハズレ"}
    ]
    initial = rules["scoring_rubric"]["initial_weights"]
    threshold = rules.get("learning_auto_apply_threshold", 100)
    n = len(completed)
    report: dict[str, Any] = {
        "version": 1,
        "sport": rules["sport"],
        "prediction_logic_version": rules.get("prediction_logic_version"),
        "race_count": n,
        "remaining_to_threshold": max(0, threshold - n),
        "auto_change_allowed": n >= threshold,
        "initial_weights": dict(initial),
        "overall": performance(completed),
        "weights_auto_applied": False,
    }
    if n == 0:
        report["recommended_weights"] = _empty_recommendation(initial)
        report["message"] = "履歴がないため傾向分析のみ可能です"
        return report

    breakdown_keys = _collect_breakdown_keys(completed)
    correlations: dict[str, dict[str, Any]] = {}
    hit_values = [1.0 if r["result"]["status"] == "的中" else 0.0 for r in completed]
    return_values = [r["result"]["payout"] / r["result"]["stake"] for r in completed]
    for key in breakdown_keys:
        scores = [float(r.get("score_breakdown", {}).get(key, 0)) for r in completed]
        correlations[key] = {
            "hit_rate_correlation": pearson(scores, hit_values),
            "return_rate_correlation": pearson(scores, return_values),
        }
    report["scoring_item_relationships"] = correlations
    report["good_conditions"] = _top_conditions(completed, reverse=True)
    report["bad_conditions"] = _top_conditions(completed, reverse=False)
    report["miss_reason_trends"] = _miss_trends(completed)
    report["overbetting_check"] = _overbetting_check(completed, rules)
    report["return_rate_drag_factors"] = _return_drag(completed)

    if n < threshold:
        report["recommended_weights"] = {
            "status": "collection_phase",
            "sample_size": n,
            "threshold": threshold,
            "weights": dict(initial),
            "auto_applied": False,
            "note": f"{threshold}レース未満のため配点変更は提案のみ。自動反映しません。",
        }
    else:
        report["recommended_weights"] = _recommended_weights(initial, correlations, n)
    return report


def _collect_breakdown_keys(records: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for record in records:
        keys.update(record.get("score_breakdown", {}).keys())
    return sorted(keys)


def _empty_recommendation(initial: dict[str, int]) -> dict[str, Any]:
    return {
        "status": "no_data",
        "sample_size": 0,
        "weights": dict(initial),
        "auto_applied": False,
    }


def _recommended_weights(
    initial: dict[str, int], correlations: dict[str, dict[str, Any]], sample_size: int
) -> dict[str, Any]:
    raw: dict[str, float] = {}
    impacts: dict[str, dict[str, Any]] = {}
    for key, weight in initial.items():
        values = [
            v
            for v in (
                correlations.get(key, {}).get("hit_rate_correlation"),
                correlations.get(key, {}).get("return_rate_correlation"),
            )
            if v is not None
        ]
        signal = sum(values) / len(values) if values else 0.0
        raw[key] = weight * max(0.5, 1 + 0.35 * signal)
        impacts[key] = {
            "current_weight": weight,
            "proposed_weight": None,
            "signal": round(signal, 4),
            "hit_rate_impact": "要確認",
            "return_rate_impact": "要確認",
            "overfitting_risk": "中" if sample_size < 150 else "低",
            "change_risk": "原田さん承認前は反映しない",
        }
    scale = 100 / sum(raw.values())
    scaled = {k: raw[k] * scale for k in raw}
    proposed = {k: math.floor(v) for k, v in scaled.items()}
    remainder = 100 - sum(proposed.values())
    for key in sorted(scaled, key=lambda name: scaled[name] - proposed[name], reverse=True)[
        :remainder
    ]:
        proposed[key] += 1
    for key in impacts:
        impacts[key]["proposed_weight"] = proposed[key]
        delta = proposed[key] - impacts[key]["current_weight"]
        impacts[key]["change_reason"] = (
            f"相関シグナルに基づく提案（差分{delta:+d}）。自動反映は行いません。"
        )
    return {
        "status": "proposal_only",
        "sample_size": sample_size,
        "weights": proposed,
        "item_details": impacts,
        "auto_applied": False,
        "note": "recommended_weightsは提案のみ。原田さんの承認なしに配点へ反映しません。",
    }


def _top_conditions(records: list[dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
    from .aggregation import group_performance, score_band

    bands = group_performance(records, lambda r: score_band(r["prediction_score"]))
    ranked = []
    for band, stats in bands.items():
        if stats["n"] >= 2 and stats["hit_rate"] is not None:
            ranked.append({"condition": f"prediction_score={band}", **stats})
    ranked.sort(key=lambda x: (x["hit_rate"], x["return_rate"] or 0), reverse=reverse)
    return ranked[:3]


def _miss_trends(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {r: 0 for r in sorted(MISS_REASONS)}
    for record in records:
        if record["result"]["status"] != "ハズレ":
            continue
        primary = record["result"].get("primary_miss_reason")
        if primary in counts:
            counts[primary] += 1
    return {k: v for k, v in counts.items() if v > 0}


def _overbetting_check(records: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    max_pts = rules["max_combinations_per_race"]
    high_point = [r for r in records if r.get("ticket_count", 0) >= max_pts]
    perf_high = performance(high_point)
    perf_all = performance(records)
    return {
        "races_at_max_points": len(high_point),
        "max_points_hit_rate": perf_high["hit_rate"],
        "overall_hit_rate": perf_all["hit_rate"],
        "warning": len(high_point) > len(records) * 0.4,
        "message": "買い目上限付近が多い場合は的中率・回収率を確認してください",
    }


def _return_drag(records: list[dict[str, Any]]) -> list[str]:
    factors: list[str] = []
    losses = [r for r in records if r["result"]["status"] == "ハズレ"]
    if len(losses) > len(records) * 0.7:
        factors.append("ハズレ率が高く回収率を押し下げています")
    high_stake = sum(r["result"]["stake"] for r in records if r.get("ticket_count", 0) >= 9)
    total_stake = sum(r["result"]["stake"] for r in records)
    if total_stake and high_stake / total_stake > 0.5:
        factors.append("9点以上のレース投資比率が高い")
    axis_miss = sum(
        1
        for r in losses
        if r["result"].get("primary_miss_reason") == "axis_miss"
    )
    if losses and axis_miss / len(losses) > 0.4:
        factors.append("軸外しがハズレの主因")
    return factors or ["特筆すべき要因は未検出"]
