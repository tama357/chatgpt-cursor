"""GitHub Actions の実行結果サマリー。秘密情報は出さない。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from common.constants import SPORT_LABELS, SPORTS
from common.state import find_day_records, load_json


def collect_day_stats(base_dir: Path, target_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sport in SPORTS:
        state = load_json(base_dir / "data" / sport / "state.json")
        records = [
            r
            for r in find_day_records(state, target_date)
            if not r.get("skipped") and r.get("tickets")
        ]
        done = [r for r in records if (r.get("result") or {}).get("trifecta")]
        hits = [r for r in done if r.get("result", {}).get("status") == "的中"]
        stake = sum(int((r.get("result") or {}).get("stake") or 0) for r in done)
        payout = sum(int((r.get("result") or {}).get("payout") or 0) for r in done)
        points = sum(int(r.get("ticket_count") or 0) for r in records)
        pending = len(records) - len(done)
        rows.append(
            {
                "sport": sport,
                "label": SPORT_LABELS[sport],
                "selected": len(records),
                "races": [f"{r.get('venue')}{r.get('race')}R" for r in records],
                "points": points,
                "results_done": len(done),
                "results_pending": pending,
                "hits": len(hits),
                "stake": stake,
                "payout": payout,
                "hit_rate": (len(hits) / len(done) * 100) if done else None,
                "recovery": (payout / stake * 100) if stake else None,
                "fetch_failures": [
                    f
                    for f in (state.get("fetch_failures") or [])
                    if isinstance(f, dict) and f.get("date") == target_date
                ],
            }
        )
    return rows


def format_github_summary(
    *,
    title: str,
    target_date: str,
    stats: list[dict[str, Any]] | None = None,
    drive_ok: bool | None = None,
    drive_note: str = "",
    extra_lines: list[str] | None = None,
) -> str:
    lines = [f"## {title}", "", f"- 対象日: {target_date}"]
    if drive_ok is True:
        lines.append("- Drive更新: 成功")
    elif drive_ok is False:
        lines.append("- Drive更新: 失敗")
    if drive_note:
        lines.append(f"- Driveメモ: {drive_note}")
    if stats:
        lines.extend(
            [
                "",
                "| 競技 | 選定 | 点数 | 結果取得 | 的中 | 的中率 | 回収率 |",
                "|------|------|------|----------|------|--------|--------|",
            ]
        )
        for row in stats:
            hit_rate = f"{row['hit_rate']:.1f}%" if row["hit_rate"] is not None else "-"
            recovery = f"{row['recovery']:.1f}%" if row["recovery"] is not None else "-"
            lines.append(
                f"| {row['label']} | {row['selected']} | {row['points']} | "
                f"{row['results_done']}/"
                f"{row['selected'] or 0} | {row['hits']} | {hit_rate} | {recovery} |"
            )
        lines.append("")
        for row in stats:
            if row["races"]:
                lines.append(f"- {row['label']} 選定レース: {', '.join(row['races'])}")
            if row["results_pending"]:
                lines.append(f"- {row['label']}: 未取得 {row['results_pending']}レース（処理済みにしていません）")
    if extra_lines:
        lines.append("")
        lines.extend(extra_lines)
    lines.append("")
    lines.append("秘密鍵・トークン・サービスアカウントJSONは表示していません。")
    return "\n".join(lines) + "\n"


def write_github_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
