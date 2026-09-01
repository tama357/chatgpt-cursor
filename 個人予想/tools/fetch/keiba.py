"""旧・統合競馬取得。個人予想では未使用（中央競馬は jra、地方競馬は nar）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fetch.jra import fetch_races as fetch_jra


def fetch_races(
    base_dir: Path,
    target_date: str,
    *,
    allow_sample: bool = False,
    try_auto: bool = True,
) -> list[dict[str, Any]]:
    return fetch_jra(
        base_dir, target_date, allow_sample=allow_sample, try_auto=try_auto
    )
