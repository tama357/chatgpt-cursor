"""日本時間（Asia/Tokyo）の日付。UTCと混同しない。"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    return datetime.now(JST)


def today_str() -> str:
    return now_jst().date().isoformat()


def yesterday_str() -> str:
    return (now_jst().date() - timedelta(days=1)).isoformat()


def yyyymmdd(date_str: str) -> str:
    return date_str.replace("-", "")


def sheet_tab_date(date_str: str) -> str:
    """予想記入シートの当日タブ名 YYYY/MM/DD。構造は変えない。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%Y/%m/%d")


def summary_tab_month(date_str: str) -> str:
    """予想集計シートの月タブ名 YYYY/MM。構造は変えない。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%Y/%m")


def summary_day_label(date_str: str) -> str:
    """集計シート日付列の見え方（例: 9/3）。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.month}/{dt.day}"
