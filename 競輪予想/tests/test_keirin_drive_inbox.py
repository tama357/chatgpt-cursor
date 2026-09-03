import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


import keirin_drive_inbox as inbox

flow = _load("keirin_cursor_flow", TOOLS / "keirin_cursor_flow.py")
chatgpt_io = _load("keirin_chatgpt_io", TOOLS / "keirin_chatgpt_io.py")
sheets = _load("keirin_sheets", TOOLS / "keirin_sheets.py")


class KeirinDriveInboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data" / "inbox").mkdir(parents=True)
        (self.root / "current_rules.json").write_text(
            (ROOT / "current_rules.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.store = inbox.MemoryDriveInboxStore()

    def tearDown(self):
        self.tmp.cleanup()

    def _complete_input(self, date: str = "2099-01-01") -> dict:
        return chatgpt_io.build_chatgpt_input(
            date=date,
            candidates=[
                {
                    "venue": f"テスト競輪場{index}",
                    "race_number": 7 + index,
                    "deadline": "18:20",
                    "riders": [{"number": n, "name": f"選手{n}"} for n in range(1, 6)],
                    "prediction_score": 80 - index,
                }
                for index in range(3)
            ],
        )

    def _copy_example(self, name: str) -> Path:
        dest = self.root / name
        dest.write_text((ROOT / "examples" / name).read_text(encoding="utf-8"), encoding="utf-8")
        return dest

    def test_tmp_and_learning_names_are_rejected(self):
        with self.assertRaises(inbox.DriveInboxError):
            inbox.parse_allowed_daily_name("prediction_input_2099-01-01.tmp.json")
        with self.assertRaises(inbox.DriveInboxError):
            inbox.parse_allowed_daily_name("keirin_learning_state.json")
        with self.assertRaises(inbox.DriveInboxError):
            inbox.parse_allowed_daily_name("2099-01-01.predictions.json")
        with self.assertRaises(inbox.DriveInboxError):
            inbox.parse_allowed_daily_name("2099-01-01.learning.json")

    def test_incomplete_input_is_not_uploaded(self):
        payload = chatgpt_io.build_chatgpt_input(date="2099-01-01", candidates=[])
        chatgpt_io.write_chatgpt_input(self.root, payload)
        with self.assertRaises(inbox.DriveInboxError):
            inbox.sync_ready_input(self.root, "2099-01-01", store=self.store)
        self.assertEqual(self.store.creates, [])
        self.assertEqual(self.store.uploads, [])

    def test_ready_input_is_uploaded_and_reread(self):
        chatgpt_io.write_chatgpt_input(self.root, self._complete_input())
        result = inbox.sync_ready_input(self.root, "2099-01-01", store=self.store)
        self.assertEqual(result["name"], "prediction_input_2099-01-01.json")
        self.assertEqual(result["action"], "created")
        self.assertIn("競輪学習 / inbox", result["path"])
        self.assertEqual(self.store.creates, ["prediction_input_2099-01-01.json"])
        raw = self.store.download(result["file_id"])
        loaded = json.loads(raw.decode("utf-8"))
        self.assertEqual(loaded["status"], "ready")
        self.assertTrue(loaded["data_complete"])

    def test_prepare_today_syncs_ready_input_only(self):
        races = self._copy_example("races_collect.example.json")
        text = flow.prepare_today(
            self.root,
            "2099-01-01",
            races_file=races,
            sync_drive=True,
            drive_store=self.store,
        )
        self.assertIn("Drive同期：成功", text)
        self.assertIn("input JSON作成：成功", text)
        self.assertNotIn("Drive同期：失敗", text)
        self.assertIn("prediction_input_2099-01-01.json", text)
        self.assertEqual(self.store.creates, ["prediction_input_2099-01-01.json"])
        self.assertFalse(any(name.endswith(".tmp.json") for name in self.store.creates))

        broken_store = inbox.MemoryDriveInboxStore()
        empty_races = self.root / "empty_races.json"
        empty_races.write_text("[]\n", encoding="utf-8")
        empty = flow.prepare_today(
            self.root,
            "2099-01-02",
            races_file=empty_races,
            sync_drive=True,
            drive_store=broken_store,
        )
        self.assertIn("正式ファイルは未作成", empty)
        self.assertIn("Drive同期：未使用", empty)
        self.assertNotIn("Drive同期：成功", empty)
        self.assertEqual(broken_store.creates, [])

    def test_drive_quota_failure_is_not_reported_as_success(self):
        races = self._copy_example("races_collect.example.json")
        with mock.patch.object(
            flow,
            "sync_ready_input",
            side_effect=inbox.DriveInboxError("storageQuotaExceeded"),
        ):
            text = flow.prepare_today(
                self.root,
                "2099-01-01",
                races_file=races,
                sync_drive=True,
                drive_store=self.store,
            )
        self.assertIn("input JSON作成：成功", text)
        self.assertIn("Drive同期：失敗", text)
        self.assertIn("storageQuotaExceeded", text)
        self.assertNotIn("Drive同期：成功", text)
        self.assertTrue(chatgpt_io.chatgpt_input_path(self.root, "2099-01-01").is_file())

    def test_incomplete_final_is_not_uploaded(self):
        payload = {"date": "2099-01-01", "predictions": []}
        with self.assertRaises(inbox.DriveInboxError):
            inbox.upsert_completed_json(self.store, "prediction_final_2099-01-01.json", payload)
        self.assertEqual(self.store.creates, [])

    def test_ingest_syncs_completed_final_after_validation(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = self._copy_example("chatgpt_final.example.json")
        text = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            write_sheets=False,
            sync_drive=True,
            drive_store=self.store,
        )
        self.assertIn("Drive同期", text)
        self.assertIn("prediction_final_2099-01-01.json", " ".join(self.store.creates))
        self.assertNotIn("2099-01-01.predictions.json", self.store.creates)
        self.assertNotIn("keirin_learning_state.json", self.store.creates)

    def test_validation_error_does_not_sync_final(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = json.loads((ROOT / "examples" / "chatgpt_final.example.json").read_text(encoding="utf-8"))
        final["predictions"][0]["ticket_count"] = 99
        path = self.root / "bad_final.json"
        path.write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(Exception) as ctx:
            flow.ingest_final(
                self.root,
                "2099-01-01",
                final_file=path,
                write_sheets=False,
                sync_drive=True,
                drive_store=self.store,
            )
        self.assertIn("補正しません", str(ctx.exception))
        self.assertEqual(self.store.creates, [])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["predictions"][0]["ticket_count"], 99)

    def test_pull_completed_final_from_drive(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = json.loads((ROOT / "examples" / "chatgpt_final.example.json").read_text(encoding="utf-8"))
        inbox.upsert_completed_json(self.store, "prediction_final_2099-01-01.json", final)
        self.assertFalse(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").exists())
        text = flow.ingest_final(
            self.root,
            "2099-01-01",
            write_sheets=False,
            sync_drive=True,
            drive_store=self.store,
        )
        self.assertIn("改変していません", text)
        self.assertTrue(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").is_file())
        local = json.loads(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").read_text(encoding="utf-8"))
        self.assertEqual(local["predictions"][0]["tickets"][0]["pick"], "1-2-345")

    def test_submission_state_is_synced_to_drive_not_sheets(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        store = sheets.MemorySheetStore()
        flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=self._copy_example("chatgpt_final.example.json"),
            sheet_store=store,
            write_sheets=True,
            sync_drive=True,
            drive_store=self.store,
        )
        state_files = list((self.root / "data" / "state").glob("submission_state_*.json"))
        self.assertEqual(len(state_files), 1)
        self.assertIn("submission_state_2099-01-01.json", self.store.creates)
        self.assertNotIn("keirin_learning_state.json", self.store.creates)

    def test_poll_without_final_is_not_error(self):
        text = flow.poll_ingest_final(
            self.root,
            "2099-01-01",
            write_sheets=False,
            drive_store=self.store,
        )
        self.assertIn("まだありません", text)
        self.assertIn("エラーではありません", text)

    def test_poll_ingests_drive_final_once(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = json.loads((ROOT / "examples" / "chatgpt_final.example.json").read_text(encoding="utf-8"))
        inbox.upsert_completed_json(self.store, "prediction_final_2099-01-01.json", final)
        store = sheets.MemorySheetStore()
        sent: list[int] = []

        def send_fn(_data):
            sent.append(1)
            return {"message_id": "1"}

        with mock.patch.dict(os.environ, {"CHATWORK_ENABLED": "true"}):
            first = flow.poll_ingest_final(
                self.root,
                "2099-01-01",
                sheet_store=store,
                write_sheets=True,
                confirm_send=True,
                send_fn=send_fn,
                drive_store=self.store,
            )
        self.assertIn("再読で完全一致", first)
        self.assertEqual(store.write_entry_calls, 1)
        self.assertEqual(sent, [1])
        with mock.patch.dict(os.environ, {"CHATWORK_ENABLED": "true"}):
            second = flow.poll_ingest_final(
                self.root,
                "2099-01-01",
                sheet_store=store,
                write_sheets=True,
                confirm_send=True,
                send_fn=send_fn,
                drive_store=self.store,
            )
        self.assertIn("すでに処理済み", second)
        self.assertEqual(store.write_entry_calls, 1)
        self.assertEqual(sent, [1])

    def test_matching_sheet_is_not_rewritten(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = self._copy_example("chatgpt_final.example.json")
        store = sheets.MemorySheetStore()
        flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            sync_drive=False,
        )
        self.assertEqual(store.write_entry_calls, 1)
        text = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            sync_drive=False,
        )
        self.assertTrue(
            "再書き込みしません" in text or "すでに処理済み" in text,
            text,
        )
        self.assertEqual(store.write_entry_calls, 1)


if __name__ == "__main__":
    unittest.main()
