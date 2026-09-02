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
    DAY_STATUS_FETCH_FAILED,
    DAY_STATUS_NO_MEETING,
    DEFAULT_START_DATE,
    LEARNING_JSON_UNSAVED,
    RULE_FILES,
    SPORT_EXCEL_KEYS,
    SPORT_LABELS,
    SPORTS,
)
from common.daily_json import (  # noqa: E402
    apply_results_doc_to_records,
    build_predictions_payload,
    build_results_payload,
    count_completed_from_inbox,
    empty_day_payload,
    has_predicted_races,
    is_before_learning_start,
    load_daily_json,
    load_predictions_doc,
    load_results_doc,
    make_race_id,
    merge_result_races,
    prediction_reread_problems,
    predictions_path,
    records_from_predictions_doc,
    remaining_to_100,
    results_cover_predictions,
    results_path,
    results_reread_problems,
    save_daily_json,
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
    init_personal_states,
    load_canonical_state,
    load_json,
    require_production_states,
    records_since_start,
    save_json,
    skip_before_start_message,
    upsert_record,
    validate_prediction_record,
    validate_result_record,
)
from excel.drive_inbox import upsert_inbox_file  # noqa: E402
from common.tickets import ValidationError, check_hit, count_tickets  # noqa: E402
from excel.io import write_predictions, write_results, write_summary  # noqa: E402
from excel.templates import ensure_workbooks, init_excel  # noqa: E402
from excel.drive_sync import DriveAuthError, sync_excel_files  # noqa: E402
from cloud_runner import (  # noqa: E402
    CloudJobError,
    run_bootstrap_cloud,
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
    save_results_json,
)
from orchestrator import (  # noqa: E402
    _result_key,
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


def _skip_before(date: str, *, kind: str) -> str:
    return skip_before_start_message(
        {"start_date": DEFAULT_START_DATE}, date, kind=kind
    )


def _learning_json_notes(
    *,
    sport: str,
    path: Path,
    payload: dict[str, Any],
    problems: list[str],
    sync_inbox: bool,
    kind: str,
) -> str:
    lines: list[str] = []
    if problems:
        lines.append(f"{LEARNING_JSON_UNSAVED}（ローカル再読失敗: {'; '.join(problems)}）")
        return "\n".join(lines)
    lines.append(f"学習JSON保存: {path.name}")
    if not sync_inbox:
        return "\n".join(lines)

    def _check(loaded: dict[str, Any]) -> list[str]:
        if kind == "predictions":
            return prediction_reread_problems(loaded, payload)
        return results_reread_problems(loaded, payload)

    item = upsert_inbox_file(ROOT, sport, path, reread_check=_check)
    if item.status != "success":
        lines.append(f"{LEARNING_JSON_UNSAVED}（{item.message}）")
    else:
        lines.append(f"Drive inbox更新: {path.name}")
    return "\n".join(lines)


def _write_predictions_json(
    sport: str,
    payload: dict[str, Any],
    *,
    sync_inbox: bool,
) -> str:
    try:
        path = save_daily_json(predictions_path(ROOT, sport, payload["date"]), payload)
        loaded = load_daily_json(path)
        problems = prediction_reread_problems(loaded, payload)
        return _learning_json_notes(
            sport=sport,
            path=path,
            payload=payload,
            problems=problems,
            sync_inbox=sync_inbox,
            kind="predictions",
        )
    except Exception as exc:  # noqa: BLE001 - 学習JSON失敗でExcel成功を取り消さない
        return f"{LEARNING_JSON_UNSAVED}（{exc}）"


def _write_results_json(
    sport: str,
    payload: dict[str, Any],
    *,
    sync_inbox: bool,
) -> str:
    try:
        path = save_daily_json(results_path(ROOT, sport, payload["date"]), payload)
        loaded = load_daily_json(path)
        problems = results_reread_problems(loaded, payload)
        return _learning_json_notes(
            sport=sport,
            path=path,
            payload=payload,
            problems=problems,
            sync_inbox=sync_inbox,
            kind="results",
        )
    except Exception as exc:  # noqa: BLE001 - 学習JSON失敗でExcel成功を取り消さない
        return f"{LEARNING_JSON_UNSAVED}（{exc}）"


def run_predict(
    sport: str,
    target_date: str,
    *,
    force: bool = False,
    sync_drive: bool = True,
    sync_inbox: bool | None = None,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> str:
    if sport not in CONFIG_FILES:
        return UNSUPPORTED.format(sport=sport)
    if sync_inbox is None:
        sync_inbox = sync_drive
    rules = load_rules(sport)
    if is_before_learning_start(target_date):
        return _skip_before(target_date, kind="predict")
    label = SPORT_LABELS[sport]
    existing = load_predictions_doc(ROOT, sport, target_date)
    if not force and has_predicted_races(existing):
        races = records_from_predictions_doc(existing)
        return (
            f"⚠ 二重登録防止: {target_date} の{label}予想は処理済みです。"
            f"再実行する場合は --force を付けてください。"
            f"\n\n既存 {len(races)} レース"
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
            payload = empty_day_payload(
                date=target_date, sport=sport, day_status=DAY_STATUS_FETCH_FAILED
            )
            json_note = _write_predictions_json(sport, payload, sync_inbox=sync_inbox)
            return (
                f"【取得失敗】{label}の出走情報を取得できませんでした。"
                f"{' ' + str(fetch_error) if fetch_error else ''}"
                " サンプルデータは使いません。"
                " この競技の予想は中止します。"
                f"\n\n{json_note}"
            )
        if sport == "jra" or status_code == "no_meeting":
            payload = empty_day_payload(
                date=target_date, sport=sport, day_status=DAY_STATUS_NO_MEETING
            )
            json_note = _write_predictions_json(sport, payload, sync_inbox=sync_inbox)
            return (
                f"【開催なし】{target_date} は{label}の開催日ではありません。"
                + (" 中央競馬は開催日のみ予想します。" if sport == "jra" else "")
                + f"\n\n{json_note}"
            )
        payload = empty_day_payload(
            date=target_date, sport=sport, day_status=DAY_STATUS_FETCH_FAILED
        )
        json_note = _write_predictions_json(sport, payload, sync_inbox=sync_inbox)
        return (
            f"【取得失敗】{label}の出走情報を取得できませんでした。サンプルデータは使いません。"
            " この競技の予想は中止します。"
            f"\n\n{json_note}"
        )

    selected, skipped = select_races(races, rules)
    predictions: list[dict[str, Any]] = []
    for idx, candidate in enumerate(selected, start=1):
        pred = build_prediction(candidate, rules, idx)
        pred["date"] = target_date
        pred["sport"] = rules["sport"]
        pred["race_id"] = make_race_id(pred)
        validate_prediction_record(pred, rules)
        predictions.append(pred)

    sheet_status = write_predictions(entry, target_date, predictions)
    payload = build_predictions_payload(
        date=target_date,
        sport=sport,
        races=predictions,
        skipped=skipped,
    )
    json_note = _write_predictions_json(sport, payload, sync_inbox=sync_inbox)

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
    report += "\n\n※ 予想しやすさスコア(prediction_score)はExcel列がないため、解説文と学習JSONに保存します。"
    report += f"\n\n{json_note}"
    if sync_drive:
        report += "\n\n" + sync_drive_cmd(keys=SPORT_EXCEL_KEYS[sport])
    return report


def run_results(
    sport: str,
    target_date: str,
    *,
    force: bool = False,
    sync_drive: bool = True,
    sync_inbox: bool | None = None,
) -> str:
    if sport not in CONFIG_FILES:
        return UNSUPPORTED.format(sport=sport)
    if sync_inbox is None:
        sync_inbox = sync_drive
    if is_before_learning_start(target_date):
        return _skip_before(target_date, kind="results")
    label = SPORT_LABELS[sport]
    pred_doc = load_predictions_doc(ROOT, sport, target_date)
    day_records = records_from_predictions_doc(pred_doc) if pred_doc else []
    if not day_records:
        return f"{target_date} の{label}予想記録がありません。先に予想を実行してください。"

    existing_results = load_results_doc(ROOT, sport, target_date)
    apply_results_doc_to_records(day_records, existing_results)
    if not force and results_cover_predictions(pred_doc, existing_results):
        return f"⚠ 二重登録防止: {target_date} の{label}結果処理は済みです。--force で再実行可。"

    pending = [r for r in day_records if not (r.get("result") or {}).get("trifecta")]
    if pending:
        fetched, _fetch_status = ensure_result_data(ROOT, sport, target_date, day_records)
        official_path = result_data_path(ROOT, sport, target_date)
        rows = fetched or (
            load_official_results(official_path) if is_official_result_file(official_path) else []
        )
        if rows:
            _apply_result_rows_to_records(day_records, rows)
            pending = [r for r in day_records if not (r.get("result") or {}).get("trifecta")]

    pending_note = ""
    if pending and not any((r.get("result") or {}).get("trifecta") for r in day_records):
        names = ", ".join(f"{r['venue']}{r['race']}R" for r in pending)
        return (
            f"【取得失敗】{label}の正式結果を取得できませんでした: {names}\n"
            "推測では記入しません。この競技の結果処理は中止します。"
            " 処理済みにはしません。"
        )

    if pending:
        names = ", ".join(f"{r['venue']}{r['race']}R" for r in pending)
        pending_note = (
            f"\n\n【取得失敗・一部】未確定: {names}。"
            " 処理済みにはしません。次回は未取得レースだけ再取得します。"
        )

    ensure_workbooks(ROOT)
    excel = ensure_workbooks(ROOT)
    entry = excel[f"{sport}_entry"]
    summary = excel[f"{sport}_summary"]

    result_items: list[dict[str, Any]] = []
    for record in day_records:
        result = record.get("result")
        if not result or not result.get("trifecta"):
            continue
        if not record.get("review"):
            review = analyze_review(record, result["trifecta"])
            record["review"] = review
            if result["status"] == "ハズレ" and not result.get("primary_miss_reason"):
                result["primary_miss_reason"] = review.get("primary_miss_reason")
                result["secondary_miss_reasons"] = review.get("secondary_miss_reasons", [])
            result["close_miss"] = review.get("close_miss", False)
        validate_result_record(record)
        result_items.append(record)

    sheet1 = write_results(
        entry,
        target_date,
        [{"number": r["number"], "result": r["result"], "ticket_count": r["ticket_count"]} for r in result_items],
    )
    sheet2 = write_summary(summary, target_date, result_items)
    merged_races = merge_result_races(
        (existing_results or {}).get("races") or [],
        [item for item in build_results_payload(date=target_date, sport=sport, races=result_items)["races"]],
    )
    payload = {
        "schema_version": build_results_payload(date=target_date, sport=sport, races=[])["schema_version"],
        "date": target_date,
        "sport": sport,
        "timezone": build_results_payload(date=target_date, sport=sport, races=[])["timezone"],
        "races": merged_races,
    }
    json_note = _write_results_json(sport, payload, sync_inbox=sync_inbox)
    completed_n = count_completed_from_inbox(ROOT, sport)
    json_note += (
        f"\n100R母数（{label}・確定レースのみ）: {completed_n}"
        f" / 残り {remaining_to_100(completed_n)}"
    )

    all_records = _inbox_completed_records(sport)
    base_report = format_result_report(
        sport_label=label,
        date=target_date,
        records=result_items,
        all_records=all_records,
        sheet_status=f"{sheet1}\n{sheet2}",
    )
    if pending:
        base_report += pending_note
    base_report += f"\n\n{json_note}"
    if sync_drive:
        return base_report + "\n\n" + sync_drive_cmd(keys=SPORT_EXCEL_KEYS[sport])
    return base_report


def _inbox_completed_records(sport: str) -> list[dict[str, Any]]:
    folder = ROOT / "data" / "inbox" / sport
    if not folder.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.results.json")):
        try:
            doc = load_daily_json(path)
        except (OSError, ValidationError, json.JSONDecodeError):
            continue
        date = doc.get("date")
        for race in doc.get("races") or []:
            if not isinstance(race, dict):
                continue
            record = {
                "date": date,
                "sport": sport,
                "venue": race.get("venue"),
                "race": race.get("race"),
                "ticket_count": race.get("points") or 0,
                "prediction_score": 0,
                "result": {
                    "status": race.get("status"),
                    "stake": race.get("stake") or 0,
                    "payout": race.get("payout") or 0,
                },
            }
            out.append(record)
    return out


def _apply_result_rows_to_records(
    records: list[dict[str, Any]], results: list[dict[str, Any]]
) -> None:
    by_race = {_result_key(r): r for r in results}
    for record in records:
        if (record.get("result") or {}).get("trifecta"):
            continue
        key = _result_key(record)
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


def apply_results_from_file(
    sport: str,
    target_date: str,
    results_file: Path,
    *,
    sync_drive: bool = True,
    sync_inbox: bool | None = None,
) -> str:
    """公式結果JSONを取り込み、Excelと日次results.jsonへ反映する。正規stateは変更しない。"""
    if sport not in CONFIG_FILES:
        return UNSUPPORTED.format(sport=sport)
    if is_before_learning_start(target_date):
        return _skip_before(target_date, kind="results")
    with results_file.open(encoding="utf-8") as handle:
        data = json.load(handle)
    save_results_json(
        ROOT, sport, target_date, list(data.get("results") or []), source="manual_file"
    )
    return run_results(
        sport, target_date, force=True, sync_drive=sync_drive, sync_inbox=sync_inbox
    )


def ingest_inbox(sport: str, target_date: str) -> str:
    """Cursor用。日次JSONを正規stateへ合成する。日次ジョブからは呼ばない。"""
    if sport not in CONFIG_FILES:
        return UNSUPPORTED.format(sport=sport)
    if is_before_learning_start(target_date):
        return _skip_before(target_date, kind="results")
    state = load_canonical_state(ROOT, sport)
    pred_doc = load_predictions_doc(ROOT, sport, target_date)
    records = records_from_predictions_doc(pred_doc) if pred_doc else []
    if not records:
        return f"{target_date} の{SPORT_LABELS[sport]}予想JSONがありません。"
    apply_results_doc_to_records(records, load_results_doc(ROOT, sport, target_date))
    for record in records:
        if record.get("result") and not record.get("review"):
            review = analyze_review(record, record["result"].get("trifecta"))
            record["review"] = review
            result = record["result"]
            if result.get("status") == "ハズレ" and not result.get("primary_miss_reason"):
                result["primary_miss_reason"] = review.get("primary_miss_reason")
                result["secondary_miss_reasons"] = review.get("secondary_miss_reasons", [])
            result["close_miss"] = review.get("close_miss", False)
        if record.get("result"):
            validate_result_record(record)
        upsert_record(state, record)
    save_json(state_path(sport), state)
    done = sum(1 for r in records if (r.get("result") or {}).get("status") in {"的中", "ハズレ"})
    return (
        f"{SPORT_LABELS[sport]} {target_date}: 正規stateへ合成しました。"
        f" 予想{len(records)} / 確定{done}"
    )


def run_learning_report(sport: str) -> str:
    rules = load_rules(sport)
    state = load_canonical_state(ROOT, sport)
    records = records_since_start(state, with_result=True)
    report = build_learning_report(records, rules)
    report_path = ROOT / "data" / sport / "learning_report.json"
    save_json(report_path, report)
    text = format_learning_report_text(report)
    analysis = build_analysis(records)
    text += "\n\n## 詳細分析\n"
    text += json.dumps(analysis, ensure_ascii=False, indent=2)
    return text


def run_summary(target_date: str) -> str:
    require_production_states(ROOT)
    by_sport = {
        sport: load_canonical_state(ROOT, sport).get("records", []) for sport in SPORTS
    }
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
        "ingest-inbox",
    ):
        sub.add_parser(name, parents=[common])

    init_state = sub.add_parser("init-state")
    init_state.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help=f"学習・結果の開始日 YYYY-MM-DD（省略時は {DEFAULT_START_DATE} JST）",
    )
    init_state.add_argument(
        "--i-confirm-init-state",
        action="store_true",
        help="明示確認。このフラグが無いと初期化しない。",
    )

    bootstrap = sub.add_parser("bootstrap-cloud", parents=[common])
    bootstrap.add_argument(
        "--i-confirm-bootstrap",
        action="store_true",
        help="原田さんの明示許可があるときだけ付ける。Driveから古いExcelは取得しない。",
    )

    apply = sub.add_parser("apply-results", parents=[common])
    apply.add_argument("sport", choices=list(SPORTS))
    apply.add_argument("results_file", type=Path)

    save_races = sub.add_parser("save-races", parents=[common])
    save_races.add_argument("sport", choices=list(SPORTS))
    save_races.add_argument("races_file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init-state":
            print(
                init_personal_states(
                    ROOT,
                    start_date=args.start_date,
                    confirm=bool(args.i_confirm_init_state),
                )
            )
            return 0
        target_date = args.date or jst_today_str()
        if args.command == "init-excel":
            print(init_excel_cmd())
        elif args.command == "sync-drive":
            print(sync_drive_cmd())
        elif args.command == "verify-drive":
            print(run_verify_drive(ROOT))
        elif args.command == "bootstrap-cloud":
            print(run_bootstrap_cloud(ROOT, confirm=bool(args.i_confirm_bootstrap)))
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
                    load_state_fn=lambda sport: load_canonical_state(ROOT, sport),
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
                    load_state_fn=lambda sport: load_canonical_state(ROOT, sport),
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
        elif args.command == "ingest-inbox":
            print(
                "\n\n".join(ingest_inbox(sport, target_date) for sport in SPORTS)
            )
        return 0
    except CloudJobError as exc:
        print(str(exc))
        return 1
    except DriveAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
