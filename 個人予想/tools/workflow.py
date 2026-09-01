#!/usr/bin/env python3
"""個人利用 中央競馬・地方競馬・競艇 予想・記録・集計・復習・学習システム。

提出用競輪（競輪予想/）とは完全分離。外部送信は行わない。
原田さんは Cursor チャットのみ。JSON作成・コマンド入力は Cursor が実行する。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common.jst import today_str as jst_today_str

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from common.aggregation import build_analysis  # noqa: E402
from common.constants import (  # noqa: E402
    RULE_FILES,
    SPORT_EXCEL_KEYS,
    SPORT_LABELS,
    SPORTS,
)
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
from excel.drive_sync import DriveAuthError, sync_excel_files  # noqa: E402
from cloud_runner import (  # noqa: E402
    record_fetch_failure,
    run_cloud_predict,
    run_cloud_results,
    run_verify_drive,
)
from fetch import jra as fetch_jra  # noqa: E402
from fetch import nar as fetch_nar  # noqa: E402
from fetch import kyotei as fetch_kyotei  # noqa: E402
from fetch.race_builder import (  # noqa: E402
    is_official_result_file,
    load_official_results,
    load_races_from_file,
    result_data_path,
    save_races_json,
)
from orchestrator import (  # noqa: E402
    ensure_result_data,
    run_predict_today,
    run_results_yesterday,
)
from predict.builder import build_prediction  # noqa: E402
from predict.scorer import select_races  # noqa: E402

CONFIG_FILES = {sport: ROOT / "config" / filename for sport, filename in RULE_FILES.items()}
FETCHERS = {"jra": fetch_jra, "nar": fetch_nar, "kyotei": fetch_kyotei}
UNSUPPORTED = "未対応の競技です: {sport}（個人予想は中央競馬・地方競馬・競艇のみ）"


def load_rules(sport: str) -> dict[str, Any]:
    with CONFIG_FILES[sport].open(encoding="utf-8") as handle:
        return json.load(handle)


def state_path(sport: str) -> Path:
    return ROOT / "data" / sport / "state.json"


def run_predict(
    sport: str,
    target_date: str,
    *,
    force: bool = False,
    sync_drive: bool = True,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> str:
    if sport not in CONFIG_FILES:
        return UNSUPPORTED.format(sport=sport)
    rules = load_rules(sport)
    state = load_json(state_path(sport))
    state["sport"] = rules["sport"]
    key = f"predict:{target_date}"
    payload = {"date": target_date, "sport": sport}
    label = SPORT_LABELS[sport]

    if not force and is_processed(state, key, payload):
        existing = find_day_records(state, target_date)
        if existing:
            return (
                f"⚠ 二重登録防止: {target_date} の{label}予想は処理済みです。"
                f"再実行する場合は --force を付けてください。"
                f"\n\n既存 {len(existing)} レース"
            )

    ensure_workbooks(ROOT)
    excel = ensure_workbooks(ROOT)
    outcome_fn = getattr(FETCHERS[sport], "fetch_races_outcome", None)
    if outcome_fn:
        outcome = outcome_fn(ROOT, target_date, allow_sample=allow_sample, try_auto=try_auto)
        races = list(outcome.get("races") or [])
        status_code = outcome.get("status") or ("ok" if races else "fetch_failed")
        fetch_error = outcome.get("error")
    else:
        races = FETCHERS[sport].fetch_races(
            ROOT, target_date, allow_sample=allow_sample, try_auto=try_auto
        )
        status_code = "ok" if races else "fetch_failed"
        fetch_error = None
    entry = excel[f"{sport}_entry"]

    if not races:
        if status_code == "fetch_failed":
            record_fetch_failure(state, date=target_date, reason=fetch_error or "取得失敗")
            save_json(state_path(sport), state)
            return (
                f"【取得失敗】{label}の出走情報を取得できませんでした。サンプルデータは使いません。"
                " この競技の予想は中止します。"
            )
        if sport == "jra" or status_code == "no_meeting":
            return (
                f"【開催なし】{target_date} は{label}の開催日ではありません。"
                + (" 中央競馬は開催日のみ予想します。" if sport == "jra" else "")
            )
        record_fetch_failure(state, date=target_date, reason="取得失敗")
        save_json(state_path(sport), state)
        return (
            f"【取得失敗】{label}の出走情報を取得できませんでした。サンプルデータは使いません。"
            " この競技の予想は中止します。"
        )

    selected, skipped = select_races(races, rules)
    predictions: list[dict[str, Any]] = []
    for idx, candidate in enumerate(selected, start=1):
        pred = build_prediction(candidate, rules, idx)
        pred["date"] = target_date
        pred["sport"] = rules["sport"]
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
        sport_label=label,
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
    if under:
        report += "\n\n⚠ 目安点数未満: " + ", ".join(
            f"{p['venue']}{p['race']}R({p['ticket_count']}点)" for p in under
        )
    report += "\n\n※ 予想しやすさスコア(prediction_score)はExcel列がないため、解説文とstate.jsonに保存します。"
    if sync_drive:
        report += "\n\n" + sync_drive_cmd(keys=SPORT_EXCEL_KEYS[sport])
    return report


def run_results(sport: str, target_date: str, *, force: bool = False, sync_drive: bool = True) -> str:
    if sport not in CONFIG_FILES:
        return UNSUPPORTED.format(sport=sport)
    rules = load_rules(sport)
    state = load_json(state_path(sport))
    key = f"results:{target_date}"
    payload = {"date": target_date, "sport": sport}
    label = SPORT_LABELS[sport]

    day_records = [
        r
        for r in find_day_records(state, target_date)
        if not r.get("skipped") and r.get("tickets")
    ]
    if not day_records:
        return f"{target_date} の{label}予想記録がありません。先に予想を実行してください。"

    pending = [r for r in day_records if not r.get("result")]
    if pending and not any(r.get("result") for r in day_records):
        fetched, _fetch_status = ensure_result_data(ROOT, sport, target_date, day_records)
        official_path = result_data_path(ROOT, sport, target_date)
        rows = fetched or (
            load_official_results(official_path) if is_official_result_file(official_path) else []
        )
        if rows:
            _apply_result_rows(state, target_date, rows)
            save_json(state_path(sport), state)
            day_records = [
                r
                for r in find_day_records(state, target_date)
                if not r.get("skipped") and r.get("tickets")
            ]
            pending = [r for r in day_records if not r.get("result")]

    pending_note = ""
    if pending and not any(r.get("result") for r in day_records):
        names = ", ".join(f"{r['venue']}{r['race']}R" for r in pending)
        record_fetch_failure(state, date=target_date, reason=f"正式結果なし: {names}")
        save_json(state_path(sport), state)
        return (
            f"【取得失敗】{label}の正式結果を取得できませんでした: {names}\n"
            "推測では記入しません。この競技の結果処理は中止します。"
        )
    if pending:
        names = ", ".join(f"{r['venue']}{r['race']}R" for r in pending)
        record_fetch_failure(state, date=target_date, reason=f"一部未取得: {names}")
        pending_note = f"\n\n【取得失敗・一部】未確定: {names}（推測では記入していません）"

    if not force and is_processed(state, key, payload):
        return f"⚠ 二重登録防止: {target_date} の{label}結果処理は済みです。--force で再実行可。"

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
            "sport": sport,
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

    base_report = format_result_report(
        sport_label=label,
        date=target_date,
        records=result_items,
        all_records=get_records(state, with_result=True),
        sheet_status=f"{sheet1}\n{sheet2}",
    )
    if sync_drive:
        return base_report + pending_note + "\n\n" + sync_drive_cmd(keys=SPORT_EXCEL_KEYS[sport])
    return base_report + pending_note


def _apply_result_rows(state: dict[str, Any], target_date: str, results: list[dict[str, Any]]) -> None:
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


def apply_results_from_file(
    sport: str, target_date: str, results_file: Path, *, sync_drive: bool = True
) -> str:
    """結果JSONをstateへ反映してから run_results を実行。"""
    state = load_json(state_path(sport))
    with results_file.open(encoding="utf-8") as handle:
        data = json.load(handle)
    _apply_result_rows(state, target_date, data.get("results", []))
    save_json(state_path(sport), state)
    return run_results(sport, target_date, sync_drive=sync_drive)


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
    by_sport = {sport: load_json(state_path(sport)).get("records", []) for sport in SPORTS}
    return format_summary_report(by_sport, target_date)


def init_excel_cmd() -> str:
    return init_excel(ROOT)


def sync_drive_cmd(*, keys: list[str] | None = None) -> str:
    try:
        report = sync_excel_files(ROOT, keys=keys)
    except DriveAuthError as exc:
        return (
            "## Google Drive 同期\n\n"
            f"❌ Drive同期失敗: {exc}\n\n"
            "ローカルExcelのみ更新されています。"
            " 今回の仕様では Drive へはアップロードしません。"
        )
    return report.format_report()


def save_races_cmd(sport: str, target_date: str, races_file: Path) -> str:
    races = load_races_from_file(races_file)
    path = save_races_json(ROOT, sport, target_date, races, source="cursor_web")
    return f"レースJSONを保存しました: {path}（{len(races)}レース）"


def _run_all(fn, target_date: str, *, force: bool = False) -> str:
    parts = [fn(sport, target_date, force=force) for sport in SPORTS]
    return "\n\n---\n\n".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は今日）")
    common.add_argument("--force", action="store_true", help="二重登録防止を上書き")
    # --allow-sample は意図的に無い。CLI / predict-today からサンプルは使えない。
    sub = parser.add_subparsers(dest="command", required=True)

    for name in (
        "predict-today",
        "results-yesterday",
        "predict-jra",
        "predict-nar",
        "predict-kyotei",
        "predict-all",
        "results-jra",
        "results-nar",
        "results-kyotei",
        "results-all",
        "learning-jra",
        "learning-nar",
        "learning-kyotei",
        "report-all",
        "init-excel",
        "sync-drive",
        "verify-drive",
        "cloud-predict",
        "cloud-results",
    ):
        sub.add_parser(name, parents=[common])

    apply = sub.add_parser("apply-results", parents=[common])
    apply.add_argument("sport", choices=list(SPORTS))
    apply.add_argument("results_file", type=Path)

    save_races = sub.add_parser("save-races", parents=[common])
    save_races.add_argument("sport", choices=list(SPORTS))
    save_races.add_argument("races_file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_date = args.date or jst_today_str()
    try:
        if args.command == "init-excel":
            print(init_excel_cmd())
        elif args.command == "sync-drive":
            print(sync_drive_cmd())
        elif args.command == "verify-drive":
            print(run_verify_drive(ROOT))
        elif args.command == "cloud-predict":
            print(
                run_cloud_predict(
                    ROOT,
                    target_date=args.date,
                    force=args.force,
                    run_predict_today_fn=run_predict_today,
                    run_predict_fn=run_predict,
                )
            )
        elif args.command == "cloud-results":
            print(
                run_cloud_results(
                    ROOT,
                    target_date=args.date,
                    force=args.force,
                    run_results_yesterday_fn=run_results_yesterday,
                    apply_results_fn=apply_results_from_file,
                    run_results_fn=run_results,
                    run_learning_fn=run_learning_report,
                    find_day_records_fn=find_day_records,
                    load_state_fn=lambda sport: load_json(state_path(sport)),
                )
            )
        elif args.command == "predict-today":
            print(
                run_predict_today(
                    ROOT,
                    target_date=args.date,
                    force=args.force,
                    run_predict_fn=run_predict,
                )
            )
        elif args.command == "results-yesterday":
            print(
                run_results_yesterday(
                    ROOT,
                    target_date=args.date,
                    force=args.force,
                    apply_results_fn=apply_results_from_file,
                    run_results_fn=run_results,
                    run_learning_fn=run_learning_report,
                    find_day_records_fn=find_day_records,
                    load_state_fn=lambda sport: load_json(state_path(sport)),
                )
            )
        elif args.command == "predict-jra":
            print(run_predict("jra", target_date, force=args.force))
        elif args.command == "predict-nar":
            print(run_predict("nar", target_date, force=args.force))
        elif args.command == "predict-kyotei":
            print(run_predict("kyotei", target_date, force=args.force))
        elif args.command == "predict-all":
            print(_run_all(run_predict, target_date, force=args.force))
        elif args.command == "results-jra":
            print(run_results("jra", target_date, force=args.force))
        elif args.command == "results-nar":
            print(run_results("nar", target_date, force=args.force))
        elif args.command == "results-kyotei":
            print(run_results("kyotei", target_date, force=args.force))
        elif args.command == "results-all":
            print(_run_all(run_results, target_date, force=args.force))
        elif args.command == "learning-jra":
            print(run_learning_report("jra"))
        elif args.command == "learning-nar":
            print(run_learning_report("nar"))
        elif args.command == "learning-kyotei":
            print(run_learning_report("kyotei"))
        elif args.command == "report-all":
            print(run_summary(target_date))
        elif args.command == "apply-results":
            print(apply_results_from_file(args.sport, target_date, args.results_file))
        elif args.command == "save-races":
            print(save_races_cmd(args.sport, target_date, args.races_file))
        return 0
    except (ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
