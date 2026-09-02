"""完成済みの当日JSONだけを、既存の競輪学習inboxへ同期する。

対象は prediction_input_日付.json と prediction_final_日付.json のみ。
.tmp.json、学習用日次JSON、シート、keirin_learning_state.json は触らない。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from keirin_chatgpt_io import (
    SchemaError,
    chatgpt_final_path,
    chatgpt_input_path,
    is_chatgpt_input_ready,
    is_input_ready_payload,
    load_json,
    missing_final_prediction_fields,
    require_chatgpt_final,
    save_json,
)
from keirin_drive_state import (
    ACCESS_TOKEN_ENV,
    DRIVE_API_BASE,
    DRIVE_UPLOAD_BASE,
    JSON_MIME,
    SA_JSON_ENV,
    get_access_token,
)

FOLDER_MIME = "application/vnd.google-apps.folder"
INBOX_PATH_LABEL = "マイドライブ / ChatGPT / 競輪学習 / inbox"
FOLDER_CHAIN = ("ChatGPT", "競輪学習", "inbox")
STATE_FILE_NAME = "keirin_learning_state.json"
LEARNING_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\.(predictions|results|learning)\.json$"
)
INPUT_NAME_RE = re.compile(r"^prediction_input_(\d{4}-\d{2}-\d{2})\.json$")
FINAL_NAME_RE = re.compile(r"^prediction_final_(\d{4}-\d{2}-\d{2})\.json$")


class DriveInboxError(RuntimeError):
    pass


class DriveInboxStore(Protocol):
    def find_inbox_folder_id(self) -> str:
        """既存の競輪学習inboxを探す。無ければ作らない。"""

    def find_file(self, folder_id: str, name: str) -> dict[str, Any] | None:
        """inbox内の同名ファイルを1件返す。無ければ None。"""

    def download(self, file_id: str) -> bytes:
        """既存ファイルの中身を返す。"""

    def upload_replace(self, file_id: str, content: bytes) -> dict[str, Any]:
        """既存ファイルを上書きする。"""

    def create_file(self, folder_id: str, name: str, content: bytes) -> dict[str, Any]:
        """inbox内に当日JSONを1件作る。フォルダやstateは作らない。"""


def credentials_available() -> bool:
    return bool(
        os.environ.get(ACCESS_TOKEN_ENV, "").strip()
        or os.environ.get(SA_JSON_ENV, "").strip()
    )


def is_tmp_name(name: str) -> bool:
    return name.endswith(".tmp.json") or ".tmp." in name


def parse_allowed_daily_name(name: str) -> tuple[str, str]:
    """許可された当日JSONなら (kind, date)。それ以外はエラー。"""
    if is_tmp_name(name):
        raise DriveInboxError(f"{name} は作成途中のためDriveへ出しません")
    if name == STATE_FILE_NAME:
        raise DriveInboxError("keirin_learning_state.json は同期対象外です")
    if LEARNING_NAME_RE.match(name):
        raise DriveInboxError(f"{name} は既存の学習用JSONのため、この同期では扱いません")
    input_match = INPUT_NAME_RE.match(name)
    if input_match:
        return "input", input_match.group(1)
    final_match = FINAL_NAME_RE.match(name)
    if final_match:
        return "final", final_match.group(1)
    raise DriveInboxError(
        f"{name} は同期対象外です。完成済みの prediction_input_日付.json と "
        "prediction_final_日付.json だけをDriveへ出します"
    )


def assert_payload_syncable(name: str, payload: dict[str, Any]) -> None:
    kind, date = parse_allowed_daily_name(name)
    if str(payload.get("date") or "").strip() != date:
        raise DriveInboxError(
            f"{name} の日付が中身と一致しません（中身={payload.get('date')}）"
        )
    if kind == "input":
        if not is_input_ready_payload(payload):
            raise DriveInboxError(
                f"{name} は status=ready かつ data_complete=true ではないためDriveへ出しません"
            )
        return
    missing = missing_final_prediction_fields(payload)
    if missing:
        raise DriveInboxError(
            f"{name} はChatGPTの完成版ではないためDriveへ出しません。"
            "欠けている項目: " + "、".join(missing)
        )


class MemoryDriveInboxStore:
    """テスト用。既存の ChatGPT / 競輪学習 / inbox だけを持つ。"""

    def __init__(self) -> None:
        self.folders: dict[str, dict[str, str]] = {
            "folder-chatgpt": {"name": "ChatGPT", "parent": "root"},
            "folder-keirin": {"name": "競輪学習", "parent": "folder-chatgpt"},
            "folder-inbox": {"name": "inbox", "parent": "folder-keirin"},
        }
        self.files: dict[str, dict[str, Any]] = {}
        self.uploads: list[str] = []
        self.creates: list[str] = []
        self.downloads: list[str] = []
        self._next = 1

    def find_inbox_folder_id(self) -> str:
        return "folder-inbox"

    def find_file(self, folder_id: str, name: str) -> dict[str, Any] | None:
        for file_id, item in self.files.items():
            if item["parent"] == folder_id and item["name"] == name:
                return {"id": file_id, "name": name}
        return None

    def download(self, file_id: str) -> bytes:
        self.downloads.append(file_id)
        if file_id not in self.files:
            raise DriveInboxError(f"Drive file ID が存在しません: {file_id}")
        return bytes(self.files[file_id]["content"])

    def upload_replace(self, file_id: str, content: bytes) -> dict[str, Any]:
        if file_id not in self.files:
            raise DriveInboxError(f"Drive file ID が存在しません: {file_id}")
        self.uploads.append(self.files[file_id]["name"])
        self.files[file_id]["content"] = bytes(content)
        return {"id": file_id}

    def create_file(self, folder_id: str, name: str, content: bytes) -> dict[str, Any]:
        if folder_id != "folder-inbox":
            raise DriveInboxError("inbox以外への作成はしません")
        file_id = f"file-{self._next}"
        self._next += 1
        self.creates.append(name)
        self.files[file_id] = {
            "name": name,
            "parent": folder_id,
            "content": bytes(content),
        }
        return {"id": file_id, "name": name}


class GoogleDriveInboxStore:
    """フォルダ名で既存inboxを探し、完成済み当日JSONだけをupsertする。"""

    def __init__(self, access_token: str | None = None) -> None:
        self._access_token = access_token

    def _token(self) -> str:
        return get_access_token(self._access_token)

    def _http(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _search(self, query: str) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "fields": "files(id,name,mimeType)",
                "pageSize": 20,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
        )
        status, raw = self._http(
            f"{DRIVE_API_BASE}?{params}",
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        if status != 200:
            raise DriveInboxError(
                f"Drive検索に失敗しました HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        files = json.loads(raw.decode("utf-8")).get("files") or []
        return [item for item in files if isinstance(item, dict)]

    def _child_folder(self, parent_id: str, name: str) -> str | None:
        escaped = name.replace("'", "\\'")
        matches = self._search(
            f"'{parent_id}' in parents and name = '{escaped}' "
            f"and mimeType = '{FOLDER_MIME}' and trashed = false"
        )
        exact = [item for item in matches if item.get("name") == name]
        if not exact:
            return None
        return str(exact[0]["id"])

    def find_inbox_folder_id(self) -> str:
        chatgpt_matches = self._search(
            f"name = '{FOLDER_CHAIN[0]}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        )
        for folder in chatgpt_matches:
            if folder.get("name") != FOLDER_CHAIN[0]:
                continue
            learning_id = self._child_folder(str(folder["id"]), FOLDER_CHAIN[1])
            if not learning_id:
                continue
            inbox_id = self._child_folder(learning_id, FOLDER_CHAIN[2])
            if inbox_id:
                return inbox_id
        raise DriveInboxError(
            f"{INBOX_PATH_LABEL} が見つかりません。フォルダは新規作成しません。"
        )

    def find_file(self, folder_id: str, name: str) -> dict[str, Any] | None:
        escaped = name.replace("'", "\\'")
        matches = self._search(
            f"'{folder_id}' in parents and name = '{escaped}' and trashed = false"
        )
        files = [
            item
            for item in matches
            if item.get("name") == name and item.get("mimeType") != FOLDER_MIME
        ]
        if not files:
            return None
        return files[0]

    def download(self, file_id: str) -> bytes:
        quoted = urllib.parse.quote(file_id, safe="")
        status, raw = self._http(
            f"{DRIVE_API_BASE}/{quoted}?alt=media&supportsAllDrives=true",
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        if status != 200:
            raise DriveInboxError(
                f"Drive download 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        return raw

    def upload_replace(self, file_id: str, content: bytes) -> dict[str, Any]:
        quoted = urllib.parse.quote(file_id, safe="")
        query = urllib.parse.urlencode({"uploadType": "media", "supportsAllDrives": "true"})
        status, raw = self._http(
            f"{DRIVE_UPLOAD_BASE}/{quoted}?{query}",
            method="PATCH",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": JSON_MIME,
                "Content-Length": str(len(content)),
            },
            body=content,
        )
        if status not in (200, 201):
            raise DriveInboxError(
                f"Drive upload 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        if not raw:
            return {"id": file_id}
        return json.loads(raw.decode("utf-8"))

    def create_file(self, folder_id: str, name: str, content: bytes) -> dict[str, Any]:
        parse_allowed_daily_name(name)
        metadata = json.dumps(
            {"name": name, "parents": [folder_id], "mimeType": JSON_MIME}
        ).encode("utf-8")
        boundary = "cursor_keirin_inbox_boundary"
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8")
            + metadata
            + f"\r\n--{boundary}\r\nContent-Type: {JSON_MIME}\r\n\r\n".encode("utf-8")
            + content
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        query = urllib.parse.urlencode({"uploadType": "multipart", "supportsAllDrives": "true"})
        status, raw = self._http(
            f"{DRIVE_UPLOAD_BASE}?{query}",
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": f"multipart/related; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
            body=body,
        )
        if status not in (200, 201):
            raise DriveInboxError(
                f"Drive create 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        return json.loads(raw.decode("utf-8"))


def resolve_store(store: DriveInboxStore | None) -> DriveInboxStore | None:
    if store is not None:
        return store
    if not credentials_available():
        return None
    return GoogleDriveInboxStore()


def _encode(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def upsert_completed_json(
    store: DriveInboxStore,
    name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    assert_payload_syncable(name, payload)
    folder_id = store.find_inbox_folder_id()
    content = _encode(payload)
    existing = store.find_file(folder_id, name)
    if existing:
        store.upload_replace(str(existing["id"]), content)
        file_id = str(existing["id"])
        action = "updated"
    else:
        created = store.create_file(folder_id, name, content)
        file_id = str(created.get("id") or "")
        if not file_id:
            raise DriveInboxError(f"{name} をDriveへ作成できませんでした")
        action = "created"
    raw = store.download(file_id)
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DriveInboxError(f"{name} の再読がJSONではありません") from exc
    if loaded != payload:
        raise DriveInboxError(f"{name} のDrive再読がローカルと一致しません")
    return {"name": name, "file_id": file_id, "action": action, "path": INBOX_PATH_LABEL}


def sync_ready_input(
    root,
    date: str,
    *,
    store: DriveInboxStore | None = None,
) -> dict[str, Any] | None:
    client = resolve_store(store)
    if client is None:
        return None
    if not is_chatgpt_input_ready(root, date):
        raise DriveInboxError(
            f"prediction_input_{date}.json が完成していないためDriveへ出しません"
        )
    path = chatgpt_input_path(root, date)
    parse_allowed_daily_name(path.name)
    payload = load_json(path)
    return upsert_completed_json(client, path.name, payload)


def sync_completed_final(
    root,
    date: str,
    *,
    store: DriveInboxStore | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    client = resolve_store(store)
    if client is None:
        return None
    path = chatgpt_final_path(root, date)
    data = payload if payload is not None else (load_json(path) if path.is_file() else None)
    try:
        completed = require_chatgpt_final(data)
    except SchemaError as exc:
        raise DriveInboxError(str(exc)) from exc
    parse_allowed_daily_name(path.name)
    return upsert_completed_json(client, path.name, completed)


def pull_ready_input(
    root,
    date: str,
    *,
    store: DriveInboxStore | None = None,
) -> dict[str, Any] | None:
    client = resolve_store(store)
    if client is None:
        return None
    name = chatgpt_input_path(root, date).name
    parse_allowed_daily_name(name)
    folder_id = client.find_inbox_folder_id()
    existing = client.find_file(folder_id, name)
    if existing is None:
        return None
    loaded = json.loads(client.download(str(existing["id"])).decode("utf-8"))
    if not is_input_ready_payload(loaded):
        raise DriveInboxError(
            f"Drive上の {name} は未完成のため取り込みません。.tmp.json も使いません。"
        )
    save_json(chatgpt_input_path(root, date), loaded)
    return loaded


def pull_completed_final(
    root,
    date: str,
    *,
    store: DriveInboxStore | None = None,
) -> dict[str, Any] | None:
    client = resolve_store(store)
    if client is None:
        return None
    name = chatgpt_final_path(root, date).name
    parse_allowed_daily_name(name)
    folder_id = client.find_inbox_folder_id()
    existing = client.find_file(folder_id, name)
    if existing is None:
        return None
    loaded = json.loads(client.download(str(existing["id"])).decode("utf-8"))
    completed = require_chatgpt_final(loaded)
    save_json(chatgpt_final_path(root, date), completed)
    return completed


def format_sync_note(result: dict[str, Any] | None, *, skipped_reason: str | None = None) -> str:
    if result:
        return (
            f"Drive同期: {result['path']} / {result['name']}（{result['action']}）"
        )
    if skipped_reason:
        return skipped_reason
    return "Drive同期は認証情報がないためスキップしました。"
