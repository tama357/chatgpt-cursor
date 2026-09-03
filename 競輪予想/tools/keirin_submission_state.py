"""提出の内部状態。既存スプレッドシートには書かない。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from keirin_chatgpt_io import SchemaError, load_json
from keirin_jst import now_jst

STATE_FIELDS = ("sheet_written", "chatwork_sent", "processed_at")


def state_dir(root: Path) -> Path:
    return root / "data" / "state"


def submission_state_path(root: Path, date: str) -> Path:
    return state_dir(root) / f"submission_state_{date}.json"


def empty_submission_state(date: str) -> dict[str, Any]:
    return {
        "date": date,
        "sheet_written": False,
        "chatwork_sent": False,
        "processed_at": None,
    }


def load_submission_state(root: Path, date: str) -> dict[str, Any]:
    path = submission_state_path(root, date)
    if not path.exists():
        return empty_submission_state(date)
    data = load_json(path)
    state = empty_submission_state(date)
    state["sheet_written"] = bool(data.get("sheet_written"))
    state["chatwork_sent"] = bool(data.get("chatwork_sent"))
    processed = data.get("processed_at")
    state["processed_at"] = processed if isinstance(processed, str) or processed is None else str(processed)
    return state


def save_submission_state(root: Path, state: dict[str, Any]) -> Path:
    date = str(state.get("date") or "").strip()
    if not date:
        raise SchemaError("提出状態にdateがありません")
    path = submission_state_path(root, date)
    payload = {
        "date": date,
        "sheet_written": bool(state.get("sheet_written")),
        "chatwork_sent": bool(state.get("chatwork_sent")),
        "processed_at": state.get("processed_at"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    writing = path.with_name(path.name + ".writing")
    try:
        writing.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        loaded = json.loads(writing.read_text(encoding="utf-8"))
        if loaded != payload:
            raise SchemaError(f"提出状態の再読不一致: {writing}")
        os.replace(writing, path)
    except Exception:
        if writing.exists():
            try:
                writing.unlink()
            except OSError:
                pass
        raise
    return path


def mark_submission(
    root: Path,
    date: str,
    *,
    sheet_written: bool | None = None,
    chatwork_sent: bool | None = None,
) -> dict[str, Any]:
    state = load_submission_state(root, date)
    if sheet_written is True:
        state["sheet_written"] = True
    if chatwork_sent is True:
        state["chatwork_sent"] = True
    if sheet_written is True or chatwork_sent is True:
        state["processed_at"] = now_jst().isoformat(timespec="seconds")
    save_submission_state(root, state)
    return state


def chatwork_sending_enabled() -> bool:
    """個人運用では既定オフ。機能削除はせず、明示ONのときだけ送る。"""
    return os.environ.get("CHATWORK_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def already_fully_processed(state: dict[str, Any]) -> bool:
    if not chatwork_sending_enabled():
        return bool(state.get("sheet_written"))
    return bool(state.get("sheet_written")) and bool(state.get("chatwork_sent"))
