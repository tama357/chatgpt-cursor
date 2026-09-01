from __future__ import annotations

import re
import urllib.error
from typing import Any

from .http import fetch_text


VENUE_CODE = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


def fetch_race_ids(kaisai_date: str) -> list[str]:
    """kaisai_date: YYYYMMDD"""
    urls = [
        f"https://race.netkeiba.com/top/race_list_get_date_list.html?kaisai_date={kaisai_date}",
        f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={kaisai_date}",
        f"https://race.netkeiba.com/top/race_list.html?kaisai_date={kaisai_date}",
    ]
    ids: list[str] = []
    for url in urls:
        try:
            html = fetch_text(url, encoding="euc-jp")
        except (urllib.error.URLError, TimeoutError):
            continue
        ids.extend(re.findall(r"race_id=(\d{12})", html))
        ids.extend(re.findall(r"/race/(\d{12})", html))
        ids.extend(re.findall(r"shutuba\.html\?race_id=(\d{12})", html))
    return sorted(set(ids))


def _parse_shutuba(html: str, race_id: str) -> dict[str, Any] | None:
    venue_code = race_id[4:6]
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
        # fallback: umaban only
        nums = re.findall(r'class="Umaban[^"]*"[^>]*>\s*(\d+)\s*<', html)
        entries = [
            {"number": int(n), "name": f"馬{n}", "rating": 50, "popularity": i + 1}
            for i, n in enumerate(dict.fromkeys(nums))
        ]
    if len(entries) < 4:
        return None
    ranked = sorted(entries, key=lambda e: (-e["rating"], e["number"]))
    axis = str(ranked[0]["number"])
    return {
        "venue": venue,
        "race": race_num,
        "close_time": close_time,
        "axis": axis,
        "entries": entries,
        "notes": f"netkeiba race_id={race_id}",
        "fetched_data": {"source": "netkeiba", "race_id": race_id},
    }


def fetch_races_for_date(date_str: str) -> list[dict[str, Any]]:
    """date_str: YYYY-MM-DD"""
    kaisai = date_str.replace("-", "")
    races: list[dict[str, Any]] = []
    for race_id in fetch_race_ids(kaisai):
        url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        try:
            html = fetch_text(url, encoding="euc-jp")
        except (urllib.error.URLError, TimeoutError):
            continue
        parsed = _parse_shutuba(html, race_id)
        if parsed:
            parsed["date"] = date_str
            races.append(parsed)
    return races


def fetch_result_trifecta(race_id: str) -> dict[str, Any] | None:
    url = f"https://db.netkeiba.com/race/{race_id}/"
    try:
        html = fetch_text(url, encoding="euc-jp")
    except (urllib.error.URLError, TimeoutError):
        return None
    # 三連単払戻 例: 3-4-1 2,340円
    pay = re.search(r"3連単[^0-9]*(\d)-(\d)-(\d)[^\d]*(\d{1,3}(?:,\d{3})*)", html)
    if not pay:
        # 着順から組み立て
        rows = re.findall(
            r'<td[^>]*class="[^"]*Umaban[^"]*"[^>]*>\s*(\d+)\s*</td>',
            html,
        )
        if len(rows) >= 3:
            trifecta = f"{rows[0]}-{rows[1]}-{rows[2]}"
            return {"trifecta": trifecta, "payout": 0, "source": "db.netkeiba"}
        return None
    trifecta = f"{pay.group(1)}-{pay.group(2)}-{pay.group(3)}"
    payout = int(pay.group(4).replace(",", ""))
    return {"trifecta": trifecta, "payout": payout, "source": "db.netkeiba"}
