"""BOAT RACE 公式サイト（boatrace.jp）から出走・展示・モーター・オッズ・結果を取得する。"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from typing import Any

from fetch.http import fetch_text

BASE = "https://www.boatrace.jp/owpc/pc/race"

VENUE_NAMES = {
    "01": "桐生",
    "02": "戸田",
    "03": "江戸川",
    "04": "平和島",
    "05": "多摩川",
    "06": "浜名湖",
    "07": "蒲郡",
    "08": "常滑",
    "09": "津",
    "10": "三国",
    "11": "びわこ",
    "12": "住之江",
    "13": "尼崎",
    "14": "鳴門",
    "15": "丸亀",
    "16": "児島",
    "17": "宮島",
    "18": "徳山",
    "19": "下関",
    "20": "若松",
    "21": "芦屋",
    "22": "福岡",
    "23": "唐津",
    "24": "大村",
}


def _hd(date_str: str) -> str:
    return date_str.replace("-", "")


def _jcd(code: str | int) -> str:
    return f"{int(code):02d}"


def _strip(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _floats(text: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+\.\d+|-?\d+", text)]


def _safe_fetch(url: str) -> str:
    try:
        return fetch_text(url)
    except Exception:
        return ""


def fetch_today_venues(hd: str) -> list[tuple[str, str]]:
    html = _safe_fetch(f"{BASE}/index?hd={hd}")
    if not html:
        html = _safe_fetch(f"{BASE}/index")
    codes = sorted(set(re.findall(r"raceindex\?jcd=(\d+)&amp;hd=", html)))
    return [(_jcd(c), VENUE_NAMES.get(_jcd(c), f"場{c}")) for c in codes]


def parse_raceindex(html: str, jcd: str, hd: str) -> list[dict[str, Any]]:
    races: list[dict[str, Any]] = []
    seen: set[int] = set()
    for match in re.finditer(
        r"racelist\?rno=(\d+)&amp;jcd=\d+&amp;hd=\d+\">(\d+)R</a>"
        r".{0,400}?<td>(\d{1,2}:\d{2})</td>",
        html,
        re.S,
    ):
        rno = int(match.group(1))
        if rno in seen:
            continue
        seen.add(rno)
        races.append(
            {
                "jcd": _jcd(jcd),
                "hd": hd,
                "rno": rno,
                "race": rno,
                "close_time": match.group(3),
            }
        )
    if not races:
        rnos = sorted({int(x) for x in re.findall(r"racelist\?rno=(\d+)&amp;jcd=", html)})
        times = re.findall(r"<td class=\" \">(\d{1,2}:\d{2})</td>", html)
        for idx, rno in enumerate(rnos):
            races.append(
                {
                    "jcd": _jcd(jcd),
                    "hd": hd,
                    "rno": rno,
                    "race": rno,
                    "close_time": times[idx] if idx < len(times) else "",
                }
            )
    return races


def parse_racelist_entries(html: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    blocks = re.split(r'<td class="is-boatColor(\d) is-fs14" rowspan="4">', html)
    if len(blocks) < 3:
        return entries
    for i in range(1, len(blocks), 2):
        boat = int(blocks[i])
        body = blocks[i + 1]
        toban_m = re.search(r"toban=(\d+)", body)
        name_m = re.search(r'class="is-fs18 is-fBold"><a[^>]*>([^<]+)</a>', body)
        class_m = re.search(r"/ <span[^>]*>([AB][12])</span>", body)
        cells = re.findall(
            r'<td class="[^"]*is-lineH2[^"]*"[^>]*rowspan="4">(.*?)</td>',
            body,
            re.S,
        )
        st_avg = winrate = motor_no = motor_2ren = boat_no = boat_2ren = None
        local_win = national_2ren = None
        if cells:
            st_vals = _floats(cells[0])
            st_avg = st_vals[-1] if st_vals else None
        if len(cells) > 1:
            nat = _floats(cells[1])
            winrate = nat[0] if nat else None
            national_2ren = nat[1] if len(nat) > 1 else None
        if len(cells) > 2:
            loc = _floats(cells[2])
            local_win = loc[0] if loc else None
        if len(cells) > 3:
            mot = _floats(cells[3])
            motor_no = int(mot[0]) if mot else None
            motor_2ren = mot[1] if len(mot) > 1 else None
        if len(cells) > 4:
            bt = _floats(cells[4])
            boat_no = int(bt[0]) if bt else None
            boat_2ren = bt[1] if len(bt) > 1 else None
        name = _strip(name_m.group(1)) if name_m else f"{boat}号艇"
        name = re.sub(r"\s+", "", name)
        rating = _entry_rating(winrate, motor_2ren, boat_2ren, boat)
        entries.append(
            {
                "number": boat,
                "name": name,
                "toban": toban_m.group(1) if toban_m else None,
                "racer_class": class_m.group(1) if class_m else None,
                "winrate": winrate,
                "national_2ren": national_2ren,
                "local_winrate": local_win,
                "st_avg": st_avg,
                "motor_no": motor_no,
                "motor_2ren": motor_2ren,
                "boat_no": boat_no,
                "boat_2ren": boat_2ren,
                "rating": rating,
            }
        )
    return entries


def parse_venue_name(html: str, jcd: str) -> str:
    match = re.search(r'text_place2_\d+\.png"[^>]*alt="([^"]+)"', html)
    if match:
        return match.group(1)
    return VENUE_NAMES.get(_jcd(jcd), f"場{jcd}")


def parse_beforeinfo(html: str) -> dict[int, dict[str, Any]]:
    info: dict[int, dict[str, Any]] = {}
    blocks = re.split(r'<td class="is-boatColor(\d) is-fs14" rowspan="4">', html)
    for i in range(1, len(blocks), 2):
        boat = int(blocks[i])
        body = blocks[i + 1]
        nums = re.findall(
            r'<td[^>]*rowspan="4"[^>]*>\s*([\d\.\-]+|&nbsp;)\s*</td>',
            body,
        )
        exhibition = None
        tilt = None
        if len(nums) >= 1 and nums[0] not in {"&nbsp;", ""}:
            try:
                exhibition = float(nums[0])
            except ValueError:
                exhibition = None
        if len(nums) >= 2 and nums[1] not in {"&nbsp;", ""}:
            try:
                tilt = float(nums[1])
            except ValueError:
                tilt = None
        info[boat] = {"exhibition_time": exhibition, "tilt": tilt}
    for match in re.finditer(
        r'table1_boatImage1Number is-type(\d)">(\d+)</span>.*?table1_boatImage1Time">([^<]+)</span>',
        html,
        re.S,
    ):
        boat = int(match.group(2))
        raw = match.group(3).strip().lstrip(".")
        try:
            st = float(f"0.{raw}") if match.group(3).strip().startswith(".") else float(raw)
        except ValueError:
            st = None
        info.setdefault(boat, {})
        info[boat]["exhibition_st"] = st
        info[boat]["course"] = int(match.group(1))
    return info


def parse_odds3t(html: str) -> list[dict[str, Any]]:
    values = []
    for match in re.finditer(r'class="oddsPoint\s*">\s*([\d.]+)', html):
        values.append(float(match.group(1)))
    if not values:
        return []
    favorite = min(values)
    return [{"rank": 1, "odds": favorite, "count": len(values)}]


def parse_result(html: str) -> dict[str, Any] | None:
    if "3連単" not in html:
        return None
    block = html.split("3連単", 1)[1]
    nums = re.findall(r"numberSet1_number is-type(\d)", block)
    if len(nums) < 3:
        return None
    trifecta = f"{nums[0]}-{nums[1]}-{nums[2]}"
    pay_m = re.search(r'is-payout1">&yen;([0-9,]+)', block)
    payout = int(pay_m.group(1).replace(",", "")) if pay_m else 0
    return {"trifecta": trifecta, "payout": payout, "source": "boatrace.jp"}


def _entry_rating(
    winrate: float | None,
    motor_2ren: float | None,
    boat_2ren: float | None,
    boat: int,
) -> float:
    score = 0.0
    if winrate is not None:
        score += winrate * 10
    if motor_2ren is not None:
        score += motor_2ren * 0.6
    if boat_2ren is not None:
        score += boat_2ren * 0.25
    score += {1: 18, 2: 10, 3: 7, 4: 4, 5: 2, 6: 1}.get(boat, 0)
    return round(score, 2)


def _build_candidate(
    *,
    date_str: str,
    venue: str,
    meta: dict[str, Any],
    entries: list[dict[str, Any]],
    exhibition: dict[int, dict[str, Any]],
    odds: list[dict[str, Any]],
) -> dict[str, Any]:
    for entry in entries:
        extra = exhibition.get(int(entry["number"]), {})
        entry["exhibition_time"] = extra.get("exhibition_time")
        entry["exhibition_st"] = extra.get("exhibition_st")
        entry["tilt"] = extra.get("tilt")
        entry["course"] = extra.get("course")
        if extra.get("exhibition_time"):
            # 展示が速いほど加点
            entry["rating"] = round(
                float(entry.get("rating", 0)) + max(0.0, (7.15 - extra["exhibition_time"]) * 25),
                2,
            )
    ranked = sorted(entries, key=lambda e: -float(e.get("rating", 0)))
    axis = str(ranked[0]["number"]) if ranked else "1"
    rivals = [str(e["number"]) for e in ranked[1:3]] or ["2", "3"]
    ratings = [float(e.get("rating", 0)) for e in ranked]
    gap = (ratings[0] - ratings[1]) if len(ratings) > 1 else 0.0
    winrates = [e.get("winrate") or 0 for e in entries]
    motors = [e.get("motor_2ren") or 0 for e in entries]
    exhibitions = [e.get("exhibition_time") for e in entries if e.get("exhibition_time")]

    axis_entry = next((e for e in entries if str(e["number"]) == axis), {})
    ability_gap = min(15, max(4, int(gap * 0.35)))
    axis_rel = min(20, max(8, int((axis_entry.get("winrate") or 4) * 2.8)))
    motor_score = min(18, max(6, int((axis_entry.get("motor_2ren") or 20) * 0.45)))
    exhib_score = 10
    if exhibitions:
        best = min(exhibitions)
        axis_ex = axis_entry.get("exhibition_time")
        exhib_score = 14 if axis_ex and axis_ex <= best + 0.03 else 9
    course_score = 12 if axis == "1" else 8 if axis == "2" else 5
    clarity = min(12, 6 + ability_gap // 3)
    odds_score = 8
    if odds:
        fav = odds[0]["odds"]
        if fav <= 8:
            odds_score = 10
        elif fav >= 40:
            odds_score = 4

    penalties: list[dict[str, Any]] = []
    if gap < 8:
        penalties.append({"code": "evenly_matched", "points": 6})
    if exhibitions and (max(exhibitions) - min(exhibitions) < 0.05):
        penalties.append({"code": "close_exhibition", "points": 4})
    if max(winrates) - min(winrates) < 1.0:
        penalties.append({"code": "wide_open", "points": 5})
    if not exhibitions:
        penalties.append({"code": "data_shortage", "points": 3})

    notes_parts = [
        f"{axis}号艇軸（{axis_entry.get('name', '')}）",
        f"全国勝率{axis_entry.get('winrate', '-')}",
        f"モーター2連対{axis_entry.get('motor_2ren', '-')}",
    ]
    if axis_entry.get("exhibition_time"):
        notes_parts.append(f"展示{axis_entry['exhibition_time']}")
    if odds:
        notes_parts.append(f"最人気オッズ{odds[0]['odds']}")

    return {
        "date": date_str,
        "venue": venue,
        "race": meta["race"],
        "close_time": meta.get("close_time"),
        "axis": axis,
        "rivals": rivals,
        "entries": entries,
        "factors": {
            "axis_reliability": axis_rel,
            "motor_2ren": motor_score,
            "exhibition_time": exhib_score,
            "ability_gap": ability_gap,
            "course_advantage": course_score,
            "scenario_clarity": clarity,
            "odds_clarity": odds_score,
        },
        "penalties": penalties,
        "notes": "、".join(notes_parts),
        "scenario": f"{axis}号艇が主導。2着候補{'・'.join(rivals)}",
        "odds_band_median": odds[0]["odds"] if odds else None,
        "fetched_data": {
            "source": "boatrace.jp",
            "jcd": meta["jcd"],
            "rno": meta["rno"],
            "hd": meta["hd"],
            "url": f"{BASE}/racelist?rno={meta['rno']}&jcd={meta['jcd']}&hd={meta['hd']}",
        },
    }


def _fetch_one_race(
    date_str: str, venue: str, meta: dict[str, Any], *, light: bool = True
) -> dict[str, Any] | None:
    jcd, hd, rno = meta["jcd"], meta["hd"], meta["rno"]
    racelist = _safe_fetch(f"{BASE}/racelist?rno={rno}&jcd={jcd}&hd={hd}")
    if not racelist:
        return None
    entries = parse_racelist_entries(racelist)
    if len(entries) < 6:
        return None
    from fetch.base import is_dummy_entry_name

    if any(is_dummy_entry_name(e.get("name")) for e in entries):
        return None
    exhibition: dict[int, dict[str, Any]] = {}
    odds: list[dict[str, Any]] = []
    if not light:
        before = _safe_fetch(f"{BASE}/beforeinfo?rno={rno}&jcd={jcd}&hd={hd}")
        exhibition = parse_beforeinfo(before) if before else {}
        odds_html = _safe_fetch(f"{BASE}/odds3t?rno={rno}&jcd={jcd}&hd={hd}")
        odds = parse_odds3t(odds_html) if odds_html else []
    if not venue:
        venue = parse_venue_name(racelist, jcd)
    return _build_candidate(
        date_str=date_str,
        venue=venue,
        meta=meta,
        entries=entries,
        exhibition=exhibition,
        odds=odds,
    )


def fetch_races_outcome(date_str: str, *, light: bool = True) -> dict[str, Any]:
    hd = _hd(date_str)
    index = _safe_fetch(f"{BASE}/index?hd={hd}")
    if not index:
        index = _safe_fetch(f"{BASE}/index")
    if not index:
        return {"races": [], "status": "fetch_failed", "error": "boatrace.jp の開催一覧を取得できませんでした"}
    venues = fetch_today_venues(hd)
    if not venues:
        return {"races": [], "status": "no_meeting", "error": None}
    jobs: list[tuple[str, dict[str, Any]]] = []
    for jcd, venue in venues:
        index_html = _safe_fetch(f"{BASE}/raceindex?jcd={jcd}&hd={hd}")
        if not index_html:
            continue
        metas = parse_raceindex(index_html, jcd, hd)
        picked = metas[-4:] if len(metas) > 4 else metas
        for meta in picked:
            jobs.append((venue, meta))
    if not jobs:
        return {"races": [], "status": "fetch_failed", "error": "各場の番組表を取得できませんでした"}
    races: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [
            pool.submit(_fetch_one_race, date_str, venue, meta, light=light)
            for venue, meta in jobs
        ]
        for fut in as_completed(futs):
            try:
                item = fut.result()
            except Exception:
                continue
            if item:
                races.append(item)
    races.sort(key=lambda r: (r.get("venue", ""), r.get("race", 0)))
    if not races:
        return {"races": [], "status": "fetch_failed", "error": "出走表の公式情報を解析できませんでした"}
    return {"races": races, "status": "ok", "error": None}


def fetch_races_for_date(date_str: str) -> list[dict[str, Any]]:
    return list(fetch_races_outcome(date_str).get("races") or [])


def fetch_result_trifecta(jcd: str, rno: int, hd: str) -> dict[str, Any] | None:
    html = _safe_fetch(f"{BASE}/raceresult?rno={rno}&jcd={_jcd(jcd)}&hd={hd}")
    if not html:
        return None
    return parse_result(html)


def fetch_results_for_predictions(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in predictions:
        data = record.get("fetched_data") or {}
        jcd = data.get("jcd")
        rno = data.get("rno") or record.get("race")
        hd = data.get("hd")
        if not (jcd and rno and hd):
            continue
        parsed = fetch_result_trifecta(str(jcd), int(rno), str(hd))
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
