#!/usr/bin/env python3
"""競輪の内部state.jsonを、既存のGoogle Drive JSONファイルへID指定で読み書きする。

新規作成はしない。KEIRIN_STATE_DRIVE_FILE_ID に対する files.update
（uploadType=media の PATCH）だけを使う。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Protocol

FILE_ID_ENV = "KEIRIN_STATE_DRIVE_FILE_ID"
SA_JSON_ENV = "GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON"
ACCESS_TOKEN_ENV = "GOOGLE_DRIVE_ACCESS_TOKEN"

JSON_MIME = "application/json"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"

EMPTY_STATE = {"version": 1, "days": []}

EXPECTED_STATE_FILE_NAME = "keirin_learning_state.json"
ALLOWED_STATE_MIME_TYPES = {"application/json", "text/plain"}


class DriveStateError(RuntimeError):
    pass


class DriveStateStore(Protocol):
    def get_metadata(self, file_id: str) -> dict[str, Any]:
        """既存ファイルの名前・MIMEタイプ等を返す。無いIDは作らず失敗する。"""

    def download(self, file_id: str) -> bytes:
        """既存ファイルの中身を返す。無いIDは作らず失敗する。"""

    def upload_replace(self, file_id: str, content: bytes) -> Any:
        """既存ファイルを上書きする。files.create は使わない。"""


def require_state_file_id(file_id: str | None = None) -> str:
    value = (file_id if file_id is not None else os.environ.get(FILE_ID_ENV, "")).strip()
    if not value:
        raise DriveStateError(
            f"{FILE_ID_ENV} が未設定です。既存DriveファイルのIDが必要です。新規作成はしません。"
        )
    return value


def _http_request(
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


def _parse_json(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def _service_account_access_token(sa_data: dict[str, Any]) -> str:
    try:
        import jwt  # type: ignore
    except ImportError as exc:
        raise DriveStateError("service account 利用には PyJWT が必要です。") from exc

    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": sa_data["client_email"],
        "scope": DRIVE_SCOPE,
        "aud": TOKEN_ENDPOINT,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(payload, sa_data["private_key"], algorithm="RS256")
    body = urllib.parse.urlencode(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        }
    ).encode("utf-8")
    status, raw = _http_request(
        TOKEN_ENDPOINT,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    if status != 200:
        raise DriveStateError(
            f"service account 認証失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
        )
    return str(_parse_json(raw)["access_token"])


def get_access_token(access_token: str | None = None) -> str:
    if access_token and access_token.strip():
        return access_token.strip()
    env_token = os.environ.get(ACCESS_TOKEN_ENV, "").strip()
    if env_token:
        return env_token
    sa_env = os.environ.get(SA_JSON_ENV, "").strip()
    if sa_env:
        try:
            sa_data = json.loads(sa_env)
        except json.JSONDecodeError as exc:
            raise DriveStateError(f"{SA_JSON_ENV} がJSONではありません") from exc
        if not isinstance(sa_data, dict):
            raise DriveStateError(f"{SA_JSON_ENV} はオブジェクトである必要があります")
        return _service_account_access_token(sa_data)
    raise DriveStateError(
        f"Google Drive 認証情報がありません。{SA_JSON_ENV} または {ACCESS_TOKEN_ENV} を設定してください。"
    )


class MemoryDriveStateStore:
    """テスト用。あらかじめ登録した既存IDだけを上書きする。新規IDは作らない。

    metadata を指定しない登録ファイルは、想定どおりの学習専用state.json
    （name=EXPECTED_STATE_FILE_NAME, mimeType=application/json）として扱う。
    誤ファイル判定のテストでは metadata を明示的に上書きする。
    """

    def __init__(
        self,
        files: dict[str, bytes] | None = None,
        metadata: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.files: dict[str, bytes] = dict(files or {})
        self.metadata: dict[str, dict[str, str]] = dict(metadata or {})
        self.download_calls: list[str] = []
        self.upload_calls: list[str] = []
        self.metadata_calls: list[str] = []

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        file_id = require_state_file_id(file_id)
        self.metadata_calls.append(file_id)
        if file_id not in self.files:
            raise DriveStateError(
                f"Drive file ID が存在しません。新規作成しません: {file_id}"
            )
        default = {"name": EXPECTED_STATE_FILE_NAME, "mimeType": JSON_MIME}
        return dict(self.metadata.get(file_id, default))

    def download(self, file_id: str) -> bytes:
        file_id = require_state_file_id(file_id)
        self.download_calls.append(file_id)
        if file_id not in self.files:
            raise DriveStateError(
                f"Drive file ID が存在しません。新規作成しません: {file_id}"
            )
        return self.files[file_id]

    def upload_replace(self, file_id: str, content: bytes) -> dict[str, Any]:
        file_id = require_state_file_id(file_id)
        self.upload_calls.append(file_id)
        if file_id not in self.files:
            raise DriveStateError(
                f"Drive file ID が存在しません。files.create はしません: {file_id}"
            )
        if not isinstance(content, (bytes, bytearray)):
            raise DriveStateError("Driveへ送る内容はbytesである必要があります")
        self.files[file_id] = bytes(content)
        return {"id": file_id}


class GoogleDriveStateStore:
    """既存ファイルIDだけを GET alt=media / PATCH uploadType=media する。"""

    def __init__(self, access_token: str | None = None) -> None:
        self._access_token = access_token

    def _token(self) -> str:
        return get_access_token(self._access_token)

    def get_metadata(self, file_id: str) -> dict[str, Any]:
        file_id = require_state_file_id(file_id)
        quoted = urllib.parse.quote(file_id, safe="")
        fields = urllib.parse.quote("name,mimeType", safe="")
        url = f"{DRIVE_API_BASE}/{quoted}?fields={fields}&supportsAllDrives=true"
        status, raw = _http_request(
            url, headers={"Authorization": f"Bearer {self._token()}"}
        )
        if status != 200:
            raise DriveStateError(
                f"Drive メタデータ取得失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        try:
            return _parse_json(raw)
        except json.JSONDecodeError as exc:
            raise DriveStateError("Drive メタデータ応答がJSONではありません") from exc

    def download(self, file_id: str) -> bytes:
        file_id = require_state_file_id(file_id)
        quoted = urllib.parse.quote(file_id, safe="")
        url = f"{DRIVE_API_BASE}/{quoted}?alt=media&supportsAllDrives=true"
        status, raw = _http_request(
            url, headers={"Authorization": f"Bearer {self._token()}"}
        )
        if status != 200:
            raise DriveStateError(
                f"Drive download 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        return raw

    def upload_replace(self, file_id: str, content: bytes) -> dict[str, Any]:
        file_id = require_state_file_id(file_id)
        if not isinstance(content, (bytes, bytearray)):
            raise DriveStateError("Driveへ送る内容はbytesである必要があります")
        quoted = urllib.parse.quote(file_id, safe="")
        query = urllib.parse.urlencode({"uploadType": "media", "supportsAllDrives": "true"})
        url = f"{DRIVE_UPLOAD_BASE}/{quoted}?{query}"
        status, raw = _http_request(
            url,
            method="PATCH",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": JSON_MIME,
                "Content-Length": str(len(content)),
            },
            body=bytes(content),
        )
        if status not in (200, 201):
            raise DriveStateError(
                f"Drive upload 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}"
            )
        if not raw:
            return {"id": file_id}
        try:
            parsed = _parse_json(raw)
        except json.JSONDecodeError as exc:
            raise DriveStateError("Drive upload 応答がJSONではありません") from exc
        return parsed


def default_drive_store() -> DriveStateStore:
    return GoogleDriveStateStore()


def verify_state_file_metadata(store: "DriveStateStore", file_id: str) -> dict[str, Any]:
    """GET/PATCH前に必ず呼ぶ。ファイル名・MIMEタイプが想定外なら中断する。

    KEIRIN_STATE_DRIVE_FILE_ID の設定ミスで競輪スプレッドシートや別ファイルを
    誤って上書きしないための事前チェック。中身の検証はここでは行わない。
    """
    file_id = require_state_file_id(file_id)
    metadata = store.get_metadata(file_id)
    name = metadata.get("name")
    mime = metadata.get("mimeType")
    if name != EXPECTED_STATE_FILE_NAME:
        raise DriveStateError(
            "Drive上のファイル名が想定と異なるため中断しました"
            f"（期待: {EXPECTED_STATE_FILE_NAME} / 実際: {name}）。"
            "KEIRIN_STATE_DRIVE_FILE_ID の設定を確認してください。"
        )
    if mime not in ALLOWED_STATE_MIME_TYPES:
        raise DriveStateError(
            "Drive上のMIMEタイプが許可されていないため中断しました"
            f"（実際: {mime} / 許可: {sorted(ALLOWED_STATE_MIME_TYPES)}）。"
            "KEIRIN_STATE_DRIVE_FILE_ID の設定を確認してください。"
        )
    return metadata


def guard_against_destructive_overwrite(
    local_data: dict[str, Any], remote_data: dict[str, Any]
) -> None:
    """空のローカルstateで、既存Drive上の学習データを空に上書きしない安全策。"""
    if not local_data.get("days") and remote_data.get("days"):
        raise DriveStateError(
            "ローカルstateにdaysがありませんが、Drive上には既存の学習データがあります。"
            "空内容での上書きは危険なため中止しました。"
        )


def encode_state_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def parse_remote_state_bytes(raw: bytes) -> dict[str, Any]:
    if raw is None:
        raise DriveStateError("Driveからstateを取得できませんでした")
    if not raw.strip():
        return {"version": 1, "days": []}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DriveStateError(
            "Drive上のstate.jsonが壊れているため続行しません。Driveは上書きしません。"
        ) from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("days"), list):
        raise DriveStateError(
            "Drive上のstate.jsonが正規形式ではないため続行しません。Driveは上書きしません。"
        )
    return data
