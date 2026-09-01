from __future__ import annotations

from typing import Any

from .aggregation import aggregate_periods, performance
from .tickets import expand_tickets


def format_prediction_report(
    *,
    sport_label: str,
    date: str,
    selected: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    sheet_status: str,
) -> str:
    lines = [
        f"# {sport_label} 予想報告（{date}）",
        "",
        "## 本日の対象",
        f"- 競技: {sport_label}",
        f"- 選定レース数: {len(selected)}",
        f"- 見送り: {len(skipped)}レース",
        "",
    ]
    if skipped:
        lines.append("## 見送ったレース")
        for item in skipped:
            lines.append(
                f"- {item.get('venue')}{item.get('race')}R "
                f"（スコア{item.get('prediction_score', '-')}）: {item.get('skip_reason', '基準未達')}"
            )
        lines.append("")
    lines.append("## 選定レースの予想")
    total_points = 0
    for idx, pred in enumerate(selected, start=1):
        tickets = pred.get("tickets", [])
        expanded = expand_tickets(tickets) if tickets else []
        pts = sum(len(t.combinations) for t in expanded)
        total_points += pts
        main = [t for t in expanded if t.kind == "本線"]
        cover = [t for t in expanded if t.kind == "抑え"]
        lines.extend(
            [
                f"### 予想{idx}: {pred.get('venue')}{pred.get('race')}R",
                f"- 締切: {pred.get('close_time', '-')}",
                f"- 狙い: {pred.get('target')} / 自信度: {pred.get('confidence')}",
                f"- 予想しやすさスコア: {pred.get('prediction_score')}",
                f"- 軸: {pred.get('axis', '-')}",
                f"- 本線: {', '.join(t.compact for t in main) or 'なし'}",
                f"- 抑え: {', '.join(t.compact for t in cover) or 'なし'}",
                f"- 合計点数: {pts}点",
                f"- 根拠: {pred.get('rationale', pred.get('explanation', '-'))}",
                f"- 想定展開: {pred.get('scenario', '-')}",
                f"- リスク: {pred.get('risks', '-')}",
                "",
            ]
        )
    lines.extend(
        [
            "## シート記載",
            sheet_status,
            "",
            f"## サマリー",
            f"- 総レース数: {len(selected)}",
            f"- 総点数: {total_points}点（1点100円 = {total_points * 100}円）",
        ]
    )
    return "\n".join(lines)


def format_result_report(
    *,
    sport_label: str,
    date: str,
    records: list[dict[str, Any]],
    all_records: list[dict[str, Any]],
    sheet_status: str,
) -> str:
    day_records = [r for r in records if r["date"] == date and r.get("result")]
    periods = aggregate_periods(all_records, date)
    lines = [
        f"# {sport_label} 結果報告（{date}）",
        "",
        "## 各レース結果",
    ]
    for record in day_records:
        result = record["result"]
        review = record.get("review", {})
        lines.extend(
            [
                f"### {record.get('venue')}{record.get('race')}R",
                f"- 結果: {result.get('trifecta')} / {result.get('status')}",
                f"- 払戻: {result.get('payout')}円 / 購入: {result.get('stake')}円（{record.get('ticket_count')}点）",
                f"- ハズレ理由: {result.get('primary_miss_reason') or '-'}",
            ]
        )
        if review.get("close_miss"):
            lines.append("- 惜しいハズレ: はい")
        lines.append(f"- 反省: {'; '.join(review.get('improvements', []))}")
        lines.append("")
    today = periods["today"]
    all_perf = periods["all"]
    lines.extend(
        [
            "## 集計",
            f"- 当日的中率: {_pct(today['hit_rate'])} ({today['hits']}/{today['n']})",
            f"- 当日回収率: {_pct(today['return_rate'])}",
            f"- 累計的中率: {_pct(all_perf['hit_rate'])} ({all_perf['hits']}/{all_perf['n']})",
            f"- 累計回収率: {_pct(all_perf['return_rate'])}",
            "",
            "## シート・学習",
            sheet_status,
        ]
    )
    return "\n".join(lines)


def format_learning_report_text(report: dict[str, Any]) -> str:
    rw = report.get("recommended_weights", {})
    lines = [
        f"# 学習レポート（{report.get('sport')}）",
        "",
        f"- 現在のレース数: {report.get('race_count', 0)}",
        f"- 100レースまでの残り: {report.get('remaining_to_threshold', 0)}",
        f"- 自動配点変更: {'可能' if report.get('auto_change_allowed') else '不可（収集フェーズ）'}",
        "",
        "## 成績が良い条件",
    ]
    for item in report.get("good_conditions", []):
        lines.append(
            f"- {item['condition']}: 的中率{_pct(item.get('hit_rate'))}, "
            f"回収率{_pct(item.get('return_rate'))} (n={item['n']})"
        )
    lines.append("\n## 成績が悪い条件")
    for item in report.get("bad_conditions", []):
        lines.append(
            f"- {item['condition']}: 的中率{_pct(item.get('hit_rate'))}, "
            f"回収率{_pct(item.get('return_rate'))} (n={item['n']})"
        )
    lines.append("\n## ハズレ理由の傾向")
    for reason, count in report.get("miss_reason_trends", {}).items():
        lines.append(f"- {reason}: {count}件")
    ob = report.get("overbetting_check", {})
    lines.extend(
        [
            "",
            "## 買い目過多チェック",
            f"- 上限点数レース: {ob.get('races_at_max_points', 0)}",
            f"- 警告: {'あり' if ob.get('warning') else 'なし'}",
            "",
            "## 回収率を下げる要因",
        ]
    )
    for factor in report.get("return_rate_drag_factors", []):
        lines.append(f"- {factor}")
    lines.extend(
        [
            "",
            "## recommended_weights（提案のみ）",
            f"- ステータス: {rw.get('status')}",
            f"- 自動反映: {rw.get('auto_applied', False)} ← 原田さん承認前は反映しません",
        ]
    )
    if rw.get("item_details"):
        for key, detail in rw["item_details"].items():
            lines.append(
                f"  - {key}: {detail.get('current_weight')} → {detail.get('proposed_weight')} "
                f"（{detail.get('change_reason', '')}）"
            )
    return "\n".join(lines)


def format_summary_report(
    records_by_sport: dict[str, list[dict[str, Any]]],
    date: str,
) -> str:
    from common.constants import SPORT_LABELS, SPORTS

    lines = [f"# 全体成績報告（{date}）", "", "各競技の学習・成績は混ぜていません。"]
    for sport in SPORTS:
        records = records_by_sport.get(sport, [])
        done = [r for r in records if r.get("result") and r["result"]["status"] != "未実施"]
        day = [
            r
            for r in done
            if r.get("date") == date
        ]
        total = performance(done)
        today = performance(day)
        lines.extend(
            [
                "",
                f"## {SPORT_LABELS[sport]}",
                f"- 当日: 的中率{_pct(today['hit_rate'])} / 回収率{_pct(today['return_rate'])}",
                f"- 累計: 的中率{_pct(total['hit_rate'])} / 回収率{_pct(total['return_rate'])} (n={total['n']})",
            ]
        )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"
