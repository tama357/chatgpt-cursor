"""個人予想の運用スイッチ。PERSONAL_PREDICT_ENABLED=false のあいだ実行しない。"""

from __future__ import annotations

import json
import os
from pathlib import Path

STOPPED_MESSAGE = (
    "個人予想（中央競馬・地方競馬・競艇）は停止中です。"
    "PERSONAL_PREDICT_ENABLED=false。"
    "明示的な再開指示があるまで、予想・結果・Excel・Drive・inbox・state・学習は実行しません。"
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def personal_predict_enabled(root: Path | None = None) -> bool:
    env = os.environ.get("PERSONAL_PREDICT_ENABLED", "").strip().lower()
    if env in {"true", "1", "yes"}:
        return True
    if env in {"false", "0", "no"}:
        return False
    base = root if root is not None else PACKAGE_ROOT
    path = base / "config" / "ops.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("PERSONAL_PREDICT_ENABLED") is True
    return True


def stopped_message() -> str:
    return STOPPED_MESSAGE
