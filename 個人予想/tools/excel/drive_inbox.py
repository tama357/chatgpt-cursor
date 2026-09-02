"""学習用日次JSONを Drive inbox へ保存する。Excel 6ファイルは触らない。

フォルダが無いときは
マイドライブ / ChatGPT / 予想学習 / {競技} / inbox
を自動作成する。同名ファイルは更新し、重複作成しない。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from common.constants import (
    INBOX_DIR_NAME,
    INBOX_ROOT_NAME,
    INBOX_SPORT_FOLDERS,
    SPORTS,
)
from common.daily_json import (
    load_daily_json,
    prediction_reread_problems,
    predictions_path,
    results_path,
    results_reread_problems,
)
from excel.drive_sync import (
    JSON_MIME,
    DriveAuthError,
    DriveSyncReport,
    FileSyncResult,
    _drive_create,
    _drive_create_folder,
    _drive_download,
    _drive_find_all_in_folder,
    _drive_upload_replace,
    _get_access_token,
    load_drive_config,
    md5_hex,
)


class InboxSaveError(RuntimeError):
    pass


def _inbox_config(config: dict[str, Any]) -> dict[str, Any]:
    inbox = config.get("learning_inbox") or {}
    return {
        "root_name": inbox.get("root_name") or INBOX_ROOT_NAME,
        "inbox_name": inbox.get("inbox_name") or INBOX_DIR_NAME,
        "sports": inbox.get("sports") or {
            sport: {"folder_name": INBOX_SPORT_FOLDERS[sport]} for sport in SPORTS
        },
    }


def _sport_folder_name(config: dict[str, Any], sport: str) -> str:
    spec = _inbox_config(config)["sports"].get(sport) or {}
    return str(spec.get("folder_name") or INBOX_SPORT_FOLDERS[sport])


def _ensure_child_folder(
    token: str,
    parent_id: str,
    name: str,
    *,
    create: bool,
    create_folder: Callable[..., dict[str, Any]],
    find_all: Callable[..., list[dict[str, Any]]],
) -> str:
    existing = find_all(token, parent_id, name)
    folders = [
        item
        for item in existing
        if str(item.get("mimeType") or "") == "application/vnd.google-apps.folder"
        or not item.get("mimeType")
    ]
    if folders:
        return str(folders[0]["id"])
    if not create:
        raise InboxSaveError(f"フォルダ '{name}' がありません")
    created = create_folder(token, parent_id, name)
    folder_id = created.get("id")
    if not folder_id:
        raise InboxSaveError(f"フォルダ '{name}' を作成できませんでした")
    return str(folder_id)


def ensure_sport_inbox_folder(
    base_dir: Path,
    sport: str,
    *,
    access_token: str | None = None,
    create: bool = True,
    create_folder: Callable[..., dict[str, Any]] | None = None,
    find_all: Callable[..., list[dict[str, Any]]] | None = None,
) -> str:
    """ChatGPT / 予想学習 / {競技} / inbox を探す。create=True なら無ければ作る。"""
    if sport not in INBOX_SPORT_FOLDERS:
        raise InboxSaveError(f"未対応の競技です: {sport}")
    config = load_drive_config(base_dir)
    token = access_token or _get_access_token(base_dir)
    parent = str(config["folder_id"])
    inbox_cfg = _inbox_config(config)
    folder_create = create_folder or _drive_create_folder
    search = find_all or _drive_find_all_in_folder
    learning_id = _ensure_child_folder(
        token,
        parent,
        str(inbox_cfg["root_name"]),
        create=create,
        create_folder=folder_create,
        find_all=search,
    )
    sport_id = _ensure_child_folder(
        token,
        learning_id,
        _sport_folder_name(config, sport),
        create=create,
        create_folder=folder_create,
        find_all=search,
    )
    return _ensure_child_folder(
        token,
        sport_id,
        str(inbox_cfg["inbox_name"]),
        create=create,
        create_folder=folder_create,
        find_all=search,
    )


def _upsert_named_file(
    token: str,
    folder_id: str,
    local_path: Path,
    title: str,
    *,
    find_all: Callable[..., list[dict[str, Any]]],
    upload_replace: Callable[..., Any],
    create_file: Callable[..., dict[str, Any]],
) -> tuple[str, str]:
    matches = [
        item
        for item in find_all(token, folder_id, title)
        if str(item.get("mimeType") or JSON_MIME) != "application/vnd.google-apps.folder"
    ]
    if matches:
        file_id = str(matches[0]["id"])
        upload_replace(token, file_id, local_path, mime=JSON_MIME)
        return file_id, "updated"
    created = create_file(token, folder_id, title, local_path, mime=JSON_MIME)
    file_id = created.get("id")
    if not file_id:
        raise InboxSaveError(f"{title} をDriveへ作成できませんでした")
    return str(file_id), "created"


def upsert_inbox_file(
    base_dir: Path,
    sport: str,
    local_path: Path,
    *,
    access_token: str | None = None,
    reread_check: Callable[[dict[str, Any]], list[str]] | None = None,
) -> FileSyncResult:
    """同名ファイルがあれば更新、無ければ1件だけ作る。保存後に再読する。"""
    result = FileSyncResult(
        key=f"{sport}:{local_path.name}",
        local_name=local_path.name,
        local_path=local_path,
        drive_file_id=None,
        status="pending",
        message="",
    )
    if not local_path.exists():
        result.status = "failed"
        result.message = f"ローカルに {local_path.name} がありません"
        return result
    try:
        token = access_token or _get_access_token(base_dir)
        folder_id = ensure_sport_inbox_folder(base_dir, sport, access_token=token)
        file_id, action = _upsert_named_file(
            token,
            folder_id,
            local_path,
            local_path.name,
            find_all=_drive_find_all_in_folder,
            upload_replace=_drive_upload_replace,
            create_file=_drive_create,
        )
        raw = _drive_download(token, file_id)
        loaded = json.loads(raw.decode("utf-8"))
        if reread_check:
            problems = reread_check(loaded)
            if problems:
                raise InboxSaveError("再読確認に失敗: " + "; ".join(problems))
        result.drive_file_id = file_id
        result.local_size = local_path.stat().st_size
        result.local_md5 = md5_hex(local_path.read_bytes())
        result.drive_size = len(raw)
        result.status = "success"
        result.message = f"inboxへ{action}し、再読しました"
        return result
    except DriveAuthError as exc:
        result.status = "failed"
        result.message = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.message = str(exc)
        return result


def pull_inbox_file(
    base_dir: Path,
    sport: str,
    filename: str,
    dest: Path,
    *,
    access_token: str | None = None,
) -> FileSyncResult:
    result = FileSyncResult(
        key=f"{sport}:{filename}",
        local_name=filename,
        local_path=dest,
        drive_file_id=None,
        status="pending",
        message="",
    )
    try:
        token = access_token or _get_access_token(base_dir)
        folder_id = ensure_sport_inbox_folder(
            base_dir, sport, access_token=token, create=False
        )
        matches = _drive_find_all_in_folder(token, folder_id, filename)
        files = [
            item
            for item in matches
            if str(item.get("mimeType") or JSON_MIME) != "application/vnd.google-apps.folder"
        ]
        if not files:
            result.status = "skipped"
            result.message = "inboxにファイルがありません"
            return result
        file_id = str(files[0]["id"])
        raw = _drive_download(token, file_id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        load_daily_json(dest)
        result.drive_file_id = file_id
        result.local_size = len(raw)
        result.status = "success"
        result.message = "inboxから取得しました"
        return result
    except DriveAuthError as exc:
        result.status = "failed"
        result.message = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.message = str(exc)
        return result


def push_inbox_for_date(
    base_dir: Path,
    date: str,
    *,
    kinds: tuple[str, ...] = ("predictions", "results"),
    sports: tuple[str, ...] | None = None,
    reread_predictions: Callable[[str, dict[str, Any]], list[str]] | None = None,
    reread_results: Callable[[str, dict[str, Any]], list[str]] | None = None,
) -> DriveSyncReport:
    report = DriveSyncReport()
    target_sports = sports or SPORTS
    for sport in target_sports:
        mapping = {
            "predictions": predictions_path(base_dir, sport, date),
            "results": results_path(base_dir, sport, date),
        }
        for kind in kinds:
            path = mapping[kind]
            if not path.exists():
                continue
            expected = load_daily_json(path)

            def _check(
                loaded: dict[str, Any],
                *,
                _kind: str = kind,
                _sport: str = sport,
                _expected: dict[str, Any] = expected,
            ) -> list[str]:
                if _kind == "predictions":
                    if reread_predictions:
                        return reread_predictions(_sport, loaded) or []
                    return prediction_reread_problems(loaded, _expected)
                if reread_results:
                    return reread_results(_sport, loaded) or []
                return results_reread_problems(loaded, _expected)

            report.attempted += 1
            item = upsert_inbox_file(base_dir, sport, path, reread_check=_check)
            report.results.append(item)
            if item.status == "success":
                report.succeeded += 1
            else:
                report.failed += 1
    return report


def pull_predictions_for_date(
    base_dir: Path,
    date: str,
    *,
    sports: tuple[str, ...] | None = None,
) -> DriveSyncReport:
    report = DriveSyncReport()
    for sport in sports or SPORTS:
        dest = predictions_path(base_dir, sport, date)
        report.attempted += 1
        item = pull_inbox_file(base_dir, sport, dest.name, dest)
        report.results.append(item)
        if item.status == "success":
            report.succeeded += 1
        elif item.status == "skipped":
            report.skipped += 1
        else:
            report.failed += 1
    return report
