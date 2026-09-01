from __future__ import annotations

import re
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .base import is_dummy_entry_name, reject_dummy_races
from .http import fetch_text


JRA_VENUE = {
    "01": "札幌",
    "02": "函館",
    "03": "福島",
    "04": "新潟",
    "05": "東京",
    "06": "中山",
    "07": "中京",
    "08": "京都",
    "09": "阪神",
    "10": "小倉",
}

NAR_VENUE = {
    "30": "門別",
    "32": "門別",
    "33": "盛岡",
    "34": "水沢",
    "35": "浦和",
    "36": "船橋",
    "37": "大井",
    "38": "川崎",
    "39": "金沢",
    "40": "笠松",
    "41": "名古屋",
    "42": "園田",
    "43": "姫路",
    "44": "高知",
    "45": "佐賀",
    "46": "荒尾",
    "47": "帯広ば",
    "48": "旭川",
    "50": "その他",
}

VENUE_CODE = {**JRA_VENUE, **NAR_VENUE}


def _safe_text(url: str) -> str | None:
    try:
        return fetch_text(url)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _list_urls(kaisai_date: str, circuit: str) -> list[str]:
    if circuit == "nar":
        host = "https://nar.netkeiba.com/top"
    else:
        host = "https://race.netkeiba.com/top"
    return [
        f"{host}/race_list_sub.html?kaisai_date={kaisai_date}",
        f"{host}/race_list_get_date_list.html?kaisai_date={kaisai_date}",
        f"{host}/race_list.html?kaisai_date={kaisai_date}",
    ]


