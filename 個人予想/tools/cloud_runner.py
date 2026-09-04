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

from common.constants import LEARNING_JSON_UNSAVED, SPORTS
from common.job_summary import collect_day_stats, format_github_summary, write_github_summary
from common.jst import today_str, yesterday_str
from common.state import production_state_problems
from excel.drive_inbox import pull_predictions_for_date, push_inbox_for_date
from excel.drive_sync import (
    DriveAuthError,
    format_read_only_report,
    pull_excel_files,
    push_learning_data,
    sync_excel_files,
    verify_excel_readable,
)
from ops_switch import personal_predict_enabled, stopped_message


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
    return "\n".join(lines)


def _push_excel(base_dir: Path) -> str:
    excel = sync_excel_files(base_dir)
    text = excel.format_report()
    if excel.failed:
        raise CloudJobError(
            text + "\n\nExcelのDrive保存に失敗したファイルがあります。GitHub Actions を失敗終了します。"
        )
    return text


def _push_inbox(base_dir: Path, date: str, *, kinds: tuple[str, ...]) -> str:
    report = push_inbox_for_date(base_dir, date, kinds=kinds)
    lines = ["## 学習JSON（inbox）"]
    if report.attempted == 0:
        lines.append("対象の日次JSONがローカルにありません。")
        return "\n".join(lines)
    lines.append(report.format_report())
    if report.failed:
        lines.append(LEARNING_JSON_UNSAVED)
        lines.append("Excelの成功は取り消していません。後からその日の日次JSONだけ穴埋めできます。")
    return "\n".join(lines)


def run_verify_drive(base_dir: Path) -> str:
    """書き込みなし。認証と既存6ファイルの読み取りだけ。1件でも失敗したら例外。"""
    if not personal_predict_enabled(base_dir):
        raise CloudJobError(stopped_message())
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
    """PC版CursorのローカルExcel・states・学習をDriveへ一度だけ送る。古いExcelは取得しない。"""
    if not personal_predict_enabled(base_dir):
        raise CloudJobError(stopped_message())
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
    """初期移行 bootstrap 専用。日次の予想・結果では使わない。"""
    problems = production_state_problems(base_dir)
    if problems:
        raise CloudJobError(
            "正規stateが揃っていないため初期移行を中止しました: "
            + ", ".join(problems)
            + "\n日次の予想・結果は正規stateなしでも実行できます。"
        )


def run_cloud_predict(
    base_dir: Path,
    *,
    target_date: str | None,
    force: bool,
    run_predict_today_fn,
    run_predict_fn,
) -> str:
    if not personal_predict_enabled(base_dir):
        raise CloudJobError(stopped_message())
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
        excel_ok = True
        excel_error = ""
        try:
            parts.append("## Driveへ保存（Excel）\n\n" + _push_excel(base_dir))
        except CloudJobError as exc:
            excel_ok = False
            excel_error = str(exc)
            parts.append(str(exc))
        parts.append(_push_inbox(base_dir, date, kinds=("predictions",)))
        text = "\n\n".join(parts)
        if not excel_ok:
            _finish_summary(
                base_dir,
                title="当日予想",
                date=date,
                drive_ok=False,
                extra=[excel_error],
            )
            raise CloudJobError(text)
        inbox_failed = LEARNING_JSON_UNSAVED in text
        _finish_summary(
            base_dir,
            title="当日予想",
            date=date,
            drive_ok=not inbox_failed,
            extra=[LEARNING_JSON_UNSAVED] if inbox_failed else [],
        )
        return text


def run_cloud_results(
    base_dir: Path,
    *,
    target_date: str | None,
    force: bool,
    run_results_yesterday_fn,
    **kwargs,
) -> str:
    if not personal_predict_enabled(base_dir):
        raise CloudJobError(stopped_message())
    date = target_date or yesterday_str()
    with exclusive_lock(base_dir):
        parts = [_pull(base_dir)]
        pulled = pull_predictions_for_date(base_dir, date)
        parts.append("## 前日の予想JSON（inbox）\n\n" + pulled.format_report())
        parts.append(
            run_results_yesterday_fn(
                base_dir,
                target_date=date,
                force=force,
                **kwargs,
            )
        )
        excel_ok = True
        excel_error = ""
        try:
            parts.append("## Driveへ保存（Excel）\n\n" + _push_excel(base_dir))
        except CloudJobError as exc:
            excel_ok = False
            excel_error = str(exc)
            parts.append(str(exc))
        parts.append(_push_inbox(base_dir, date, kinds=("results",)))
        text = "\n\n".join(parts)
        if not excel_ok:
            _finish_summary(
                base_dir,
                title="前日結果",
                date=date,
                drive_ok=False,
                extra=[excel_error],
            )
            raise CloudJobError(text)
        inbox_failed = LEARNING_JSON_UNSAVED in text
        _finish_summary(
            base_dir,
            title="前日結果",
            date=date,
            drive_ok=not inbox_failed,
            extra=[LEARNING_JSON_UNSAVED] if inbox_failed else [],
        )
        return text


def sports() -> tuple[str, ...]:
    return SPORTS
