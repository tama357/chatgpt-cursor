from __future__ import annotations

from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from common.tickets import expand_tickets
from excel.layout import (
    COL_AXIS,
    COL_CLOSE,
    COL_CONFIDENCE,
    COL_COVER,
    COL_MAIN,
    COL_PAYOUT,
    COL_POINTS,
    COL_PRED_NUM,
    COL_PRED_SCORE,
    COL_RACE,
    COL_RATIONALE,
    COL_RESULT,
    COL_RISKS,
    COL_SCENARIO,
    COL_SKIP,
    COL_SPORT,
    COL_STATUS,
    COL_TARGET,
    COL_TOTAL,
    COL_VENUE,
    PREDICTION_INPUT_COLS,
    RESULT_INPUT_COLS,
    SUMMARY_RACE_COLS,
    SUMMARY_ROWS_PER_DAY,
    blocks,
    sheet_tab_name,
    summary_day_start_row,
    summary_tab_name,
)


def _write_cell(ws, row: int, col: int, value: Any, allowed: set[int]) -> None:
    if col not in allowed:
        return
    ws.cell(row=row, column=col, value=value)


def ensure_daily_tab(entry_path: Path, date_str: str, sport_label: str) -> None:
    wb = load_workbook(entry_path)
    tab = sheet_tab_name(date_str)
    if tab not in wb.sheetnames:
        template = wb["テンプレ"]
        ws = wb.copy_worksheet(template)
        ws.title = tab
        for row in range(2, 80):
            for col in PREDICTION_INPUT_COLS:
                if col not in {COL_PRED_NUM, COL_SPORT}:
                    ws.cell(row=row, column=col, value=None)
    wb.save(entry_path)
    wb.close()


def write_predictions(
    entry_path: Path,
    date_str: str,
    predictions: list[dict[str, Any]],
    sport_label: str,
) -> str:
    ensure_daily_tab(entry_path, date_str, sport_label)
    wb = load_workbook(entry_path)
    ws = wb[sheet_tab_name(date_str)]
    block_map = {b.index: b.main_row for b in blocks()}

    for idx, pred in enumerate(predictions[:5], start=1):
        row = block_map[idx]
        tickets = pred.get("tickets", [])
        expanded = expand_tickets(tickets) if tickets else []
        main_picks = [t.compact for t in expanded if t.kind == "本線"]
        cover_picks = [t.compact for t in expanded if t.kind == "抑え"]
        total = sum(len(t.combinations) for t in expanded)
        values = {
            COL_PRED_NUM: idx,
            COL_SPORT: sport_label,
            COL_VENUE: pred.get("venue"),
            COL_RACE: pred.get("race"),
            COL_CLOSE: pred.get("close_time"),
            COL_TARGET: pred.get("target"),
            COL_PRED_SCORE: pred.get("prediction_score"),
            COL_CONFIDENCE: pred.get("confidence"),
            COL_AXIS: pred.get("axis"),
            COL_MAIN: " / ".join(main_picks),
            COL_COVER: " / ".join(cover_picks),
            COL_TOTAL: total,
            COL_RATIONALE: pred.get("rationale") or pred.get("explanation"),
            COL_SCENARIO: pred.get("scenario"),
            COL_RISKS: pred.get("risks"),
            COL_SKIP: pred.get("skip_reason") or "",
        }
        for col, val in values.items():
            _write_cell(ws, row, col, val, PREDICTION_INPUT_COLS)

    wb.save(entry_path)
    wb.close()
    return f"記入完了: {entry_path.name} / タブ {sheet_tab_name(date_str)} / {len(predictions)}レース"


def write_results(
    entry_path: Path,
    date_str: str,
    results: list[dict[str, Any]],
) -> str:
    wb = load_workbook(entry_path)
    tab = sheet_tab_name(date_str)
    if tab not in wb.sheetnames:
        raise FileNotFoundError(f"タブ {tab} がありません。先に予想を記載してください。")
    ws = wb[tab]
    block_map = {b.index: b.main_row for b in blocks()}

    for item in results:
        row = block_map.get(item.get("number", 0))
        if not row:
            continue
        result = item.get("result", item)
        _write_cell(ws, row, COL_RESULT, result.get("trifecta"), RESULT_INPUT_COLS)
        _write_cell(ws, row, COL_PAYOUT, result.get("payout"), RESULT_INPUT_COLS)
        _write_cell(ws, row, COL_STATUS, result.get("status"), RESULT_INPUT_COLS)
        _write_cell(ws, row, COL_POINTS, item.get("ticket_count") or result.get("points"), RESULT_INPUT_COLS)

    wb.save(entry_path)
    wb.close()
    return f"結果記入完了: {entry_path.name} / タブ {tab}"


def ensure_summary_tab(summary_path: Path, year: int, month: int) -> None:
    from excel.templates import _build_summary_template_ws

    tab = summary_tab_name(year, month)
    wb = load_workbook(summary_path)
    if tab not in wb.sheetnames:
        ws = wb.create_sheet(tab)
        _build_summary_template_ws(ws, year, month)
    wb.save(summary_path)
    wb.close()


def write_summary(
    summary_path: Path,
    date_str: str,
    results: list[dict[str, Any]],
) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    ensure_summary_tab(summary_path, dt.year, dt.month)
    tab = summary_tab_name(dt.year, dt.month)
    wb = load_workbook(summary_path)
    ws = wb[tab]
    start = summary_day_start_row(dt.day)

    for idx, item in enumerate(results[:5], start=0):
        col = SUMMARY_RACE_COLS[idx]
        result = item.get("result", item)
        status = result.get("status", "")
        payout = result.get("payout", 0) if status == "的中" else 0
        points = item.get("ticket_count") or result.get("points", 0)
        ws.cell(row=start, column=col, value=status)
        ws.cell(row=start + 1, column=col, value=payout)
        ws.cell(row=start + 2, column=col, value=points)

    wb.save(summary_path)
    wb.close()
    return f"集計シート更新: {summary_path.name} / {tab} / {dt.day}日"