def parse_kaisai_venues(html: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for match in re.finditer(r"kaisai_id=(\d+)[^>]*>([^<]+)</a>", html):
        name = match.group(2).strip()
        if name:
            mapping[match.group(1)] = name
    return mapping


def fetch_race_ids(kaisai_date: str, circuit: str = "jra") -> tuple[list[str] | None, dict[str, str]]:
    """kaisai_date: YYYYMMDD。通信失敗時は (None, {})、開催なしは ([], venues)。"""
    ids: list[str] = []
    venues: dict[str, str] = {}
    any_ok = False
    for url in _list_urls(kaisai_date, circuit):
        html = _safe_text(url)
        if html is None:
            continue
        any_ok = True
        venues.update(parse_kaisai_venues(html))
        ids.extend(re.findall(r"race_id=(\d{12})", html))
        ids.extend(re.findall(r"/race/(\d{12})", html))
        ids.extend(re.findall(r"shutuba\.html\?race_id=(\d{12})", html))
    if not any_ok:
        return None, {}
    filtered: list[str] = []
    for race_id in sorted(set(ids)):
        venue_code = race_id[4:6]
        if circuit == "jra" and venue_code not in JRA_VENUE:
            continue
        if circuit == "nar" and venue_code in JRA_VENUE:
            continue
        filtered.append(race_id)
    return filtered, venues


def _venue_for(race_id: str, circuit: str, kaisai_venues: dict[str, str]) -> str:
    kaisai_id = race_id[:10]
    if kaisai_id in kaisai_venues:
        return kaisai_venues[kaisai_id]
    venue_code = race_id[4:6]
    if circuit == "jra":
        return JRA_VENUE.get(venue_code, venue_code)
    return VENUE_CODE.get(venue_code, venue_code)


def parse_shutuba(html: str, race_id: str, circuit: str, kaisai_venues: dict[str, str] | None = None) -> dict[str, Any] | None:
    venue = _venue_for(race_id, circuit, kaisai_venues or {})
    race_num = int(race_id[10:12])
    close_m = re.search(r"(\d{1,2}:\d{2})発走", html) or re.search(r"発走[^0-9]*(\d{1,2}:\d{2})", html)
    close_time = close_m.group(1) if close_m else None
    entries: list[dict[str, Any]] = []
    for match in re.finditer(
        r'<td class="Umaban(\d+)">(\d+)</td>(.*?)(?=<tr class="HorseList"|<td class="Umaban\d+">|\Z)',
        html,
        re.S,
    ):
        num = int(match.group(2))
        chunk = match.group(3)
        name_m = re.search(r'id="umalink_\d+"[^>]*>([^<]+)</a>', chunk)
        if not name_m:
            name_m = re.search(r'title="([^"]+)"[^>]*id="umalink_', chunk)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        if is_dummy_entry_name(name):
            continue
        odds_m = re.search(r'class="Popular Txt_R">\s*([\d.]+)', chunk)
        ninki_m = re.search(r'class="Popular Txt_C\s*">\s*<span>(\d+)</span>', chunk)
        popularity = int(ninki_m.group(1)) if ninki_m else 99
        odds = float(odds_m.group(1)) if odds_m else None
        rating = max(40, 100 - min(popularity, 12) * 8)
        if odds:
            rating = max(rating, round(120 - min(odds, 80)))
        entries.append(
            {
                "number": num,
                "name": name,
                "rating": rating,
                "popularity": popularity,
                "odds": odds,
            }
        )
    if len(entries) < 4:
        names = re.findall(r'id="umalink_\d+"[^>]*>([^<]+)</a>', html)
        nums = re.findall(r'<td class="Umaban\d+">(\d+)</td>', html)
        entries = []
        for i, name in enumerate(names):
            if i >= len(nums) or is_dummy_entry_name(name):
                continue
            entries.append(
                {
                    "number": int(nums[i]),
                    "name": name.strip(),
                    "rating": max(40, 100 - (i + 1) * 8),
                    "popularity": i + 1,
                }
            )
    real = [e for e in entries if not is_dummy_entry_name(e.get("name"))]
    if len(real) < 4:
        return None
    bettable = [e for e in real if 1 <= int(e["number"]) <= 9]
    ranked = sorted(
        bettable or real,
        key=lambda e: (e.get("popularity", 99), -float(e.get("rating", 0)), e["number"]),
    )
    axis = str(ranked[0]["number"])
    source = "nar.netkeiba" if circuit == "nar" else "netkeiba"
    return {
        "venue": venue,
        "race": race_num,
        "close_time": close_time or "12:00",
        "axis": axis,
        "rivals": [str(e["number"]) for e in ranked[1:3]],
        "entries": real,
        "notes": f"{source} race_id={race_id}",
        "fetched_data": {"source": source, "race_id": race_id, "circuit": circuit},
    }


def _parse_shutuba(html: str, race_id: str, circuit: str) -> dict[str, Any] | None:
    return parse_shutuba(html, race_id, circuit, None)


def fetch_races_for_date(date_str: str, circuit: str = "jra") -> list[dict[str, Any]]:
    outcome = fetch_races_outcome(date_str, circuit=circuit)
    return list(outcome.get("races") or [])


def fetch_races_outcome(date_str: str, circuit: str = "jra") -> dict[str, Any]:
    """date_str: YYYY-MM-DD。status は ok / no_meeting / fetch_failed。"""
    kaisai = date_str.replace("-", "")
    ids, venues = fetch_race_ids(kaisai, circuit=circuit)
    if ids is None:
        return {"races": [], "status": "fetch_failed", "error": "公式一覧を取得できませんでした"}
    if not ids:
        return {"races": [], "status": "no_meeting", "error": None}
    if circuit == "nar":
        shutuba = "https://nar.netkeiba.com/race/shutuba.html?race_id="
    else:
        shutuba = "https://race.netkeiba.com/race/shutuba.html?race_id="

    def _one(race_id: str) -> dict[str, Any] | None:
        html = _safe_text(f"{shutuba}{race_id}")
        if not html:
            return None
        parsed = parse_shutuba(html, race_id, circuit, venues)
        if not parsed:
            return None
        parsed["date"] = date_str
        return parsed

    races: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_one, race_id) for race_id in ids]
        for fut in as_completed(futs):
            try:
                item = fut.result()
            except Exception:
                continue
            if item:
                races.append(item)
    races = reject_dummy_races(races)
    races.sort(key=lambda r: (str(r.get("venue") or ""), int(r.get("race") or 0)))
    if not races:
        return {"races": [], "status": "fetch_failed", "error": "出馬表の公式情報を解析できませんでした"}
    return {"races": races, "status": "ok", "error": None}


