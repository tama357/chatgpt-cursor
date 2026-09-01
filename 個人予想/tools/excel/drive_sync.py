"""Google Drive へ個人予想 Excel をアップロードし、成功を検証する。"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3/files"


@dataclass
class FileSyncResult:
    key: str
    local_name: str
    local_path: Path
    drive_file_id: str | None
    status: str
    message: str
    local_size: int = 0
    local_md5: str = ""
    drive_size: int | None = None
    drive_md5: str | None = None
    drive_modified_time: str | None = None
    drive_view_url: str | None = None


@dataclass
class DriveSyncReport:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[FileSyncResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.succeeded > 0

    def format_report(self) -> str:
        lines = ["## Google Drive 同期"]
        if self.succeeded == 0 and self.failed == 0:
            lines.append("⚠ Drive同期は実行されませんでした（認証情報未設定など）。")
            return "\n".join(lines)
        for item in self.results:
            if item.status == "success":
                lines.append(
                    f"✅ {item.local_name} → Drive更新成功 "
                    f"(ID: {item.drive_file_id}, size={item.drive_size}, md5一致)"
                )
                if item.drive_view_url:
                    lines.append(f"   URL: {item.drive_view_url}")
            elif item.status == "skipped":
                lines.append(f"ℹ スキップ: {item.local_name} — {item.message}")
            else:
                lines.append(f"❌ 失敗: {item.local_name} — {item.message}")
        if self.ok:
            lines.append(
                f"\n**Drive同期完了**: {self.succeeded}/{self.attempted} ファイルを検証済みアップロードしました。"
            )
        else:
            lines.append(
                f"\n**Drive同期未完了**: 成功 {self.succeeded} / 失敗 {self.failed} / スキップ {self.skipped}"
            )
            lines.append("ローカルExcelのみ更新されています。Drive反映は成功確認後に報告してください。")
        return "\n".join(lines)


class DriveAuthError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_drive_config(base_dir: Path) -> dict[str, Any]:
    return _load_json(base_dir / "config" / "drive_excel.json")


def save_drive_config(base_dir: Path, config: dict[str, Any]) -> None:
    _save_json(base_dir / "config" / "drive_excel.json", config)


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


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


def _get_access_token(base_dir: Path) -> str:
    env_token = os.environ.get("GOOGLE_DRIVE_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    token_path = base_dir / ".drive" / "token.json"
    if token_path.exists():
        token_data = _load_json(token_path)
        access = token_data.get("access_token")
        if access and token_data.get("expires_at", 0) > datetime.now(timezone.utc).timestamp() + 30:
            return str(access)
        refresh = token_data.get("refresh_token")
        client_id = token_data.get("client_id") or os.environ.get("GOOGLE_DRIVE_CLIENT_ID")
        client_secret = token_data.get("client_secret") or os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET")
        if refresh and client_id and client_secret:
            body = urllib.parse.urlencode(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
            ).encode("utf-8")
            status, raw = _http_request(
                TOKEN_ENDPOINT,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body,
            )
            if status != 200:
                raise DriveAuthError(f"トークン更新失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}")
            refreshed = _parse_json(raw)
            token_data["access_token"] = refreshed["access_token"]
            token_data["expires_at"] = datetime.now(timezone.utc).timestamp() + int(
                refreshed.get("expires_in", 3600)
            )
            _save_json(token_path, token_data)
            return str(refreshed["access_token"])

    sa_env = os.environ.get("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    sa_path = base_dir / ".drive" / "service_account.json"
    sa_data: dict[str, Any] | None = None
    if sa_env:
        sa_data = json.loads(sa_env)
    elif sa_path.exists():
        sa_data = _load_json(sa_path)
    if sa_data:
        return _service_account_access_token(sa_data)

    raise DriveAuthError(
        "Google Drive 認証情報がありません。"
        " `個人予想/.drive/token.json` または `個人予想/.drive/service_account.json` を設定してください。"
    )


def _service_account_access_token(sa_data: dict[str, Any]) -> str:
    try:
        import jwt  # type: ignore
    except ImportError as exc:
        raise DriveAuthError("service account 利用には PyJWT が必要です。") from exc

    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": sa_data["client_email"],
        "scope": "https://www.googleapis.com/auth/drive.file",
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
        raise DriveAuthError(f"service account 認証失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}")
    return str(_parse_json(raw)["access_token"])


def _drive_get_metadata(access_token: str, file_id: str) -> dict[str, Any]:
    fields = urllib.parse.quote("id,name,size,md5Checksum,modifiedTime,webViewLink,mimeType,trashed")
    url = f"{DRIVE_API_BASE}/{file_id}?fields={fields}&supportsAllDrives=true"
    status, raw = _http_request(url, headers={"Authorization": f"Bearer {access_token}"})
    if status != 200:
        raise RuntimeError(f"Drive metadata 取得失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}")
    return _parse_json(raw)


def _drive_upload_replace(access_token: str, file_id: str, local_path: Path) -> dict[str, Any]:
    content = local_path.read_bytes()
    query = urllib.parse.urlencode({"uploadType": "media", "supportsAllDrives": "true"})
    url = f"{DRIVE_UPLOAD_BASE}/{file_id}?{query}"
    status, raw = _http_request(
        url,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": XLSX_MIME,
            "Content-Length": str(len(content)),
        },
        body=content,
    )
    if status not in (200, 201):
        raise RuntimeError(f"Drive upload 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}")
    return _parse_json(raw)


def _drive_create(access_token: str, folder_id: str, title: str, local_path: Path) -> dict[str, Any]:
    content = local_path.read_bytes()
    metadata = json.dumps({"name": title, "parents": [folder_id], "mimeType": XLSX_MIME}).encode("utf-8")
    boundary = "cursor_personal_predict_boundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8")
        + metadata
        + f"\r\n--{boundary}\r\nContent-Type: {XLSX_MIME}\r\n\r\n".encode("utf-8")
        + content
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    query = urllib.parse.urlencode({"uploadType": "multipart", "supportsAllDrives": "true"})
    url = f"{DRIVE_UPLOAD_BASE}?{query}"
    status, raw = _http_request(
        url,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        body=body,
    )
    if status not in (200, 201):
        raise RuntimeError(f"Drive create 失敗 HTTP {status}: {raw.decode('utf-8', errors='replace')}")
    return _parse_json(raw)


def _is_forbidden(title: str, config: dict[str, Any]) -> bool:
    prefixes = config.get("forbidden_title_prefixes", [])
    return any(title.startswith(prefix) for prefix in prefixes)


def sync_excel_files(
    base_dir: Path,
    *,
    keys: list[str] | None = None,
    access_token: str | None = None,
) -> DriveSyncReport:
    config = load_drive_config(base_dir)
    excel_dir = base_dir / "excel"
    report = DriveSyncReport()
    token = access_token or _get_access_token(base_dir)
    target_keys = keys or list(config.get("files", {}).keys())

    for key in target_keys:
        spec = config.get("files", {}).get(key)
        if not spec:
            continue
        local_name = spec["local_name"]
        local_path = excel_dir / local_name
        result = FileSyncResult(
            key=key,
            local_name=local_name,
            local_path=local_path,
            drive_file_id=spec.get("drive_file_id"),
            status="pending",
            message="",
        )
        report.attempted += 1

        if _is_forbidden(local_name, config):
            result.status = "skipped"
            result.message = "個人競輪など対象外ファイルのため同期しません"
            report.skipped += 1
            report.results.append(result)
            continue
        if not local_path.exists():
            result.status = "failed"
            result.message = f"ローカルファイルがありません: {local_path}"
            report.failed += 1
            report.results.append(result)
            continue

        content = local_path.read_bytes()
        result.local_size = len(content)
        result.local_md5 = md5_hex(content)

        try:
            file_id = spec.get("drive_file_id")
            if file_id:
                uploaded = _drive_upload_replace(token, str(file_id), local_path)
            else:
                uploaded = _drive_create(
                    token,
                    str(config["folder_id"]),
                    str(spec.get("drive_title", local_name)),
                    local_path,
                )
                file_id = uploaded.get("id")
                spec["drive_file_id"] = file_id
                config["files"][key] = spec
                save_drive_config(base_dir, config)

            meta = _drive_get_metadata(token, str(file_id))
            if meta.get("trashed"):
                raise RuntimeError("アップロード後に Drive 上でファイルがゴミ箱状態です")
            drive_md5 = meta.get("md5Checksum")
            drive_size = int(meta.get("size", 0))
            result.drive_file_id = str(file_id)
            result.drive_md5 = drive_md5
            result.drive_size = drive_size
            result.drive_modified_time = meta.get("modifiedTime")
            result.drive_view_url = meta.get("webViewLink")

            if drive_md5 != result.local_md5 or drive_size != result.local_size:
                raise RuntimeError(
                    f"検証失敗: local(md5={result.local_md5}, size={result.local_size}) "
                    f"!= drive(md5={drive_md5}, size={drive_size})"
                )

            result.status = "success"
            result.message = "Driveへ反映し、md5/size を確認しました"
            report.succeeded += 1
        except Exception as exc:  # noqa: BLE001 - report per file
            result.status = "failed"
            result.message = str(exc)
            report.failed += 1
        report.results.append(result)

    return report


def register_mcp_upload_result(
    base_dir: Path,
    key: str,
    *,
    drive_file_id: str,
    local_path: Path,
    drive_md5: str,
    drive_size: int,
    drive_view_url: str | None = None,
) -> FileSyncResult:
    """Cursor MCP アップロード後に config 更新と検証結果を記録。"""
    content = local_path.read_bytes()
    local_md5 = md5_hex(content)
    local_size = len(content)
    if local_md5 != drive_md5 or local_size != drive_size:
        raise RuntimeError(
            f"MCP upload verify failed for {key}: local(md5={local_md5},size={local_size}) "
            f"drive(md5={drive_md5},size={drive_size})"
        )
    config = load_drive_config(base_dir)
    spec = config["files"][key]
    spec["drive_file_id"] = drive_file_id
    config["files"][key] = spec
    save_drive_config(base_dir, config)
    return FileSyncResult(
        key=key,
        local_name=spec["local_name"],
        local_path=local_path,
        drive_file_id=drive_file_id,
        status="success",
        message="MCP経由でDrive反映し、md5/size を確認しました",
        local_size=local_size,
        local_md5=local_md5,
        drive_size=drive_size,
        drive_md5=drive_md5,
        drive_view_url=drive_view_url,
    )


def encode_file_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
