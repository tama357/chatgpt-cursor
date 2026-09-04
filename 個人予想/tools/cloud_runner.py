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
