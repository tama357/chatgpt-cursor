"""Cursor担当フロー: 収集・候補抽出・ChatGPT入出力・転記検証・結果記録。

Cursorは最終3Rも買い目も作らない。最終予想が無い提出は停止する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from keirin_chatgpt_io import (
    SchemaError,
    build_chatgpt_input,
    chatgpt_final_path,
    chatgpt_input_path,
    find_final_prediction,
    load_json,
    require_chatgpt_final,
    save_json,
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


def refuse_cursor_prediction(reason: str = "Cursorは競輪の予想そのものを行いません") -> None:
    raise CursorMustNotPredict(reason)


def load_rules(root: Path) -> dict[str, Any]:
    return load_json(root / "current_rules.json")


def _candidate_lookup(candidates: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for item in candidates:
        venue = str(item.get("venue") or "").strip()
        race = int(item.get("race_number") or item.get("race") or 0)
        out[(venue, race)] = item
    return out


def prepare_today(
    root: Path,
    date: str | None = None,
    *,
    races_file: Path | None = None,
    get_json: Callable[..., dict[str, Any]] | None = None,
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
        path = save_json(chatgpt_input_path(root, date), payload)
        return (
            f"【収集結果】{date} の開催・出走を取得できませんでした（source={source}）。"
            f" Cursorは予想しません。入力JSON: {path}"
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
    path = save_json(chatgpt_input_path(root, date), payload)
    names = "、".join(f"{item['venue']}{item.get('race_number') or item.get('race')}R" for item in selected)
    return (
        f"【データ準備完了】{date} の候補を {len(selected)} レース抽出しました（{source}）。\n"
        f"候補: {names or 'なし'}\n"
        f"ChatGPT入力JSON: {path}\n"
        f"最終3Rと買い目は作っていません。ChatGPTにこのJSONを渡してください。\n"
        f"最終予想JSONが来るまで提出・シート転記・Chatworkは行いません。"
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
        item["close_time"] = pred.get("close_time") or candidate.get("deadline")
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
) -> str:
    date = date or today_str()
    raw = find_final_prediction(root, date, json_file=final_file)
    try:
        final_data = require_chatgpt_final(raw)
    except SchemaError as exc:
        return STOP_NO_FINAL + f"\n{exc}"

    if final_data.get("date") and final_data["date"] != date:
        return STOP_NO_FINAL + f"\n最終予想の日付が {final_data.get('date')} で、対象日 {date} と違います。"

    input_path = chatgpt_input_path(root, date)
    input_data = load_json(input_path) if input_path.exists() else None
    try:
        predictions = _attach_scores_from_candidates(final_data, input_data)
    except SchemaError as exc:
        return f"提出処理を停止しました。{exc}"

    if final_file:
        save_json(chatgpt_final_path(root, date), final_data)

    notes = ["ChatGPT最終予想を受け取りました。Cursorは内容を改変していません。"]

    if write_sheets:
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
            except (SheetError, Exception) as exc:
                notes.append(f"シート転記または再読検証に失敗したため、Chatworkは送りません: {exc}")
                return "\n".join(notes)
    else:
        notes.append("シート転記はスキップしました（ローカル検証）。")

    day_payload = {
        "date": date,
        "candidates": (input_data or {}).get("candidates") or [],
        "predictions": predictions,
    }
    if record_fn is not None:
        record_fn(day_payload)
    else:
        try:
            from keirin_workflow import build_day_from_predictions, expand_pick, extract_axis

            for pred in predictions:
                tickets = pred.get("tickets") or []
                pred["axis"] = extract_axis(tickets)
                total = 0
                for ticket in tickets:
                    total += len(expand_pick(str(ticket["pick"])))
                if pred.get("ticket_count") != total:
                    raise SchemaError(
                        f"予想{pred['number']}: 合計点数が買い目と一致しません（JSON={pred.get('ticket_count')} / 展開={total}）。修正せず停止します。"
                    )
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
                    "ticket_count": next(
                        item["ticket_count"]
                        for item in day["predictions"]
                        if item["number"] == pred["number"]
                    ),
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
        if send_fn is None:
            notes.append("Chatwork送信関数が無いため送信していません。")
        else:
            send_result = send_fn({"date": date, "predictions": final_data["predictions"]})
            notes.append(f"Chatwork: {send_result}")
    else:
        notes.append("Chatworkは --confirm-send があるときだけ送ります。")
    return "\n".join(notes)


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
    prepared = prepare_today(root, date, races_file=kwargs.get("races_file"), get_json=kwargs.get("get_json"))
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
    )
    return prepared + "\n\n" + ingested


def missing_stop(raw: dict[str, Any] | None) -> bool:
    from keirin_chatgpt_io import missing_final_prediction_fields

    return bool(missing_final_prediction_fields(raw))
