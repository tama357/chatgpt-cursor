"""Cursor担当フロー: 収集・候補抽出・第一予想・ChatGPT入出力・転記検証・結果記録。

6:00は第一予想まで。最終確定・シート転記・ChatworkはChatGPT担当。
最終予想が無い提出は停止する。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from keirin_chatgpt_io import (
    SchemaError,
    build_chatgpt_input,
    chatgpt_final_legacy_path,
    chatgpt_final_path,
    chatgpt_input_path,
    chatgpt_input_readiness_message,
    chatgpt_input_tmp_path,
    find_final_prediction,
    is_chatgpt_input_ready,
    load_chatgpt_input_for_validation,
    load_json,
    require_chatgpt_final,
    save_json,
    validate_chatgpt_final_mechanically,
    write_chatgpt_input,
)
from keirin_submission_state import (
    already_fully_processed,
    chatwork_sending_enabled,
    load_submission_state,
    mark_submission,
)
from keirin_fetch import fetch_races_for_date, fetch_results_for_predictions, load_races_file
from keirin_jst import today_str, yesterday_str
from keirin_learning_json import (
    build_learning_records,
    save_learning_inbox,
    save_predictions_inbox,
    save_results_inbox,
)
from keirin_score import extract_candidates, score_candidate
from keirin_drive_inbox import (
    DriveInboxError,
    DriveInboxStore,
    format_sync_note,
    pull_completed_final,
    pull_ready_input,
    pull_submission_state,
    sync_completed_final,
    sync_ready_input,
    sync_submission_state,
)
from keirin_sheets import (
    SheetError,
    SheetStore,
    write_predictions_and_reread,
    write_results_and_reread,
)


STOP_NO_FINAL = (
    "ChatGPTの最終予想が無いため、提出処理を停止しました。"
    "Cursorは代わりに予想・買い目・最終3R選定をしません。"
)


class CursorMustNotPredict(RuntimeError):
    pass


def refuse_cursor_prediction(reason: str = "Cursorは最終予想を確定しません。第一予想は最終ではありません") -> None:
    raise CursorMustNotPredict(reason)


def load_rules(root: Path) -> dict[str, Any]:
    return load_json(root / "current_rules.json")


def _race_number(item: dict[str, Any]) -> int:
    if item.get("race_number") is not None:
        return int(item["race_number"])
    race = item.get("race")
    if isinstance(race, int):
        return race
    if isinstance(race, str) and race.isdigit():
        return int(race)
    return 0


def _candidate_lookup(candidates: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for item in candidates:
        venue = str(item.get("venue") or "").strip()
        out[(venue, _race_number(item))] = item
    return out


def _candidates_for_state(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in candidates:
        race_no = _race_number(item)
        close_time = item.get("close_time") or item.get("deadline")
        normalized = {
            "venue": str(item.get("venue") or "").strip(),
            "race": race_no,
            "close_time": close_time,
            "prediction_score": item.get("prediction_score"),
            "score_breakdown": item.get("score_breakdown"),
            "penalties": item.get("penalties") or [],
        }
        if item.get("selected") is not None:
            normalized["selected"] = item.get("selected")
        if "selection_rank" in item and item.get("selected") is True:
            normalized["selection_rank"] = item.get("selection_rank")
        out.append(normalized)
    return out


def input_artifact_name(date: str) -> str:
    return f"keirin-prediction-input-{date}"


def emit_github_prepare_outputs(root: Path, date: str, ready: bool) -> None:
    """GitHub Actions に Artifact 用の出力を渡す。未完成なら ready=false。"""
    gh = os.environ.get("GITHUB_OUTPUT")
    if not gh:
        return
    path = chatgpt_input_path(root, date)
    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
        rel_text = rel.as_posix()
    except ValueError:
        rel_text = str(path)
    with open(gh, "a", encoding="utf-8") as handle:
        handle.write(f"date={date}\n")
        handle.write(f"ready={'true' if ready else 'false'}\n")
        handle.write(f"input_path={rel_text}\n")
        handle.write(f"artifact_name={input_artifact_name(date)}\n")


def _handoff_status_lines(*, ready: bool, artifact_note: str, drive_note: str) -> str:
    created = "成功" if ready else "未完成"
    return (
        f"input JSON作成：{created}\n"
        f"Artifact保存：{artifact_note}\n"
        f"{drive_note}"
    )


def _sync_ready_input_note(
    root: Path,
    date: str,
    *,
    sync_drive: bool,
    drive_store: DriveInboxStore | None,
) -> str:
    if not sync_drive:
        return "Drive同期：未使用"
    try:
        result = sync_ready_input(root, date, store=drive_store)
    except Exception as exc:
        return f"Drive同期：失敗（{exc}）"
    if result:
        return "Drive同期：成功"
    return "Drive同期：未使用"


def _sync_completed_final_note(
    root: Path,
    date: str,
    *,
    sync_drive: bool,
    drive_store: DriveInboxStore | None,
    payload: dict[str, Any],
) -> str:
    if not sync_drive:
        return "Drive同期はスキップしました。"
    try:
        result = sync_completed_final(root, date, store=drive_store, payload=payload)
        return format_sync_note(result)
    except DriveInboxError as exc:
        return f"Drive未同期: {exc} 最終予想の内容は補正していません。"


def prepare_today(
    root: Path,
    date: str | None = None,
    *,
    races_file: Path | None = None,
    get_json: Callable[..., dict[str, Any]] | None = None,
    sync_drive: bool = False,
    drive_store: DriveInboxStore | None = None,
) -> str:
    date = date or today_str()
    rules = load_rules(root)
    if races_file:
        races = load_races_file(str(races_file))
        source = f"ファイル {races_file.name}"
    else:
        races = fetch_races_for_date(date, get_json=get_json, enrich=False)
        source = "keirin.jp"
    if not races:
        payload = build_chatgpt_input(date=date, candidates=[], skipped=[], rules=rules)
        path = write_chatgpt_input(root, payload)
        emit_github_prepare_outputs(root, date, ready=False)
        return (
            f"【収集結果】{date} の開催・出走を取得できませんでした（source={source}）。"
            f" 第一予想も最終予想も作っていません。"
            f" 正式ファイルは未作成です。ChatGPTには渡さないでください。"
            f" 一時ファイル: {path}\n"
            f"{_handoff_status_lines(ready=False, artifact_note='未実施', drive_note='Drive同期：未使用')}"
        )

    selected, skipped = extract_candidates(races, rules, min_count=5, max_count=10)
    if selected and not races_file:
        try:
            from keirin_fetch import enrich_races

            enrich_races(selected, get_json=get_json)
            selected = [score_candidate(item, rules) for item in selected]
            selected = sorted(selected, key=lambda item: (-int(item["prediction_score"]), item.get("venue"), item.get("race")))
        except Exception:
            selected = [score_candidate(item, rules) for item in selected]

    payload = build_chatgpt_input(date=date, candidates=selected, skipped=skipped, rules=rules)
    path = write_chatgpt_input(root, payload)
    names = "、".join(f"{item['venue']}{item.get('race_number') or item.get('race')}R" for item in selected)
    ready = is_chatgpt_input_ready(root, date)
    formal = chatgpt_input_path(root, date)
    tmp = chatgpt_input_tmp_path(root, date)
    missing = "、".join(payload.get("missing_fields") or [])
    first = payload.get("cursor_first_prediction") or {}
    first_names = "、".join(
        f"{item.get('venue')}{item.get('race')}R"
        for item in (first.get("selected_races") or [])
        if isinstance(item, dict)
    )
    first_note = (
        f"Cursor第一予想: {first_names or 'なし'}。"
        f"{first.get('shortfall_reason') or '3Rまで作成済み。'}"
        "これは最終予想ではありません。"
    )
    emit_github_prepare_outputs(root, date, ready=ready)
    artifact_note = (
        f"GitHub Actions Artifact（{input_artifact_name(date)}）へ渡します"
        if ready and os.environ.get("GITHUB_OUTPUT")
        else ("未実施（readyではない）" if not ready else "GitHub Actionsでのみ保存")
    )
    drive_note = (
        _sync_ready_input_note(root, date, sync_drive=sync_drive, drive_store=drive_store)
        if ready
        else "Drive同期：未使用"
    )
    status_lines = _handoff_status_lines(
        ready=ready, artifact_note=artifact_note, drive_note=drive_note
    )
    if not ready:
        return (
            f"【データ未完成】{date} の候補を {len(selected)} レース抽出しましたが、"
            f"重要情報が欠けているため正式ファイルは作っていません。\n"
            f"候補: {names or 'なし'}\n"
            f"欠けている項目: {missing or '不明'}\n"
            f"一時ファイル: {tmp}\n"
            f"{chatgpt_input_readiness_message(root, date)}\n"
            f"{first_note}\n"
            f"シート転記とChatworkは行っていません。ChatGPTには渡さないでください。\n"
            f"{status_lines}"
        )
    return (
        f"【データ準備完了】{date} の候補を {len(selected)} レース抽出し、第一予想をinputへ入れました（{source}）。\n"
        f"候補: {names or 'なし'}\n"
        f"{first_note}\n"
        f"ChatGPT入力JSON: {formal}\n"
        f"{chatgpt_input_readiness_message(root, date)}\n"
        f"この正式名（{formal.name}）だけをChatGPTに渡してください。"
        f" {tmp.name} は作成途中なので渡さないでください。\n"
        f"{status_lines}\n"
        f"最終予想としては確定していません。prediction_finalは作っていません。\n"
        f"6:00時点ではシート転記もChatwork送信も行いません。"
    )


def _attach_scores_from_candidates(
    final_data: dict[str, Any], input_data: dict[str, Any] | None
) -> list[dict[str, Any]]:
    candidates = list((input_data or {}).get("candidates") or [])
    lookup = _candidate_lookup(candidates)
    merged: list[dict[str, Any]] = []
    for pred in final_data["predictions"]:
        key = (str(pred["venue"]).strip(), int(pred["race"]))
        candidate = lookup.get(key)
        if candidate is None:
            raise SchemaError(
                f"{pred['venue']}{pred['race']}R は候補JSONにありません。"
                "Cursorは候補外レースを勝手に補完しません。"
            )
        item = dict(pred)
        item["prediction_score"] = candidate.get("prediction_score")
        item["score_breakdown"] = candidate.get("score_breakdown")
        item["penalties"] = candidate.get("penalties")
        item["fetched_data"] = candidate.get("fetched_data") or {}
        if "first_place_candidate_count" not in item:
            firsts = {
                str(ticket.get("pick") or "").split("-")[0]
                for ticket in item.get("tickets") or []
                if ticket.get("type") == "本線" and ticket.get("pick")
            }
            item["first_place_candidate_count"] = min(2, max(1, len(firsts)))
        merged.append(item)
    return merged


def ingest_final(
    root: Path,
    date: str | None = None,
    *,
    final_file: Path | None = None,
    sheet_store: SheetStore | None = None,
    write_sheets: bool = True,
    confirm_send: bool = False,
    send_fn: Callable[[dict[str, Any]], Any] | None = None,
    record_fn: Callable[..., Any] | None = None,
    sync_drive: bool = False,
    drive_store: DriveInboxStore | None = None,
) -> str:
    date = date or today_str()
    if not chatwork_sending_enabled():
        confirm_send = False
    if sync_drive:
        try:
            pull_submission_state(root, date, store=drive_store)
        except DriveInboxError:
            pass
    if sync_drive and not is_chatgpt_input_ready(root, date):
        try:
            pull_ready_input(root, date, store=drive_store)
        except DriveInboxError:
            pass
    raw = find_final_prediction(root, date, json_file=final_file)
    if raw is None and sync_drive and final_file is None:
        try:
            raw = pull_completed_final(root, date, store=drive_store)
        except (DriveInboxError, SchemaError):
            raw = None
    try:
        final_data = require_chatgpt_final(raw)
    except SchemaError as exc:
        return STOP_NO_FINAL + f"\n{exc}"

    input_data = load_chatgpt_input_for_validation(root, date)
    validate_chatgpt_final_mechanically(
        final_data,
        expected_date=date,
        input_data=input_data,
    )

    sub = load_submission_state(root, date)
    if already_fully_processed(sub):
        return (
            f"{date} の最終予想はすでに処理済みです。"
            f"シート転記もChatwork送信も再実行しません。"
            f"（処理日時: {sub.get('processed_at') or '不明'}）"
        )

    try:
        predictions = _attach_scores_from_candidates(final_data, input_data)
    except SchemaError as exc:
        return f"提出処理を停止しました。{exc}"

    if final_file:
        save_json(chatgpt_final_path(root, date), final_data)
    elif not chatgpt_final_path(root, date).is_file():
        save_json(chatgpt_final_path(root, date), final_data)

    notes = ["ChatGPT最終予想を受け取りました。Cursorは内容を改変していません。"]
    notes.append(
        _sync_completed_final_note(
            root,
            date,
            sync_drive=sync_drive,
            drive_store=drive_store,
            payload=final_data,
        )
    )

    if write_sheets:
        if sub["sheet_written"]:
            notes.append("シートはすでに転記済みのため、再書き込みしません。")
        else:
            store = sheet_store
            if store is None:
                try:
                    from keirin_sheets import google_store_from_env

                    store = google_store_from_env()
                except Exception as exc:
                    notes.append(f"Sheets APIに接続できないため転記していません: {exc}")
                    store = None
            if store is None:
                notes.append("シート転記なし。最終予想は改変していません。")
            else:
                try:
                    notes.append(write_predictions_and_reread(store, date, predictions))
                    sub = mark_submission(root, date, sheet_written=True)
                except (SheetError, Exception) as exc:
                    notes.append(f"シート転記または再読検証に失敗したため、Chatworkは送りません: {exc}")
                    if sync_drive:
                        try:
                            sync_submission_state(root, date, store=drive_store)
                        except DriveInboxError:
                            pass
                    return "\n".join(notes)
    else:
        notes.append("シート転記はスキップしました（ローカル検証）。")

    day_payload = {
        "date": date,
        "candidates": _candidates_for_state((input_data or {}).get("candidates") or []),
        "predictions": predictions,
    }
    if record_fn is not None:
        record_fn(day_payload)
    else:
        try:
            from keirin_workflow import build_day_from_predictions, extract_axis

            for pred in predictions:
                tickets = pred.get("tickets") or []
                if "axis" not in pred:
                    pred["axis"] = extract_axis(tickets)
            day = build_day_from_predictions({**day_payload, "date": date})
            day_payload["low_quality_day"] = day["low_quality_day"]
            day_payload["candidates"] = day["candidates"]
            day_payload["predictions"] = [
                {
                    **pred,
                    "axis": next(
                        item["axis"]
                        for item in day["predictions"]
                        if item["number"] == pred["number"]
                    ),
                    "ticket_count": pred.get("ticket_count"),
                }
                for pred in predictions
            ]
        except Exception as exc:
            notes.append(f"学習用day JSONの組み立てに失敗: {exc}")

    try:
        path = save_predictions_inbox(root, day_payload)
        notes.append(f"学習JSON保存: {path.name}")
    except Exception as exc:
        notes.append(f"学習JSON未保存（{exc}）")

    if confirm_send:
        if sub["chatwork_sent"]:
            notes.append("Chatworkはすでに送信済みのため、再送しません。")
        elif send_fn is None:
            notes.append("Chatwork送信関数が無いため送信していません。")
        else:
            try:
                send_result = send_fn({"date": date, "predictions": final_data["predictions"]})
                sub = mark_submission(root, date, chatwork_sent=True)
                notes.append(f"Chatwork: {send_result}")
            except Exception as exc:
                notes.append(
                    f"Chatwork送信に失敗しました。成功したシート転記は再書き込みしません。"
                    f"失敗したChatworkだけ再実行できます: {exc}"
                )
    else:
        if chatwork_sending_enabled():
            notes.append("Chatworkは --confirm-send があるときだけ送ります。")
        else:
            notes.append("Chatwork送信は停止中です。API送信・再送は行いません。")
    if sync_drive:
        try:
            sync_submission_state(root, date, store=drive_store)
        except DriveInboxError as exc:
            notes.append(f"提出状態のDrive保存に失敗: {exc}")
    return "\n".join(notes)


NO_FINAL_RETRY = (
    "当日の prediction_final がDriveにまだありません。"
    "何もしません。エラーではありません。次回の確認で再チェックします。"
)


def poll_ingest_final(
    root: Path,
    date: str | None = None,
    *,
    sheet_store: SheetStore | None = None,
    write_sheets: bool = True,
    confirm_send: bool = False,
    send_fn: Callable[[dict[str, Any]], Any] | None = None,
    drive_store: DriveInboxStore | None = None,
) -> str:
    """Drive上の完成finalだけを取り込む。無ければ正常終了。"""
    date = date or today_str()
    try:
        pull_submission_state(root, date, store=drive_store)
    except DriveInboxError:
        pass
    sub = load_submission_state(root, date)
    if already_fully_processed(sub):
        return (
            f"{date} の最終予想はすでに処理済みです。"
            "シート転記もChatwork送信も再実行しません。"
        )
    pulled = None
    try:
        pulled = pull_completed_final(root, date, store=drive_store)
    except (DriveInboxError, SchemaError) as exc:
        return (
            f"{date} のDrive上のfinalを取り込めませんでした。"
            f"内容は補正しません。{exc}"
        )
    if pulled is None and not chatgpt_final_path(root, date).is_file():
        return NO_FINAL_RETRY
    return ingest_final(
        root,
        date,
        final_file=chatgpt_final_path(root, date) if chatgpt_final_path(root, date).is_file() else None,
        sheet_store=sheet_store,
        write_sheets=write_sheets,
        confirm_send=confirm_send,
        send_fn=send_fn,
        sync_drive=True,
        drive_store=drive_store,
    )


def _classify_miss(axis: str | None, tickets: list[dict[str, Any]], trifecta: str, hit: bool) -> dict[str, Any]:
    if hit:
        return {"primary_miss_reason": None, "secondary_miss_reasons": []}
    first, second, third = trifecta.split("-")
    seconds = {str(t.get("pick") or "").split("-")[1] for t in tickets if str(t.get("pick") or "").count("-") == 2}
    thirds: set[str] = set()
    for ticket in tickets:
        parts = str(ticket.get("pick") or "").split("-")
        if len(parts) >= 3:
            thirds.update(parts[2])
    if axis != first:
        return {"primary_miss_reason": "axis_miss", "secondary_miss_reasons": []}
    if second not in seconds:
        return {"primary_miss_reason": "second_place_miss", "secondary_miss_reasons": []}
    if third not in thirds:
        return {"primary_miss_reason": "third_place_miss", "secondary_miss_reasons": []}
    return {"primary_miss_reason": "other", "secondary_miss_reasons": []}


def process_results(
    root: Path,
    date: str | None = None,
    *,
    results_file: Path | None = None,
    sheet_store: SheetStore | None = None,
    write_sheets: bool = True,
    get_json: Callable[..., dict[str, Any]] | None = None,
    record_fn: Callable[..., Any] | None = None,
) -> str:
    date = date or yesterday_str()
    pred_path = Path(root) / "data" / "inbox" / f"{date}.predictions.json"
    if not pred_path.exists():
        final_path = chatgpt_final_path(root, date)
        if not final_path.exists():
            final_path = chatgpt_final_legacy_path(root, date)
        if not final_path.exists():
            return f"{date} の最終予想がありません。Cursorは結果を推測して埋めません。"
        pred_doc = {"date": date, "predictions": load_json(final_path).get("predictions") or []}
    else:
        pred_doc = load_json(pred_path)
    predictions = list(pred_doc.get("predictions") or [])
    if len(predictions) != 3:
        return f"{date} の最終予想が3レース分ありません。Cursorは欠けた予想を作りません。"

    if results_file:
        raw = load_json(Path(results_file))
        official = list(raw.get("results") or raw.get("races") or [])
    else:
        official = fetch_results_for_predictions(predictions, get_json=get_json)

    by_key = {
        (str(item.get("venue") or "").strip(), int(item.get("race") or item.get("number") or 0)): item
        for item in official
    }
    # also index by number
    by_number = {int(item["number"]): item for item in official if item.get("number") in {1, 2, 3}}

    from keirin_workflow import check_hit, compute_close_miss, expand_pick, extract_axis

    result_items: list[dict[str, Any]] = []
    for pred in predictions:
        tickets = pred.get("tickets") or []
        axis = pred.get("axis") or (extract_axis(tickets) if tickets else None)
        ticket_count = pred.get("ticket_count")
        if ticket_count is None:
            ticket_count = sum(len(expand_pick(str(t["pick"]))) for t in tickets)
        official_row = by_number.get(int(pred["number"]))
        if official_row is None:
            official_row = by_key.get((str(pred["venue"]).strip(), int(pred["race"])))
        if not official_row or not official_row.get("trifecta"):
            return (
                f"【取得失敗】{pred['venue']}{pred['race']}R の公式結果がありません。"
                "推測では記入しません。"
            )
        trifecta = official_row["trifecta"]
        try:
            hit = bool(check_hit(trifecta, tickets))
        except Exception:
            expanded = []
            for ticket in tickets:
                expanded.extend(expand_pick(str(ticket["pick"])))
            hit = trifecta in expanded
        payout = int(official_row.get("payout") or 0)
        if not hit:
            payout = 0
        miss = _classify_miss(axis, tickets, trifecta, hit)
        close_miss = False
        if axis:
            close_miss = compute_close_miss(
                status="的中" if hit else "ハズレ",
                axis=str(axis),
                tickets=tickets,
                trifecta=trifecta,
            )
        item = {
            "number": pred["number"],
            "venue": pred.get("venue"),
            "race": pred.get("race"),
            "trifecta": trifecta,
            "status": "的中" if hit else "ハズレ",
            "payout": payout,
            "points": ticket_count,
            "ticket_count": ticket_count,
            "stake": ticket_count * 100,
            "primary_miss_reason": miss["primary_miss_reason"],
            "secondary_miss_reasons": miss["secondary_miss_reasons"],
            "close_miss": close_miss,
            "scenario_materialized": official_row.get("scenario_materialized"),
        }
        result_items.append(item)

    notes = [f"【結果】{date} の公式結果を3レース分確認しました。"]
    if write_sheets:
        store = sheet_store
        if store is None:
            try:
                from keirin_sheets import google_store_from_env

                store = google_store_from_env()
            except Exception as exc:
                notes.append(f"Sheets APIに接続できないため結果欄は更新していません: {exc}")
                store = None
        if store is not None:
            try:
                notes.append(write_results_and_reread(store, date, result_items))
            except Exception as exc:
                notes.append(f"シート結果欄の更新または再読に失敗しました: {exc}")
    else:
        notes.append("シート更新はスキップしました（ローカル検証）。")

    low_quality = bool(pred_doc.get("low_quality_day"))
    if not low_quality:
        scores = [int(p.get("prediction_score") or 100) for p in predictions]
        low_quality = min(scores) < 70 if scores else False

    results_payload = {"date": date, "results": result_items}
    learning_payload = build_learning_records(
        date=date,
        predictions=predictions,
        results=result_items,
        low_quality_day=low_quality,
    )
    try:
        rpath = save_results_inbox(root, results_payload)
        lpath = save_learning_inbox(root, learning_payload)
        notes.append(f"学習JSON保存: {rpath.name} / {lpath.name}")
    except Exception as exc:
        notes.append(f"学習JSON未保存（{exc}）")

    if record_fn is not None:
        record_fn(results_payload)
    return "\n".join(notes)


def run_today_or_stop(
    root: Path,
    date: str | None = None,
    **kwargs: Any,
) -> str:
    """旧『今日の予想を実行して』互換。最終予想が無ければ収集だけで止める。"""
    date = date or today_str()
    prepared = prepare_today(
        root,
        date,
        races_file=kwargs.get("races_file"),
        get_json=kwargs.get("get_json"),
        sync_drive=kwargs.get("sync_drive", False),
        drive_store=kwargs.get("drive_store"),
    )
    raw = find_final_prediction(root, date, json_file=kwargs.get("final_file"))
    if missing_stop(raw):
        return prepared + "\n\n" + STOP_NO_FINAL
    ingested = ingest_final(
        root,
        date,
        final_file=kwargs.get("final_file"),
        sheet_store=kwargs.get("sheet_store"),
        write_sheets=kwargs.get("write_sheets", True),
        confirm_send=kwargs.get("confirm_send", False),
        send_fn=kwargs.get("send_fn"),
        sync_drive=kwargs.get("sync_drive", False),
        drive_store=kwargs.get("drive_store"),
    )
    return prepared + "\n\n" + ingested


def missing_stop(raw: dict[str, Any] | None) -> bool:
    from keirin_chatgpt_io import missing_final_prediction_fields

    return bool(missing_final_prediction_fields(raw))
