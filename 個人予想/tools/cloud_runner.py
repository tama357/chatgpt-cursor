"""GitHub Actions 用のクラウド実行。提出用競輪・Chatwork には触れない。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # Windows のローカル確認用。クラウド実行は Ubuntu。
    fcntl = None  # type: ignore[assignment]

from common.constants import SPORTS
from common.job_summary import collect_day_stats, format_github_summary, write_github_summary
from common.jst import today_str, yesterday_str
from common.state import production_state_problems
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


class CloudJobError(RuntimeError):
    """GitHub Actions を失敗終了させる。"""


@contextmanager
def exclusive_lock(base_dir: Path) -> Iterator[None]:
    if fcntl is None:
        yield
        return
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
    text = "\n".join(lines)
    if excel.failed or data.failed:
        raise CloudJobError(
            text + "\n\nDrive保存に失敗したファイルがあります。GitHub Actions を失敗終了します。"
        )
    return text


def run_verify_drive(base_dir: Path) -> str:
    """書き込みなし。認証と既存6ファイルの読み取りだけ。1件でも失敗したら例外。"""
    report = verify_excel_readable(base_dir)
    text = format_read_only_report(report)
    write_github_summary(
        format_github_summary(
            title="Drive読み取り確認（書き込みなし）",
            target_date="-",
            drive_ok=report.failed == 0 and report.succeeded >= 6,
            drive_note=f"成功 {report.succeeded} / 失敗 {report.failed}",
            extra_lines=text.splitlines(),
        )
    )
    if report.failed or report.succeeded < 6:
        raise CloudJobError(text + "\n\n1件以上の読み取りに失敗したため終了コード1で終了します。")
    return text


REQUIRED_BOOTSTRAP_STATES = (
    "data/jra/state.json",
    "data/nar/state.json",
    "data/kyotei/state.json",
)


def _missing_bootstrap_files(base_dir: Path) -> list[str]:
    from excel.drive_sync import load_drive_config

    missing: list[str] = []
    config = load_drive_config(base_dir)
    for spec in config.get("files", {}).values():
        path = base_dir / "excel" / spec["local_name"]
        if not path.exists():
            missing.append(f"excel/{spec['local_name']}")
    missing.extend(production_state_problems(base_dir))
    return missing


def run_bootstrap_cloud(base_dir: Path, *, confirm: bool) -> str:
    """PC版CursorのローカルExcel・state・学習をDriveへ一度だけ送る。古いExcelは取得しない。"""
    if not confirm:
        raise CloudJobError(
            "初期移行は原田さんの明示許可と --i-confirm-bootstrap が必要です。実行していません。"
        )
    missing = _missing_bootstrap_files(base_dir)
    if missing:
        hint = (
            "GitHub Actions の checkout には、Windows ローカルの Git管理外 state がありません。"
            " 初期移行は PC 版 Cursor から実行してください。"
            if os.environ.get("GITHUB_ACTIONS") == "true"
            else (
                "PC版 Cursor で init-state を実行し、"
                "data/jra・data/nar・data/kyotei の正規stateと Excel があるか確認してください。"
            )
        )
        raise CloudJobError(
            "初期移行に必要な正規state / Excelがありません: "
            + ", ".join(missing)
            + "\n"
            + hint
            + "\nstate なしでは成功扱いにしません。"
        )

    lines = [
        "## 初期移行 bootstrap-cloud",
        "Driveから古いExcelは取得していません（9月2日の記録を消さないため）。",
        "既存6ファイルをID指定で上書きします。同名ファイルは新規作成しません。",
        "この処理は PC 版 Cursor のローカル state を使います。",
    ]
    excel = sync_excel_files(base_dir)
    lines.append(excel.format_report())
    data = push_learning_data(base_dir)
    lines.append(data.format_report())
    text = "\n".join(lines)
    write_github_summary(
        format_github_summary(
            title="初期移行 bootstrap-cloud",
            target_date="2026-09-03",
            drive_ok=excel.failed == 0 and data.failed == 0,
            extra_lines=lines,
        )
    )
    if excel.failed or data.failed:
        raise CloudJobError(text + "\n\n初期移行のDrive保存に失敗したため終了コード1で終了します。")
    skipped_state = [
        item.local_name
        for item in data.results
        if item.status == "skipped" and str(item.local_path).endswith("state.json")
    ]
    if skipped_state:
        raise CloudJobError(
            text + "\n\nstate が送れていません: " + ", ".join(skipped_state)
        )
    return text


def _finish_summary(
    base_dir: Path,
    *,
    title: str,
    date: str,
    drive_ok: bool,
    extra: list[str],
) -> None:
    write_github_summary(
        format_github_summary(
            title=title,
            target_date=date,
            stats=collect_day_stats(base_dir, date),
            drive_ok=drive_ok,
            extra_lines=extra,
        )
    )


def _require_ready_states(base_dir: Path) -> None:
    problems = production_state_problems(base_dir)
    if problems:
        raise CloudJobError(
            "正規stateが揃っていないため処理を中止しました: "
            + ", ".join(problems)
            + "\n出走取得・結果取得・Excel更新・state更新・Drive保存は行っていません。"
        )


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
        _require_ready_states(base_dir)
        parts.append(
            run_predict_today_fn(
                base_dir,
                target_date=date,
                force=force,
                run_predict_fn=run_predict_fn,
            )
        )
        try:
            parts.append(_push(base_dir))
            text = "\n\n".join(parts)
            _finish_summary(base_dir, title="当日予想", date=date, drive_ok=True, extra=[])
            return text
        except CloudJobError as exc:
            _finish_summary(
                base_dir,
                title="当日予想",
                date=date,
                drive_ok=False,
                extra=[str(exc)],
            )
            raise


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
        _require_ready_states(base_dir)
        parts.append(
            run_results_yesterday_fn(
                base_dir,
                target_date=date,
                force=force,
                **kwargs,
            )
        )
        try:
            parts.append(_push(base_dir))
            text = "\n\n".join(parts)
            _finish_summary(base_dir, title="前日結果", date=date, drive_ok=True, extra=[])
            return text
        except CloudJobError as exc:
            _finish_summary(
                base_dir,
                title="前日結果",
                date=date,
                drive_ok=False,
                extra=[str(exc)],
            )
            raise


def sports() -> tuple[str, ...]:
    return SPORTS
