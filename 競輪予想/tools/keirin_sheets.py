"""既存スプレッドシートへの値転記と再読検証。構造は一切変えない。

予想記入シート（確定・変更禁止）:
- A 予想番号 / B 狙い / C 自信度 / D 競輪場 / E R / F 締切時刻
- G 本線/抑え / H 買い目 / I 点数（各買い目行）
- J 合計点数（自動式・書かない）
- K 解説
- L Chatwork本文（自動式・書かない）
- M 結果3連単 / N 払戻金 / O 結果
- 予想1: 2〜16行、予想2: 17〜31行、予想3: 32〜46行

予想集計シート（確定・変更禁止）:
- 手入力は P〜R のみ（1本目〜3本目）
- B〜O は計算式のため編集しない
- 1日3行: 結果 / 的中額 / 購入点数
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from keirin_jst import sheet_tab_date, summary_day_label, summary_tab_month

ENTRY_SHEET_NAME = "原田さん｜予想記入シート"
SUMMARY_SHEET_NAME = "原田さん｜予想集計シート"
TEMPLATE_TAB = "テンプレ"
ROWS_PER_PREDICTION = 15
FIRST_MAIN_ROW = 2
TICKET_SLOTS = 15
FORBIDDEN_ENTRY_COLS = {"J", "L"}
FORBIDDEN_SUMMARY_COLS = set("BCDEFGHIJKLMNO")
ENTRY_INPUT_COLS = set("ABCDEFGHIK")
RESULT_COLS = set("MNO")
SUMMARY_INPUT_COLS = set("PQR")

ENTRY_COL = {
    "number": "A",
    "target": "B",
    "confidence": "C",
    "venue": "D",
    "race": "E",
    "close_time": "F",
    "ticket_type": "G",
    "pick": "H",
    "points": "I",
    "explanation": "K",
    "trifecta": "M",
    "payout": "N",
    "status": "O",
}


class SheetError(RuntimeError):
    pass


class SheetStructureGuard(RuntimeError):
    pass


def main_row(number: int) -> int:
    if number not in {1, 2, 3}:
        raise SheetError("予想番号は1〜3だけ転記します")
    return FIRST_MAIN_ROW + (number - 1) * ROWS_PER_PREDICTION


def a1(col: str, row: int) -> str:
    return f"{col}{row}"


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        text = text[:-2]
    if text.endswith("点") and text[:-1].isdigit():
        text = text[:-1]
    if text.endswith("R") and text[:-1].isdigit():
        text = text[:-1]
    if text.endswith("円"):
        text = text[:-1].replace(",", "").replace("¥", "").replace("￥", "")
    text = text.replace("¥", "").replace("￥", "").replace(",", "")
    return text


def values_equal(expected: Any, actual: Any) -> bool:
    return _norm(expected) == _norm(actual)


@dataclass
class CellUpdate:
    a1: str
    value: Any
    purpose: str


def prediction_cell_updates(predictions: list[dict[str, Any]]) -> list[CellUpdate]:
    updates: list[CellUpdate] = []
    for pred in predictions:
        number = int(pred["number"])
        row = main_row(number)
        updates.extend(
            [
                CellUpdate(a1("A", row), number, "予想番号"),
                CellUpdate(a1("B", row), pred["target"], "狙い"),
                CellUpdate(a1("C", row), pred["confidence"], "自信度"),
                CellUpdate(a1("D", row), pred["venue"], "競輪場"),
                CellUpdate(a1("E", row), pred["race"], "R"),
                CellUpdate(a1("F", row), pred["close_time"], "締切時刻"),
                CellUpdate(a1("K", row), pred["explanation"], "解説"),
            ]
        )
        tickets = list(pred.get("tickets") or [])
        for offset in range(TICKET_SLOTS):
            ticket_row = row + offset
            if offset < len(tickets):
                ticket = tickets[offset]
                combos = ticket.get("combinations") or ticket.get("points")
                if combos is None:
                    pick = str(ticket.get("pick") or "")
                    third = pick.split("-")[2] if pick.count("-") == 2 else ""
                    combos = len(third)
                updates.extend(
                    [
                        CellUpdate(a1("G", ticket_row), ticket.get("type"), "本線/抑え"),
                        CellUpdate(a1("H", ticket_row), ticket.get("pick"), "買い目"),
                        CellUpdate(a1("I", ticket_row), combos, "点数"),
                    ]
                )
            else:
                updates.extend(
                    [
                        CellUpdate(a1("G", ticket_row), "", "本線/抑え"),
                        CellUpdate(a1("H", ticket_row), "", "買い目"),
                        CellUpdate(a1("I", ticket_row), "", "点数"),
                    ]
                )
    _assert_entry_updates_safe(updates, allowed=ENTRY_INPUT_COLS)
    return updates


def result_cell_updates(results: list[dict[str, Any]]) -> list[CellUpdate]:
    updates: list[CellUpdate] = []
    for item in results:
        row = main_row(int(item["number"]))
        updates.extend(
            [
                CellUpdate(a1("M", row), item["trifecta"], "結果3連単"),
                CellUpdate(a1("N", row), item["payout"], "払戻金"),
                CellUpdate(a1("O", row), item["status"], "結果"),
            ]
        )
    _assert_entry_updates_safe(updates, allowed=RESULT_COLS)
    return updates


def summary_cell_updates(date: str, results: list[dict[str, Any]], start_row: int) -> list[CellUpdate]:
    cols = ("P", "Q", "R")
    by_number = {int(item["number"]): item for item in results}
    updates: list[CellUpdate] = []
    for index, col in enumerate(cols, start=1):
        item = by_number.get(index)
        if not item:
            continue
        updates.extend(
            [
                CellUpdate(a1(col, start_row), item["status"], "集計・結果"),
                CellUpdate(a1(col, start_row + 1), item.get("payout") if item["status"] == "的中" else 0, "集計・的中額"),
                CellUpdate(a1(col, start_row + 2), item.get("points") or item.get("ticket_count"), "集計・購入点数"),
            ]
        )
    _assert_summary_updates_safe(updates)
    return updates


def _col_letter(a1_ref: str) -> str:
    letters = "".join(ch for ch in a1_ref if ch.isalpha())
    return letters.upper()


def _assert_entry_updates_safe(updates: list[CellUpdate], *, allowed: set[str]) -> None:
    for item in updates:
        col = _col_letter(item.a1)
        if col in FORBIDDEN_ENTRY_COLS:
            raise SheetStructureGuard(f"{item.a1} は自動式のため書けません")
        if col not in allowed:
            raise SheetStructureGuard(f"{item.a1} は転記対象外です。シート構造は変更しません")


def _assert_summary_updates_safe(updates: list[CellUpdate]) -> None:
    for item in updates:
        col = _col_letter(item.a1)
        if col in FORBIDDEN_SUMMARY_COLS:
            raise SheetStructureGuard(f"{item.a1} は計算式のため書けません")
        if col not in SUMMARY_INPUT_COLS:
            raise SheetStructureGuard(f"{item.a1} は集計の手入力範囲（P〜R）外です")


class SheetStore(Protocol):
    def ensure_entry_tab(self, date: str) -> str:
        """当日タブ名を返す。無ければテンプレ複製だけ行う。列構成は変えない。"""

    def write_entry(self, tab: str, updates: list[CellUpdate]) -> None:
        ...

    def read_entry(self, tab: str, a1_list: list[str]) -> dict[str, Any]:
        ...

    def ensure_summary_tab(self, date: str) -> str:
        ...

    def find_summary_day_row(self, tab: str, date: str) -> int:
        ...

    def write_summary(self, tab: str, updates: list[CellUpdate]) -> None:
        ...

    def read_summary(self, tab: str, a1_list: list[str]) -> dict[str, Any]:
        ...


@dataclass
class MemorySheetStore:
    """テスト用。既存セルへ値だけ書き、見出しや列追加はしない。"""

    entry_tabs: dict[str, dict[str, Any]] = field(default_factory=dict)
    summary_tabs: dict[str, dict[str, Any]] = field(default_factory=dict)
    copied_tabs: list[str] = field(default_factory=list)
    write_entry_calls: int = 0
    write_summary_calls: int = 0

    def ensure_entry_tab(self, date: str) -> str:
        tab = sheet_tab_date(date)
        if tab not in self.entry_tabs:
            if TEMPLATE_TAB in self.entry_tabs:
                self.entry_tabs[tab] = dict(self.entry_tabs[TEMPLATE_TAB])
            else:
                self.entry_tabs[tab] = {}
            self.copied_tabs.append(tab)
        return tab

    def write_entry(self, tab: str, updates: list[CellUpdate]) -> None:
        self.write_entry_calls += 1
        sheet = self.entry_tabs.setdefault(tab, {})
        for item in updates:
            sheet[item.a1] = item.value

    def read_entry(self, tab: str, a1_list: list[str]) -> dict[str, Any]:
        sheet = self.entry_tabs.get(tab) or {}
        return {ref: sheet.get(ref) for ref in a1_list}

    def ensure_summary_tab(self, date: str) -> str:
        tab = summary_tab_month(date)
        self.summary_tabs.setdefault(tab, {})
        return tab

    def find_summary_day_row(self, tab: str, date: str) -> int:
        label = summary_day_label(date)
        sheet = self.summary_tabs.get(tab) or {}
        for row in range(1, 120):
            value = _norm(sheet.get(a1("B", row)))
            if value in {label, _norm(date), date}:
                return row
        # テスト用の既定: ヘッダ12行目の次、1日から3行ずつ
        day = int(date.split("-")[2])
        return 13 + (day - 1) * 3

    def write_summary(self, tab: str, updates: list[CellUpdate]) -> None:
        self.write_summary_calls += 1
        sheet = self.summary_tabs.setdefault(tab, {})
        for item in updates:
            sheet[item.a1] = item.value

    def read_summary(self, tab: str, a1_list: list[str]) -> dict[str, Any]:
        sheet = self.summary_tabs.get(tab) or {}
        return {ref: sheet.get(ref) for ref in a1_list}


def verify_updates(expected: list[CellUpdate], actual: dict[str, Any], *, label: str) -> None:
    mismatches: list[str] = []
    for item in expected:
        if not values_equal(item.value, actual.get(item.a1)):
            mismatches.append(
                f"{item.a1}（{item.purpose}） expected={item.value!r} actual={actual.get(item.a1)!r}"
            )
    if mismatches:
        raise SheetError(f"{label}の再読がChatGPT最終予想と一致しません: " + " / ".join(mismatches))


def significant_prediction_updates(predictions: list[dict[str, Any]]) -> list[CellUpdate]:
    return [item for item in prediction_cell_updates(predictions) if _norm(item.value)]


def entry_matches_predictions(
    store: SheetStore,
    date: str,
    predictions: list[dict[str, Any]],
) -> bool:
    """既存シートの予想値がfinalと一致するか。一致なら書き直さない。"""
    tab = sheet_tab_date(date)
    updates = significant_prediction_updates(predictions)
    if not updates:
        return False
    try:
        actual = store.read_entry(tab, [item.a1 for item in updates])
    except Exception:
        return False
    return all(values_equal(item.value, actual.get(item.a1)) for item in updates)


def entry_has_conflicting_predictions(
    store: SheetStore,
    date: str,
    predictions: list[dict[str, Any]],
) -> bool:
    """当日タブに予想値が入っていて、finalと一致しない。"""
    tab = sheet_tab_date(date)
    refs = [a1(col, main_row(number)) for number in (1, 2, 3) for col in ("B", "D", "H")]
    try:
        actual = store.read_entry(tab, refs)
    except Exception:
        return False
    if not any(_norm(actual.get(ref)) for ref in refs):
        return False
    return not entry_matches_predictions(store, date, predictions)


def write_predictions_and_reread(
    store: SheetStore,
    date: str,
    predictions: list[dict[str, Any]],
) -> str:
    if entry_matches_predictions(store, date, predictions):
        return (
            f"予想記入シート {sheet_tab_date(date)} は最終予想と一致済みのため、"
            "再書き込みしません"
        )
    if entry_has_conflicting_predictions(store, date, predictions):
        raise SheetError(
            f"予想記入シート {sheet_tab_date(date)} に最終予想と違う値が入っています。"
            "既存シートを壊さないため転記しません。"
        )
    tab = store.ensure_entry_tab(date)
    updates = prediction_cell_updates(predictions)
    store.write_entry(tab, updates)
    actual = store.read_entry(tab, [item.a1 for item in updates])
    verify_updates(updates, actual, label="予想記入シート")
    return f"予想記入シート {tab} へ3レースを転記し、再読で完全一致を確認しました"


def write_results_and_reread(
    store: SheetStore,
    date: str,
    results: list[dict[str, Any]],
) -> str:
    notes: list[str] = []
    entry_tab = store.ensure_entry_tab(date)
    entry_updates = result_cell_updates(results)
    store.write_entry(entry_tab, entry_updates)
    actual_entry = store.read_entry(entry_tab, [item.a1 for item in entry_updates])
    verify_updates(entry_updates, actual_entry, label="予想記入シート結果欄")
    notes.append(f"予想記入シート {entry_tab} のM/N/Oを更新し、再読一致を確認しました")

    summary_tab = store.ensure_summary_tab(date)
    start = store.find_summary_day_row(summary_tab, date)
    summary_updates = summary_cell_updates(date, results, start)
    store.write_summary(summary_tab, summary_updates)
    actual_summary = store.read_summary(summary_tab, [item.a1 for item in summary_updates])
    verify_updates(summary_updates, actual_summary, label="予想集計シートP〜R")
    notes.append(f"予想集計シート {summary_tab} のP〜Rだけを更新し、再読一致を確認しました")
    return "\n".join(notes)


def _http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class GoogleSheetStore:
    """ファイル名で既存シートを探し、値だけ書き込む。IDはコードに埋め込まない。"""

    def __init__(self, token: str, *, entry_id: str, summary_id: str) -> None:
        self.token = token
        self.entry_id = entry_id
        self.summary_id = summary_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def ensure_entry_tab(self, date: str) -> str:
        return self._ensure_tab(self.entry_id, sheet_tab_date(date))

    def ensure_summary_tab(self, date: str) -> str:
        return self._ensure_tab(self.summary_id, summary_tab_month(date), copy_template=False)

    def write_entry(self, tab: str, updates: list[CellUpdate]) -> None:
        self._write(self.entry_id, tab, updates)

    def read_entry(self, tab: str, a1_list: list[str]) -> dict[str, Any]:
        return self._read(self.entry_id, tab, a1_list)

    def write_summary(self, tab: str, updates: list[CellUpdate]) -> None:
        self._write(self.summary_id, tab, updates)

    def read_summary(self, tab: str, a1_list: list[str]) -> dict[str, Any]:
        return self._read(self.summary_id, tab, a1_list)

    def find_summary_day_row(self, tab: str, date: str) -> int:
        label = summary_day_label(date)
        status, raw = _http_request(
            f"https://sheets.googleapis.com/v4/spreadsheets/{self.summary_id}/values/{urllib.parse.quote(tab + '!B1:B120')}",
            headers=self._headers(),
        )
        if status != 200:
            raise SheetError(f"集計シートの日付列を読めません HTTP {status}")
        values = json.loads(raw.decode("utf-8")).get("values") or []
        for index, row in enumerate(values, start=1):
            cell = row[0] if row else ""
            if _norm(cell) in {label, _norm(date)}:
                return index
        raise SheetError(f"集計シート {tab} に {label} の行がありません。行追加はしません")

    def _ensure_tab(self, spreadsheet_id: str, tab: str, *, copy_template: bool = True) -> str:
        status, raw = _http_request(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}?fields=sheets.properties",
            headers=self._headers(),
        )
        if status != 200:
            raise SheetError(f"シート一覧を取得できません HTTP {status}")
        sheets = json.loads(raw.decode("utf-8")).get("sheets") or []
        names = {item.get("properties", {}).get("title"): item.get("properties", {}) for item in sheets}
        if tab in names:
            return tab
        if not copy_template or TEMPLATE_TAB not in names:
            raise SheetError(f"タブ {tab} が無く、テンプレ複製もできません。シート構造は新規作成しません")
        template_id = names[TEMPLATE_TAB].get("sheetId")
        body = json.dumps(
            {
                "requests": [
                    {
                        "duplicateSheet": {
                            "sourceSheetId": template_id,
                            "newSheetName": tab,
                        }
                    }
                ]
            }
        ).encode()
        status, raw = _http_request(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
            method="POST",
            headers=self._headers(),
            body=body,
        )
        if status != 200:
            raise SheetError(f"テンプレ複製に失敗しました HTTP {status}: {raw.decode('utf-8', errors='replace')}")
        return tab

    def _write(self, spreadsheet_id: str, tab: str, updates: list[CellUpdate]) -> None:
        data = [
            {"range": f"'{tab}'!{item.a1}", "values": [[item.value]]}
            for item in updates
        ]
        body = json.dumps({"valueInputOption": "USER_ENTERED", "data": data}).encode()
        status, raw = _http_request(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate",
            method="POST",
            headers=self._headers(),
            body=body,
        )
        if status != 200:
            raise SheetError(f"セル転記に失敗しました HTTP {status}: {raw.decode('utf-8', errors='replace')}")

    def _read(self, spreadsheet_id: str, tab: str, a1_list: list[str]) -> dict[str, Any]:
        ranges = [f"'{tab}'!{ref}" for ref in a1_list]
        query = urllib.parse.urlencode([("ranges", item) for item in ranges], doseq=True)
        status, raw = _http_request(
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet?{query}",
            headers=self._headers(),
        )
        if status != 200:
            raise SheetError(f"セル再読に失敗しました HTTP {status}: {raw.decode('utf-8', errors='replace')}")
        payload = json.loads(raw.decode("utf-8"))
        out: dict[str, Any] = {}
        for ref, value_range in zip(a1_list, payload.get("valueRanges") or []):
            values = value_range.get("values") or []
            out[ref] = values[0][0] if values and values[0] else None
        return out


def find_spreadsheet_id(token: str, title: str) -> str:
    query = urllib.parse.urlencode(
        {
            "q": f"name = '{title}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
            "fields": "files(id,name)",
            "pageSize": 5,
        }
    )
    status, raw = _http_request(
        f"https://www.googleapis.com/drive/v3/files?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200:
        raise SheetError(f"Drive検索に失敗しました HTTP {status}")
    files = json.loads(raw.decode("utf-8")).get("files") or []
    exact = [item for item in files if item.get("name") == title]
    if not exact:
        raise SheetError(f"スプレッドシートが見つかりません: {title}")
    return str(exact[0]["id"])


def google_store_from_env() -> GoogleSheetStore:
    import keirin_drive_state as drive_state

    token = drive_state.get_access_token()
    entry_id = os.environ.get("KEIRIN_ENTRY_SHEET_ID") or find_spreadsheet_id(token, ENTRY_SHEET_NAME)
    summary_id = os.environ.get("KEIRIN_SUMMARY_SHEET_ID") or find_spreadsheet_id(token, SUMMARY_SHEET_NAME)
    return GoogleSheetStore(token, entry_id=entry_id, summary_id=summary_id)
