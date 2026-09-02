"""Drive inbox のフォルダ自動作成・同名更新・再読。本番Driveには書かない。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_fixtures import PRODUCTION_ROOT, ProductionDataGuardMixin  # noqa: E402

from excel import drive_inbox  # noqa: E402
from excel.drive_sync import FOLDER_MIME, JSON_MIME  # noqa: E402
from common.daily_json import empty_day_payload, save_daily_json  # noqa: E402
from common.constants import DAY_STATUS_NO_MEETING  # noqa: E402


class FakeDrive:
    def __init__(self, chatgpt_id: str):
        self.chatgpt_id = chatgpt_id
        self.folders: dict[str, dict[str, str]] = {chatgpt_id: {}}
        self.files: dict[str, dict[str, dict]] = {}
        self.contents: dict[str, bytes] = {}
        self.next_id = 1
        self.create_file_calls = 0
        self.replace_calls = 0
        self.create_folder_calls = 0

    def _new_id(self, prefix: str) -> str:
        self.next_id += 1
        return f"{prefix}{self.next_id}"

    def find_all(self, _token: str, parent_id: str, name: str) -> list[dict]:
        out: list[dict] = []
        folder_id = self.folders.get(parent_id, {}).get(name)
        if folder_id:
            out.append({"id": folder_id, "name": name, "mimeType": FOLDER_MIME})
        file_item = self.files.get(parent_id, {}).get(name)
        if file_item:
            out.append(file_item)
        return out

    def create_folder(self, _token: str, parent_id: str, name: str) -> dict:
        self.create_folder_calls += 1
        folder_id = self._new_id("fld")
        self.folders.setdefault(parent_id, {})[name] = folder_id
        self.folders.setdefault(folder_id, {})
        self.files.setdefault(folder_id, {})
        return {"id": folder_id}

    def create_file(self, _token: str, folder_id: str, title: str, local_path: Path, **_kwargs) -> dict:
        self.create_file_calls += 1
        file_id = self._new_id("fil")
        raw = local_path.read_bytes()
        self.files.setdefault(folder_id, {})[title] = {
            "id": file_id,
            "name": title,
            "mimeType": JSON_MIME,
        }
        self.contents[file_id] = raw
        return {"id": file_id}

    def upload_replace(self, _token: str, file_id: str, local_path: Path, **_kwargs) -> dict:
        self.replace_calls += 1
        self.contents[file_id] = local_path.read_bytes()
        return {"id": file_id}

    def download(self, _token: str, file_id: str) -> bytes:
        return self.contents[file_id]


class DriveInboxTest(ProductionDataGuardMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="personal-inbox-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "config").mkdir()
        shutil.copy(
            PRODUCTION_ROOT / "config" / "drive_excel.json",
            self.tmp / "config" / "drive_excel.json",
        )
        cfg = json.loads((self.tmp / "config" / "drive_excel.json").read_text(encoding="utf-8"))
        self.chatgpt_id = cfg["folder_id"]
        self.fake = FakeDrive(self.chatgpt_id)

    def _patches(self):
        return (
            patch.object(drive_inbox, "_get_access_token", return_value="token"),
            patch.object(drive_inbox, "_drive_find_all_in_folder", side_effect=self.fake.find_all),
            patch.object(drive_inbox, "_drive_create_folder", side_effect=self.fake.create_folder),
            patch.object(drive_inbox, "_drive_create", side_effect=self.fake.create_file),
            patch.object(drive_inbox, "_drive_upload_replace", side_effect=self.fake.upload_replace),
            patch.object(drive_inbox, "_drive_download", side_effect=self.fake.download),
        )

    def test_upsert_creates_folders_and_updates_same_name(self):
        payload = empty_day_payload(
            date="2026-09-03", sport="jra", day_status=DAY_STATUS_NO_MEETING
        )
        local = self.tmp / "data" / "inbox" / "jra" / "2026-09-03.predictions.json"
        save_daily_json(local, payload)
        with self._patches()[0], self._patches()[1], self._patches()[2], self._patches()[3], self._patches()[4], self._patches()[5]:
            first = drive_inbox.upsert_inbox_file(self.tmp, "jra", local)
            self.assertEqual(first.status, "success")
            self.assertEqual(self.fake.create_file_calls, 1)
            folders_before = self.fake.create_folder_calls
            payload["note"] = "updated"
            save_daily_json(local, payload)
            second = drive_inbox.upsert_inbox_file(self.tmp, "jra", local)
        self.assertEqual(second.status, "success")
        self.assertEqual(second.drive_file_id, first.drive_file_id)
        self.assertEqual(self.fake.create_file_calls, 1)
        self.assertEqual(self.fake.replace_calls, 1)
        self.assertEqual(self.fake.create_folder_calls, folders_before)
        loaded = json.loads(self.fake.contents[second.drive_file_id].decode("utf-8"))
        self.assertEqual(loaded["note"], "updated")
        self.assertEqual(loaded["date"], "2026-09-03")

    def test_pull_does_not_create_missing_folders(self):
        dest = self.tmp / "data" / "inbox" / "nar" / "2026-09-03.predictions.json"
        with self._patches()[0], self._patches()[1], self._patches()[2], self._patches()[3], self._patches()[4], self._patches()[5]:
            item = drive_inbox.pull_inbox_file(
                self.tmp, "nar", "2026-09-03.predictions.json", dest
            )
        self.assertEqual(item.status, "failed")
        self.assertIn("フォルダ", item.message)
        self.assertEqual(self.fake.create_folder_calls, 0)
        self.assertEqual(self.fake.create_file_calls, 0)


if __name__ == "__main__":
    unittest.main()
