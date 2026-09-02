"""keirin.jp から開催・出走・結果を収集する。予想・買い目は作らない。"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from keirin_jst import yyyymmdd

USER_AGENT = "Mozilla/5.0 (compatible; HaradaKeirinCollect/1.0)"
JsonGetter = Callable[..., dict[str, Any]]


class FetchError(RuntimeError):
    pass


def default_get_json(req_type: str, **params: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"type": req_type, **params})
    request = urllib.request.Request(
        f"https://keirin.jp/pc/json?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("resultCd") in (-1, -2):
        raise FetchError(f"keirin.jp API error type={req_type} code={data.get('resultCd')}")
    return data


def _venue_short_name(name: str) -> str:
    return str(name or "").replace("競輪場", "").replace("\u3000", "").strip()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fetch_schedule(date_str: str, *, get_json: JsonGetter | None = None) -> list[dict[str, Any]]:
    getter = get_json or default_get_json
    wanted = yyyymmdd(date_str)
    meetings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kbn in ("1", "0", "2"):
        try:
            data = getter(
                "JSJ048",
                kaisaibikbn=kbn,
                kanyusyaflg="false",
                dispid="0",
                shccp="",
            )
        except (FetchError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for item in data.get("RaceList") or []:
            if str(item.get("kaisaiDate") or "") != wanted:
                continue
            encp = str(item.get("touhyouLivePara") or "")
            venue = _venue_short_name(str(item.get("keirinjoName") or ""))
            if not encp or not venue or encp in seen:
                continue
            seen.add(encp)
            meetings.append(
                {
                    "venue": venue,
                    "encp": encp,
                    "kaisai_date": wanted,
                    "cancelled": str(item.get("tyusiKbn") or "") not in {"", "0"},
                    "source": "keirin.jp",
                }
            )
    return meetings


def _parse_recent_meeting(block: dict[str, Any]) -> dict[str, Any]:
    results = []
    for row in block.get("resultInfoSubData") or []:
        if not isinstance(row, dict):
            continue
        results.append(
            {
                "place": row.get("imgTyakuiName"),
                "B_count": _as_int(row.get("backTori"), 0) if row.get("backTori") not in (None, "") else None,
            }
        )
    return {
        "venue": _venue_short_name(str(block.get("kerinjyoName") or "")),
        "start_date": block.get("kaisaiFirst"),
        "grade": block.get("gaiTeiGrade"),
        "results": results,
    }


def _rider_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    number = _as_int(entry.get("syaban"))
    kyaku = str(entry.get("kyaku") or "")
    return {
        "number": number,
        "name": str(entry.get("senName") or "").replace("\u3000", ""),
        "reg_no": str(entry.get("senNo") or ""),
        "prefecture": str(entry.get("huken") or "").replace("\u3000", ""),
        "winning_style": kyaku,
        "kyaku": kyaku,
        "line": kyaku or None,
        "recommended": bool(entry.get("itiosiFlag")),
        "aisyo": bool(entry.get("aisyoFlag")),
        "score": None,
        "recent_results": None,
        "B_count": None,
        "current_meeting_results": None,
        "previous_meeting_results": None,
    }


def _enrich_riders(
    riders: list[dict[str, Any]],
    enc_para_r: str,
    *,
    get_json: JsonGetter,
) -> None:
    try:
        detail = get_json("JSJ010", encp=enc_para_r)
    except (FetchError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        detail = {}
    try:
        extra = get_json("JSJ011", encp=enc_para_r)
    except (FetchError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        extra = {}
    by_num_010 = {
        _as_int(item.get("syaban")): item
        for item in detail.get("sensyuTypeInfo") or []
        if isinstance(item, dict)
    }
    by_num_011 = {
        _as_int(item.get("syaban")): item
        for item in extra.get("sensyuTypeInfo") or []
        if isinstance(item, dict)
    }
    for rider in riders:
        row = by_num_010.get(rider["number"]) or {}
        more = by_num_011.get(rider["number"]) or {}
        if row.get("kyakusitu"):
            rider["winning_style"] = str(row.get("kyakusitu"))
            rider["kyaku"] = rider["winning_style"]
        rider["kyuhan"] = row.get("kyuhan")
        rider["previous_kyuhan"] = row.get("prevKyuhan")
        rider["age"] = row.get("age")
        kon = row.get("konResultInfoSubData")
        if isinstance(kon, dict):
            rider["current_meeting_results"] = _parse_recent_meeting(kon)
        prev = []
        for block in row.get("tyoInfoSubData") or []:
            if isinstance(block, dict):
                prev.append(_parse_recent_meeting(block))
        rider["previous_meeting_results"] = prev or None
        b_total = 0
        b_found = False
        for meeting in prev:
            for item in meeting.get("results") or []:
                if item.get("B_count") is not None:
                    b_total += int(item["B_count"])
                    b_found = True
        rider["B_count"] = b_total if b_found else None
        comment = more.get("commentOrderCntSubData")
        if isinstance(comment, dict):
            rider["recent_results"] = {
                "first": _as_int(comment.get("tyo4Tyaku1st")),
                "second": _as_int(comment.get("tyo4Tyaku2nd")),
                "third": _as_int(comment.get("tyo4Tyaku3rd")),
                "out": _as_int(comment.get("tyo4TyakuOut")),
                "home_bank": comment.get("homeBank"),
            }
            rider["home_bank"] = comment.get("homeBank")
            rider["disqualify_point"] = comment.get("shikkakuPoint")


def _risk_factors(block: dict[str, Any], riders: list[dict[str, Any]], kessya: bool) -> list[str]:
    risks: list[str] = []
    if kessya:
        risks.append("欠場あり")
    if not riders:
        risks.append("出走データ不足")
    if not block.get("denTime"):
        risks.append("締切時刻が公式JSONに無い")
    if any(rider.get("score") is None for rider in riders):
        risks.append("競走得点は公式JSONから未取得")
    if block.get("ozzFlg") in (None, "", 0, "0"):
        risks.append("オッズ未公開または未取得")
    nige = sum(1 for rider in riders if rider.get("winning_style") == "逃")
    if nige == 0:
        risks.append("逃げる選手がいない")
    if nige >= 3:
        risks.append("逃げが複数で線が分かれやすい")
    return risks


def fetch_races_for_date(
    date_str: str,
    *,
    get_json: JsonGetter | None = None,
    enrich: bool = True,
) -> list[dict[str, Any]]:
    getter = get_json or default_get_json
    meetings = fetch_schedule(date_str, get_json=getter)
    all_races: list[dict[str, Any]] = []
    for meeting in meetings:
        if meeting.get("cancelled"):
            continue
        try:
            venue_data = getter("JSJ001", encp=meeting["encp"])
        except (FetchError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        main = venue_data.get("C0201data") or {}
        venue = _venue_short_name(str(main.get("joName") or meeting["venue"]))
        race_rows = main.get("C0201race") or []
        if not race_rows:
            continue
        enc_para_r = str(race_rows[0].get("encParaR") or "")
        if not enc_para_r:
            continue
        try:
            entries_data = getter("JSJ017", encp=enc_para_r)
        except (FetchError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
        for block in entries_data.get("rInfo") or []:
            race_no = _as_int(block.get("raceNo"))
            if race_no <= 0:
                continue
            riders = [_rider_from_entry(item) for item in block.get("sInfo") or [] if _as_int(item.get("syaban")) > 0]
            idx = race_no - 1
            enc_r = enc_para_r
            if 0 <= idx < len(race_rows):
                enc_r = str(race_rows[idx].get("encParaR") or enc_para_r)
            kessya = False
            deadline = str(block.get("denTime") or "")
            race = {
                "date": date_str,
                "venue": venue,
                "race": race_no,
                "race_number": race_no,
                "deadline": deadline,
                "close_time": deadline,
                "start_time": str(block.get("stTime") or ""),
                "class_name": str(block.get("syumoku") or ""),
                "riders": riders,
                "line": {
                    "narabi_flag": block.get("narabiFlg"),
                    "narabi_y_count": block.get("narabiYCnt"),
                    "styles": [rider.get("winning_style") for rider in riders],
                },
                "winning_style": [rider.get("winning_style") for rider in riders],
                "B_count": next((rider.get("B_count") for rider in riders if rider.get("B_count") is not None), None),
                "current_meeting_results": [rider.get("current_meeting_results") for rider in riders],
                "previous_meeting_results": [rider.get("previous_meeting_results") for rider in riders],
                "odds": None,
                "kessya": kessya,
                "scratches": [],
                "risk_factors": _risk_factors(block, riders, kessya),
                "source": "keirin.jp",
                "fetched_data": {
                    "source": "keirin.jp",
                    "encParaK": meeting["encp"],
                    "encParaR": enc_r,
                    "odds_flag": block.get("ozzFlg"),
                    "result_flag": block.get("resultFlg"),
                },
            }
            all_races.append(race)
    return all_races


def enrich_races(races: list[dict[str, Any]], *, get_json: JsonGetter | None = None) -> list[dict[str, Any]]:
    """候補だけ選手詳細を足す。買い目は作らない。"""
    getter = get_json or default_get_json
    for race in races:
        enc_r = str((race.get("fetched_data") or {}).get("encParaR") or "")
        riders = list(race.get("riders") or [])
        if not enc_r or not riders:
            continue
        _enrich_riders(riders, enc_r, get_json=getter)
        race["riders"] = riders
        race["current_meeting_results"] = [rider.get("current_meeting_results") for rider in riders]
        race["previous_meeting_results"] = [rider.get("previous_meeting_results") for rider in riders]
        race["B_count"] = next((rider.get("B_count") for rider in riders if rider.get("B_count") is not None), None)
        if "競走得点は公式JSONから未取得" not in (race.get("risk_factors") or []):
            if any(rider.get("score") is None for rider in riders):
                race.setdefault("risk_factors", []).append("競走得点は公式JSONから未取得")
    return races


def parse_trifecta_result(data: dict[str, Any]) -> dict[str, Any] | None:
    order = data.get("tyakujyunItemSubData") or []
    if len(order) < 3:
        return None
    nums = [str(row.get("syaban")) for row in order[:3]]
    if any(not item or item == "None" for item in nums):
        return None
    trifecta = "-".join(nums)
    payout = 0
    harai = data.get("haraiGakuSubData") or {}
    for item in harai.get("RT3HaraiGakuDispItemSubData") or []:
        kumi = str(item.get("kumiBan") or "").replace("=", "-")
        if kumi == trifecta:
            raw = str(item.get("haraiGaku") or "0").replace(",", "")
            if raw.isdigit():
                payout = int(raw)
            break
    return {
        "trifecta": trifecta,
        "payout": payout,
        "source": "keirin.jp",
        "weather": data.get("tenki"),
        "wind": data.get("husoku"),
    }


def fetch_result_for_race(enc_para_r: str, *, get_json: JsonGetter | None = None) -> dict[str, Any] | None:
    getter = get_json or default_get_json
    try:
        raw = getter("JSJ012", encp=enc_para_r)
    except (FetchError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    return parse_trifecta_result(raw)


def fetch_results_for_predictions(
    predictions: list[dict[str, Any]],
    *,
    get_json: JsonGetter | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for pred in predictions:
        fetched = pred.get("fetched_data") or {}
        enc_para_r = fetched.get("encParaR")
        if not enc_para_r:
            continue
        parsed = fetch_result_for_race(str(enc_para_r), get_json=get_json)
        if not parsed:
            continue
        results.append(
            {
                "number": pred.get("number"),
                "venue": pred.get("venue"),
                "race": pred.get("race") or pred.get("race_number"),
                "trifecta": parsed["trifecta"],
                "payout": parsed["payout"],
                "source": parsed["source"],
            }
        )
    return results


def load_races_file(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        races = data.get("races") or data.get("candidates")
        if isinstance(races, list):
            return races
    raise FetchError("レースJSONは races 配列が必要です")
