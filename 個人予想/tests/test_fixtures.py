"""テスト用に examples を data/races へ置く。source は test_fixture（本番の sample フォールバックではない）。"""

from __future__ import annotations

import json
from pathlib import Path


def install_test_races(root: Path, sport: str, target_date: str) -> Path:
    src = root / "examples" / f"{sport}_races.sample.json"
    dest = root / "data" / "races" / sport / f"{target_date}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    data["source"] = "test_fixture"
    data["note"] = "テストデータ使用。本番の当日レースではない。"
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest
