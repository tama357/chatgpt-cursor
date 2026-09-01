"""日本時間（Asia/Tokyo）の日付。GitHub Actions の UTC と混同しない。"""

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
