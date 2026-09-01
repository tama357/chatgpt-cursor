"""GitHub Actions 用のクラウド実行。提出用競輪・Chatwork には触れない。"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from common.constants import SPORTS
from common.jst import today_str, yesterday_str
from excel.drive_sync import (
    DriveAuthError,
    format_read_only_report,
    pull_excel_files,
    pull_learning_data,
    push_learning_data,
    sync_excel_files,
    verify_excel_readable,
)


class CloudLockError(RuntimeError):
    pass


@contextmanager
def exclusive_lock(base_dir: Path) -> Iterator[None]:
    lock_dir = base_dir / ".drive"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "cloud.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise CloudLockError("別の個人予想ジョブが実行中です。同時実行はしません。") from exc
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def record_fetch_failure(state: dict[str, Any], *, date: str, reason: str) -> None:
    failures = state.setdefault("fetch_failures", [])
    if not isinstance(failures, list):
        failures = []
        state["fetch_failures"] = failures
    failures.append({"date": date, "reason": reason})


def _pull(base_dir: Path) -> str:
    lines = ["## Driveから取得（実行開始）"]
    excel = pull_excel_files(base_dir)
    lines.append(excel.format_report())
    if excel.failed:
        raise DriveAuthError("既存Excel 6ファイルをDriveから取得できませんでした。新規作成はしません。")
    data = pull_learning_data(base_dir)
    lines.append(data.format_report())
    if data.failed:
        raise DriveAuthError("学習データの取得に失敗しました。")
    return "\n".join(lines)


def _push(base_dir: Path) -> str:
    lines = ["## Driveへ保存（実行終了）"]
    excel = sync_excel_files(base_dir)
    lines.append(excel.format_report())
    data = push_learning_data(base_dir)
    lines.append(data.format_report())
    if excel.failed or data.failed:
        lines.append("⚠ Drive保存に失敗したファイルがあります。ローカル結果は残しています。")
    return "\n".join(lines)


def run_verify_drive(base_dir: Path) -> str:
    """書き込みなし。認証と既存6ファイルの読み取りだけ。"""
    report = verify_excel_readable(base_dir)
    return format_read_only_report(report)


def run_cloud_predict(
    base_dir: Path,
    *,
    target_date: str | None,
    force: bool,
    run_predict_today_fn,
    run_predict_fn,
) -> str:
    date = target_date or today_str()
    with exclusive_lock(base_dir):
        parts = [_pull(base_dir)]
        parts.append(
            run_predict_today_fn(
                base_dir,
                target_date=date,
                force=force,
                run_predict_fn=run_predict_fn,
            )
        )
        parts.append(_push(base_dir))
        return "\n\n".join(parts)


def run_cloud_results(
    base_dir: Path,
    *,
    target_date: str | None,
    force: bool,
    run_results_yesterday_fn,
    **kwargs,
) -> str:
    date = target_date or yesterday_str()
    with exclusive_lock(base_dir):
        parts = [_pull(base_dir)]
        parts.append(
            run_results_yesterday_fn(
                base_dir,
                target_date=date,
                force=force,
                **kwargs,
            )
        )
        parts.append(_push(base_dir))
        return "\n\n".join(parts)


def sports() -> tuple[str, ...]:
    return SPORTS
