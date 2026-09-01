"""keirin.jp 公式JSON API。個人予想では未使用（提出用は 競輪予想/）。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "Mozilla/5.0 (compatible; HaradaPersonalPredict/1.0)"

KYAKU_RATING = {"逃": 96, "両": 90, "追": 84, "マ": 82}
DEFAULT_FACTORS = {
    "axis_reliability": 14,
    "line_clarity": 11,
    "ability_gap": 12,
    "scenario_simplicity": 11,
    "recent_form": 12,
    "track_style_fit": 8,
    "risk_absence": 7,
}


def _get_json(req_type: str, **params: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"type": req_type, **params})
    req = urllib.request.Request(
        f"https://keirin.jp/pc/json?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("resultCd") in (-1, -2):
        raise RuntimeError(f"keirin.jp API error type={req_type} code={data.get('resultCd')}")
    return data


def fetch_today_schedule(*, kaisaibikbn: str = "0") -> list[dict[str, Any]]:
    """JSJ048: 当日開催場一覧。"""
    data = _get_json(
        "JSJ048",
        kaisaibikbn=kaisaibikbn,
        kanyusyaflg="false",
        dispid="0",
        shccp="",
    )
    return data.get("RaceList", [])


def fetch_venue(encp: str) -> dict[str, Any]:
    """JSJ001: 開催場のレース一覧。"""
    return _get_json("JSJ001", encp=encp)


def fetch_race_entries(enc_para_r: str) -> dict[str, Any]:
    """JSJ017: 出走表（全レース分）。"""
    return _get_json("JSJ017", encp=enc_para_r)


def fetch_race_result(enc_para_r: str) -> dict[str, Any]:
    """JSJ012: 着順・払戻。"""
    return _get_json("JSJ012", encp=enc_para_r)


def _venue_short_name(jo_name: str) -> str:
    return jo_name.replace("競輪場", "").strip()


def _estimate_close_time(race_no: int) -> str:
    hour = 17 + (race_no - 1) // 3
    minute = ((race_no - 1) % 3) * 20
    return f"{hour:02d}:{minute:02d}"


def _entry_rating(entry: dict[str, Any]) -> int:
    base = KYAKU_RATING.get(str(entry.get("kyaku", "")), 80)
    if entry.get("aisyoFlag"):
        base += 2
    if entry.get("itiosiFlag"):
        base += 1
    return min(99, base)


def _parse_entries(data: dict[str, Any], venue: str, enc_para_k: str) -> list[dict[str, Any]]:
    races: list[dict[str, Any]] = []
    for block in data.get("rInfo", []):
        race_no = int(block.get("raceNo", 0))
        if race_no <= 0:
            continue
        entries_raw = block.get("sInfo", [])
        if len(entries_raw) < 4:
            continue
        entries: list[dict[str, Any]] = []
        for item in entries_raw:
            num = int(item.get("syaban", 0))
            if num <= 0:
                continue
            kyaku = str(item.get("kyaku", ""))
            line = "S" if kyaku == "逃" and item.get("itiosiFlag") else "A"
            entries.append(
                {
                    "number": num,
                    "name": str(item.get("senName", "")).replace("\u3000", ""),
                    "rating": _entry_rating(item),
                    "line": line,
                    "kyaku": kyaku,
                }
            )
        if len(entries) < 4:
            continue
        ranked = sorted(entries, key=lambda e: (-e["rating"], e["number"]))
        axis = str(ranked[0]["number"])
        races.append(
            {
                "venue": venue,
                "race": race_no,
                "close_time": _estimate_close_time(race_no),
                "axis": axis,
                "entries": entries,
                "factors": dict(DEFAULT_FACTORS),
                "penalties": [],
                "notes": f"keirin.jp自動取得（{venue}{race_no}R）",
                "fetched_data": {
                    "source": "keirin.jp",
                    "encParaK": enc_para_k,
                    "encParaR": block.get("encParaR"),
                },
            }
        )
    return races


def fetch_races_for_date(date_str: str) -> list[dict[str, Any]]:
    """指定日の全開催場から出走表を収集。"""
    kaisai = date_str.replace("-", "")
    schedule = fetch_today_schedule()
    all_races: list[dict[str, Any]] = []
    for item in schedule:
        if str(item.get("kaisaiDate")) != kaisai:
            continue
        encp = str(item.get("touhyouLivePara", ""))
        venue = str(item.get("keirinjoName", ""))
        if not encp or not venue:
            continue
        try:
            venue_data = fetch_venue(encp)
        except (RuntimeError, urllib.error.URLError, TimeoutError):
            continue
        main = venue_data.get("C0201data", {})
        jo_name = _venue_short_name(str(main.get("joName", venue)))
        sel_date = str(main.get("selKaisai", ""))
        if sel_date and sel_date != kaisai:
            continue
        race_rows = main.get("C0201race", [])
        if not race_rows:
            continue
        enc_para_r = str(race_rows[0].get("encParaR", ""))
        if not enc_para_r:
            continue
        try:
            entries_data = fetch_race_entries(enc_para_r)
        except (RuntimeError, urllib.error.URLError, TimeoutError):
            continue
        races = _parse_entries(entries_data, jo_name, encp)
        for race in races:
            race["date"] = date_str
            idx = race["race"] - 1
            if 0 <= idx < len(race_rows):
                race["fetched_data"]["encParaR"] = race_rows[idx].get("encParaR", enc_para_r)
        all_races.extend(races)
    return all_races


def _parse_trifecta_result(data: dict[str, Any]) -> dict[str, Any] | None:
    order = data.get("tyakujyunItemSubData", [])
    if len(order) < 3:
        return None
    nums = [str(row.get("syaban")) for row in order[:3]]
    trifecta = "-".join(nums)
    payout = 0
    harai = data.get("haraiGakuSubData", {})
    for item in harai.get("RT3HaraiGakuDispItemSubData", []):
        kumi = str(item.get("kumiBan", "")).replace("=", "-")
        if kumi == trifecta:
            raw = str(item.get("haraiGaku", "0")).replace(",", "")
            if raw.isdigit():
                payout = int(raw)
            break
    return {"trifecta": trifecta, "payout": payout, "source": "keirin.jp"}


def fetch_results_for_predictions(
    predictions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """予想済みレースの encParaR から結果を取得。"""
    results: list[dict[str, Any]] = []
    for pred in predictions:
        fetched = pred.get("fetched_data") or {}
        enc_para_r = fetched.get("encParaR")
        if not enc_para_r:
            continue
        try:
            raw = fetch_race_result(str(enc_para_r))
        except (RuntimeError, urllib.error.URLError, TimeoutError):
            continue
        parsed = _parse_trifecta_result(raw)
        if not parsed:
            continue
        results.append(
            {
                "venue": pred.get("venue"),
                "race": pred.get("race"),
                "trifecta": parsed["trifecta"],
                "payout": parsed["payout"],
                "scenario_realized": None,
            }
        )
    return results
