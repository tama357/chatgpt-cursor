from __future__ import annotations

import re
import urllib.error
from typing import Any

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


def _list_urls(kaisai_date: str, circuit: str) -> list[str]:
    if circuit == "nar":
        host = "https://nar.netkeiba.com/top"
    else:
        host = "https://race.netkeiba.com/top"
    return [
        f"{host}/race_list_get_date_list.html?kaisai_date={kaisai_date}",
        f"{host}/race_list_sub.html?kaisai_date={kaisai_date}",
        f"{host}/race_list.html?kaisai_date={kaisai_date}",
    ]


def fetch_race_ids(kaisai_date: str, circuit: str = "jra") -> list[str] | None:
    """kaisai_date: YYYYMMDD。通信失敗時は None、開催なしは空リスト。"""
    ids: list[str] = []
    any_ok = False
    for url in _list_urls(kaisai_date, circuit):
        try:
            html = fetch_text(url, encoding="euc-jp")
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        any_ok = True
        ids.extend(re.findall(r"race_id=(\d{12})", html))
        ids.extend(re.findall(r"/race/(\d{12})", html))
        ids.extend(re.findall(r"shutuba\.html\?race_id=(\d{12})", html))
    if not any_ok:
        return None
    filtered: list[str] = []
    for race_id in sorted(set(ids)):
        venue_code = race_id[4:6]
        if circuit == "jra" and venue_code not in JRA_VENUE:
            continue
        if circuit == "nar" and venue_code in JRA_VENUE:
            continue
        filtered.append(race_id)
    return filtered


def _parse_shutuba(html: str, race_id: str, circuit: str) -> dict[str, Any] | None:
    venue_code = race_id[4:6]
    if circuit == "jra":
        venue = JRA_VENUE.get(venue_code, venue_code)
    else:
        venue = VENUE_CODE.get(venue_code, venue_code)
    race_num = int(race_id[10:12])
    close_match = re.search(r"発走[^0-9]*(\d{1,2}:\d{2})", html)
    close_time = close_match.group(1) if close_match else "12:00"
    entries: list[dict[str, Any]] = []
    for row in re.finditer(
        r'<td[^>]*class="[^"]*Umaban[^"]*"[^>]*>\s*(\d+)\s*</td>.*?'
        r'<span[^>]*class="[^"]*HorseName[^"]*"[^>]*>([^<]+)</span>',
        html,
        re.S,
    ):
        num, name = row.group(1), row.group(2).strip()
        pop_match = re.search(rf"Umaban[^>]*>{num}<.*?Ninki[^>]*>\s*(\d+)", html, re.S)
        popularity = int(pop_match.group(1)) if pop_match else 99
        entries.append(
            {
                "number": int(num),
                "name": name,
                "rating": max(40, 100 - popularity * 8),
                "popularity": popularity,
            }
        )
    if len(entries) < 4:
        nums = re.findall(r'class="Umaban[^"]*"[^>]*>\s*(\d+)\s*<', html)
        entries = [
            {"number": int(n), "name": f"馬{n}", "rating": 50, "popularity": i + 1}
            for i, n in enumerate(dict.fromkeys(nums))
        ]
    if len(entries) < 4:
        return None
    ranked = sorted(entries, key=lambda e: (-e["rating"], e["number"]))
    axis = str(ranked[0]["number"])
    source = "nar.netkeiba" if circuit == "nar" else "netkeiba"
    return {
        "venue": venue,
        "race": race_num,
        "close_time": close_time,
        "axis": axis,
        "entries": entries,
        "notes": f"{source} race_id={race_id}",
        "fetched_data": {"source": source, "race_id": race_id, "circuit": circuit},
    }


def fetch_races_for_date(date_str: str, circuit: str = "jra") -> list[dict[str, Any]]:
    """date_str: YYYY-MM-DD。開催なし・失敗は空リスト。"""
    kaisai = date_str.replace("-", "")
    ids = fetch_race_ids(kaisai, circuit=circuit)
    if not ids:
        return []
    if circuit == "nar":
        shutuba = "https://nar.netkeiba.com/race/shutuba.html?race_id="
    else:
        shutuba = "https://race.netkeiba.com/race/shutuba.html?race_id="
    races: list[dict[str, Any]] = []
    for race_id in ids:
        url = f"{shutuba}{race_id}"
        try:
            html = fetch_text(url, encoding="euc-jp")
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        parsed = _parse_shutuba(html, race_id, circuit)
        if parsed:
            parsed["date"] = date_str
            races.append(parsed)
    return races


def fetch_result_trifecta(race_id: str, circuit: str = "jra") -> dict[str, Any] | None:
    urls = [f"https://db.netkeiba.com/race/{race_id}/"]
    if circuit == "nar":
        urls = [
            f"https://nar.netkeiba.com/race/result.html?race_id={race_id}",
            f"https://db.netkeiba.com/race/{race_id}/",
        ]
    html = ""
    for url in urls:
        try:
            html = fetch_text(url, encoding="euc-jp")
            break
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    if not html:
        return None
    pay = re.search(r"3連単[^0-9]*(\d+)-(\d+)-(\d+)[^\d]*(\d{1,3}(?:,\d{3})*)", html)
    if not pay:
        rows = re.findall(
            r'<td[^>]*class="[^"]*Umaban[^"]*"[^>]*>\s*(\d+)\s*</td>',
            html,
        )
        if len(rows) >= 3:
            return {"trifecta": f"{rows[0]}-{rows[1]}-{rows[2]}", "payout": 0, "source": "netkeiba"}
        return None
    trifecta = f"{pay.group(1)}-{pay.group(2)}-{pay.group(3)}"
    payout = int(pay.group(4).replace(",", ""))
    return {"trifecta": trifecta, "payout": payout, "source": "netkeiba"}