def _valid_official_trifecta(a: int, b: int, c: int) -> str | None:
    if not (1 <= a <= 18 and 1 <= b <= 18 and 1 <= c <= 18):
        return None
    if len({a, b, c}) < 3:
        return None
    return f"{a}-{b}-{c}"


def parse_result_trifecta(html: str) -> dict[str, Any] | None:
    """公式結果ページの三連単と払戻。馬番は1〜18。メニューリンクの『3連単』は使わない。"""
    tan3 = re.search(
        r'(?:3連単|三連単)</th>\s*<td[^>]*class="Result"[^>]*>\s*<ul>\s*'
        r"<li><span>(\d{1,2})</span></li>\s*"
        r"<li><span>(\d{1,2})</span></li>\s*"
        r"<li><span>(\d{1,2})</span></li>.*?"
        r'class="Payout"><span>([0-9,]+)円</span>',
        html,
        re.S,
    )
    if tan3:
        trifecta = _valid_official_trifecta(int(tan3.group(1)), int(tan3.group(2)), int(tan3.group(3)))
        if trifecta:
            return {
                "trifecta": trifecta,
                "payout": int(tan3.group(4).replace(",", "")),
                "source": "netkeiba",
            }

    db_row = re.search(
        r"三連単</th>\s*<td>\s*(\d{1,2})-(\d{1,2})-(\d{1,2})\s*</td>\s*"
        r"<td[^>]*>\s*([0-9,]+)",
        html,
        re.S,
    )
    if db_row:
        trifecta = _valid_official_trifecta(int(db_row.group(1)), int(db_row.group(2)), int(db_row.group(3)))
        if trifecta:
            return {
                "trifecta": trifecta,
                "payout": int(db_row.group(4).replace(",", "")),
                "source": "netkeiba",
            }

    simple = re.search(
        r"(?:3連単|三連単)\s+(\d{1,2})-(\d{1,2})-(\d{1,2})\s+([0-9,]+)円",
        html,
    )
    if simple:
        trifecta = _valid_official_trifecta(
            int(simple.group(1)), int(simple.group(2)), int(simple.group(3))
        )
        if trifecta:
            return {
                "trifecta": trifecta,
                "payout": int(simple.group(4).replace(",", "")),
                "source": "netkeiba",
            }
    return None


def fetch_result_trifecta(race_id: str, circuit: str = "jra") -> dict[str, Any] | None:
    urls = [f"https://db.netkeiba.com/race/{race_id}/"]
    if circuit == "nar":
        urls = [
            f"https://nar.netkeiba.com/race/result.html?race_id={race_id}",
            f"https://db.netkeiba.com/race/{race_id}/",
        ]
    else:
        urls = [
            f"https://race.netkeiba.com/race/result.html?race_id={race_id}",
            f"https://db.netkeiba.com/race/{race_id}/",
        ]
    for url in urls:
        html = _safe_text(url)
        if not html:
            continue
        parsed = parse_result_trifecta(html)
        if parsed:
            return parsed
    return None


def fetch_results_for_predictions(records: list[dict[str, Any]], circuit: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in records:
        race_id = (record.get("fetched_data") or {}).get("race_id")
        if not race_id:
            notes = str(record.get("notes") or record.get("rationale") or "")
            found = re.search(r"race_id=(\d{12})", notes)
            race_id = found.group(1) if found else None
        if not race_id:
            continue
        parsed = fetch_result_trifecta(str(race_id), circuit=circuit)
        if not parsed:
            continue
        results.append(
            {
                "venue": record.get("venue"),
                "race": record.get("race"),
                "trifecta": parsed["trifecta"],
                "payout": parsed.get("payout", 0),
                "scenario_realized": None,
            }
        )
    return results
