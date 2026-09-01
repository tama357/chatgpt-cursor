import hashlib
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from excel import drive_sync  # noqa: E402


class DriveSyncTest(unittest.TestCase):
    def setUp(self):
        self.base_dir = ROOT
        self.sample = self.base_dir / "excel" / "競艇_予想記入シート_2026年9月.xlsx"
        self.local_md5 = hashlib.md5(self.sample.read_bytes()).hexdigest()
        self.local_size = self.sample.stat().st_size

    @patch.object(drive_sync, "_get_access_token", return_value="token")
    @patch.object(drive_sync, "_drive_upload_replace")
    @patch.object(drive_sync, "_drive_get_metadata")
    def test_sync_existing_file_success(self, mock_meta, mock_upload, _mock_token):
        mock_upload.return_value = {"id": "10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5"}
        mock_meta.return_value = {
            "id": "10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5",
            "md5Checksum": self.local_md5,
            "size": str(self.local_size),
            "modifiedTime": "2026-09-01T12:00:00.000Z",
            "webViewLink": "https://drive.google.com/file/d/10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5/view",
            "trashed": False,
        }
        report = drive_sync.sync_excel_files(self.base_dir, keys=["kyotei_entry"])
        self.assertTrue(report.ok)
        self.assertEqual(report.succeeded, 1)
        self.assertEqual(report.results[0].status, "success")

    @patch.object(drive_sync, "_get_access_token", return_value="token")
    @patch.object(drive_sync, "_drive_upload_replace")
    @patch.object(drive_sync, "_drive_get_metadata")
    def test_sync_verify_failure(self, mock_meta, mock_upload, _mock_token):
        mock_upload.return_value = {"id": "10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5"}
        mock_meta.return_value = {
            "id": "10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5",
            "md5Checksum": "deadbeef",
            "size": "1",
            "trashed": False,
        }
        report = drive_sync.sync_excel_files(self.base_dir, keys=["kyotei_entry"])
        self.assertFalse(report.ok)
        self.assertEqual(report.failed, 1)


if __name__ == "__main__":
    unittest.main()
