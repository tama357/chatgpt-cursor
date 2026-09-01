#!/usr/bin/env python3
"""個人利用 競馬・競輪 予想・記録・集計・復習・学習システム（手動入力版）。

提出用競輪（競輪予想/）とは完全分離。外部送信は行わない。
レースデータ・結果JSONは手動配置が必要。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from common.aggregation import aggregate_periods, build_analysis  # noqa: E402
from common.learning import build_learning_report  # noqa: E402
from common.reporting import (  # noqa: E402
    format_learning_report_text,
    format_prediction_report,
    format_result_report,
    format_summary_report,
)
from common.review import analyze_review  # noqa: E402
from common.state import (  # noqa: E402
    find_day_records,
    get_records,
    is_processed,
    load_json,
    mark_processed,
    save_json,
    upsert_record,
    validate_prediction_record,
    validate_result_record,
)
from common.tickets import ValidationError, check_hit, count_tickets  # noqa: E402
from excel.io import write_predictions, write_results, write_summary  # noqa: E402
from excel.templates import ensure_workbooks, init_excel  # noqa: E402
from fetch import keiba as fetch_keiba  # noqa: E402
from fetch import keirin as fetch_keirin  # noqa: E402
from predict.builder import build_prediction  # noqa: E402
from predict.scorer import select_races  # noqa: E402

SPORT_LABELS = {"keiba": "競馬", "keirin": "競輪（個人検証）"}
CONFIG_FILES = {
    "keiba": ROOT / "config" / "keiba_rules.json",
    "keirin": ROOT / "config" / "keirin_rules.json",
}


def load_rules(sport: str) -> dict[str, Any]:
    with CONFIG_FILES[sport].open(encoding="utf-8") as handle:
        return json.load(handle)


def state_path(sport: str) -> Path:
    return ROOT / "data" / sport / "state.json"


def run_predict(sport: str, target_date: str, *, force: bool = False) -> str:
    rules = load_rules(sport)
    state = load_json(state_path(sport))
    state["sport"] = rules["sport"]
    key = f"predict:{target_date}"
    payload = {"date": target_date, "sport": sport}

    if not force and is_processed(state, key, payload):
        existing = find_day_records(state, target_date)
        if existing:
            return (
                f"⚠ 二重登録防止: {target_date} の{sport}予想は処理済みです。"
                f"再実行する場合は --force を付けてください。"
                f"\n\n既存 {len(existing)} レース"
            )

    ensure_workbooks(ROOT)
    excel = ensure_workbooks(ROOT)
    if sport == "keiba":
        races = fetch_keiba.fetch_races(ROOT, target_date)
        entry = excel["keiba_entry"]
    else:
        races = fetch_keirin.fetch_races(ROOT, target_date)
        entry = excel["keirin_entry"]

    if not races:
        return (
            f"【手動入力版】レースデータがありません。\n"
            f" {ROOT}/data/races/{sport}/{target_date}.json を配置してください。\n"
            f" テスト時は examples/{sport}_races.sample.json を参照します。"
        )

    selected, skipped = select_races(races, rules)
    predictions: list[dict[str, Any]] = []
    for idx, candidate in enumerate(selected, start=1):
        pred = build_prediction(candidate, rules, idx)
        pred["date"] = target_date
        validate_prediction_record(pred, rules)
        upsert_record(state, pred)
        predictions.append(pred)

    for skip in skipped:
        if skip.get("skip_reason") and skip.get("venue"):
            upsert_record(
                state,
                {
                    "date": target_date,
                    "sport": rules["sport"],
                    "venue": skip.get("venue"),
                    "race": skip.get("race"),
                    "skipped": True,
                    "skip_reason": skip.get("skip_reason"),
                    "prediction_score": skip.get("prediction_score"),
                },
            )

    sheet_status = write_predictions(entry, target_date, predictions)
    mark_processed(state, key, payload)
    save_json(state_path(sport), state)

    report = format_prediction_report(
        sport_label=SPORT_LABELS[sport],
        date=target_date,
        selected=predictions,
        skipped=skipped,
        sheet_status=sheet_status,
    )
    max_pts = rules["max_combinations_per_race"]
    over = [p for p in predictions if p.get("ticket_count", 0) > max_pts]
    if over:
        report += "\n\n⚠ 点数上限超過: " + ", ".join(
            f"{p['venue']}{p['race']}R({p['ticket_count']}点)" for p in over
        )
    min_pts = rules.get("min_combinations_per_race", 1)
    under = [p for p in predictions if p.get("ticket_count", 0) < min_pts]
    if under and sport == "keiba":
        report += "\n\n⚠ 競馬目安点数未満: " + ", ".join(
            f"{p['venue']}{p['race']}R({p['ticket_count']}点)" for p in under
        )
    report += "\n\n※ 予想しやすさスコア(prediction_score)はExcel列がないため、解説文とstate.jsonに保存します。"
    return report


def run_results(sport: str, target_date: str, *, force: bool = False) -> str:
    rules = load_rules(sport)
    state = load_json(state_path(sport))
    key = f"results:{target_date}"
    payload = {"date": target_date, "sport": sport}

    day_records = [
        r
        for r in find_day_records(state, target_date)
        if not r.get("skipped") and r.get("tickets")
    ]
    if not day_records:
        return f"{target_date} の{sport}予想記録がありません。先に予想を実行してください。"

    pending = [r for r in day_records if not r.get("result")]
    if pending:
        names = ", ".join(f"{r['venue']}{r['race']}R" for r in pending)
        return (
            f"結果未確定のレースがあります: {names}\n"
            f"推測で記載しません。 data/results/{sport}/{target_date}.json に"
            f"正式結果を配置してから再実行してください。"
        )

    if not force and is_processed(state, key, payload):
        return f"⚠ 二重登録防止: {target_date} の{sport}結果処理は済みです。--force で再実行可。"

    ensure_workbooks(ROOT)
    excel = ensure_workbooks(ROOT)
    entry = excel[f"{sport}_entry"]
    summary = excel[f"{sport}_summary"]

    result_items: list[dict[str, Any]] = []
    for record in day_records:
        result = record.get("result")
        if not result or not result.get("trifecta"):
            continue
        review = analyze_review(record, result["trifecta"])
        record["review"] = review
        if result["status"] == "ハズレ" and not result.get("primary_miss_reason"):
            result["primary_miss_reason"] = review.get("primary_miss_reason")
            result["secondary_miss_reasons"] = review.get("secondary_miss_reasons", [])
            result["close_miss"] = review.get("close_miss", False)
        record["learning"] = {
            "fetched_data": record.get("fetched_data"),
            "prediction_score": record.get("prediction_score"),
            "confidence": record.get("confidence"),
            "axis": record.get("axis"),
            "tickets": record.get("tickets"),
            "ticket_count": record.get("ticket_count"),
            "odds_band_median": record.get("odds_band_median"),
            "result": result,
            "review": review,
            "prediction_logic_version": record.get("prediction_logic_version"),
        }
        validate_result_record(record)
        upsert_record(state, record)
        result_items.append(record)

    sheet1 = write_results(
        entry,
        target_date,
        [{"number": r["number"], "result": r["result"], "ticket_count": r["ticket_count"]} for r in result_items],
    )
    sheet2 = write_summary(summary, target_date, result_items)
    mark_processed(state, key, payload)
    save_json(state_path(sport), state)

    return format_result_report(
        sport_label=SPORT_LABELS[sport],
        date=target_date,
        records=result_items,
        all_records=get_records(state, with_result=True),
        sheet_status=f"{sheet1}\n{sheet2}",
    )


def apply_results_from_file(sport: str, target_date: str, results_file: Path) -> str:
    """結果JSONをstateへ反映してから run_results を実行。"""
    state = load_json(state_path(sport))
    with results_file.open(encoding="utf-8") as handle:
        data = json.load(handle)
    results = data.get("results", [])
    by_race = {(r.get("venue"), r.get("race")): r for r in results}

    for record in find_day_records(state, target_date):
        if record.get("skipped"):
            continue
        key = (record.get("venue"), record.get("race"))
        if key not in by_race:
            continue
        raw = by_race[key]
        trifecta = raw["trifecta"]
        hit = check_hit(trifecta, record["tickets"])
        stake = record["ticket_count"] * 100
        payout = raw.get("payout", 0) if hit else 0
        if hit and payout <= 0:
            raise ValidationError(f"{key}: 的中時は払戻金が必要です")
        record["result"] = {
            "trifecta": trifecta,
            "status": "的中" if hit else "ハズレ",
            "payout": payout,
            "stake": stake,
            "points": record["ticket_count"],
            "primary_miss_reason": None if hit else raw.get("primary_miss_reason"),
            "secondary_miss_reasons": [] if hit else raw.get("secondary_miss_reasons", []),
            "scenario_realized": raw.get("scenario_realized"),
        }
        upsert_record(state, record)
    save_json(state_path(sport), state)
    return run_results(sport, target_date)


def run_learning_report(sport: str) -> str:
    rules = load_rules(sport)
    state = load_json(state_path(sport))
    records = get_records(state, with_result=True)
    report = build_learning_report(records, rules)
    report_path = ROOT / "data" / sport / "learning_report.json"
    save_json(report_path, report)
    text = format_learning_report_text(report)
    analysis = build_analysis(records)
    text += "\n\n## 詳細分析\n"
    text += json.dumps(analysis, ensure_ascii=False, indent=2)
    return text


def run_summary(target_date: str) -> str:
    kb = load_json(state_path("keiba"))
    kr = load_json(state_path("keirin"))
    return format_summary_report(kb.get("records", []), kr.get("records", []), target_date)


def init_excel_cmd() -> str:
    return init_excel(ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は今日）")
    common.add_argument("--force", action="store_true", help="二重登録防止を上書き")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in (
        "predict-keiba",
        "predict-keirin",
        "predict-all",
        "results-keiba",
        "results-keirin",
        "results-all",
        "learning-keiba",
        "learning-keirin",
        "report-all",
        "init-excel",
    ):
        sub.add_parser(name, parents=[common])

    apply = sub.add_parser("apply-results", parents=[common])
    apply.add_argument("sport", choices=["keiba", "keirin"])
    apply.add_argument("results_file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_date = args.date or datetime.now().strftime("%Y-%m-%d")
    try:
        if args.command == "init-excel":
            print(init_excel_cmd())
        elif args.command == "predict-keiba":
            print(run_predict("keiba", target_date, force=args.force))
        elif args.command == "predict-keirin":
            print(run_predict("keirin", target_date, force=args.force))
        elif args.command == "predict-all":
            print(run_predict("keiba", target_date, force=args.force))
            print("\n---\n")
            print(run_predict("keirin", target_date, force=args.force))
        elif args.command == "results-keiba":
            print(run_results("keiba", target_date, force=args.force))
        elif args.command == "results-keirin":
            print(run_results("keirin", target_date, force=args.force))
        elif args.command == "results-all":
            print(run_results("keiba", target_date, force=args.force))
            print("\n---\n")
            print(run_results("keirin", target_date, force=args.force))
        elif args.command == "learning-keiba":
            print(run_learning_report("keiba"))
        elif args.command == "learning-keirin":
            print(run_learning_report("keirin"))
        elif args.command == "report-all":
            print(run_summary(target_date))
        elif args.command == "apply-results":
            print(apply_results_from_file(args.sport, target_date, args.results_file))
        return 0
    except (ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
