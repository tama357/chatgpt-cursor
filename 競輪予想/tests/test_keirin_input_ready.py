import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


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


workflow = _load("keirin_workflow", TOOLS / "keirin_workflow.py")
flow = _load("keirin_cursor_flow", TOOLS / "keirin_cursor_flow.py")
chatgpt_io = _load("keirin_chatgpt_io", TOOLS / "keirin_chatgpt_io.py")
sheets = _load("keirin_sheets", TOOLS / "keirin_sheets.py")
submission = _load("keirin_submission_state", TOOLS / "keirin_submission_state.py")


class KeirinInputReadyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data" / "inbox").mkdir(parents=True)
        (self.root / "current_rules.json").write_text(
            (ROOT / "current_rules.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _copy_example(self, name: str) -> Path:
        dest = self.root / name
        dest.write_text((ROOT / "examples" / name).read_text(encoding="utf-8"), encoding="utf-8")
        return dest

    def _complete_payload(self, date: str = "2099-01-01") -> dict:
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

    def test_write_renames_tmp_to_formal_when_ready(self):
        payload = self._complete_payload()
        path = chatgpt_io.write_chatgpt_input(self.root, payload)
        formal = chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        tmp = chatgpt_io.chatgpt_input_tmp_path(self.root, "2099-01-01")
        self.assertEqual(path, formal)
        self.assertTrue(formal.is_file())
        self.assertFalse(tmp.exists())
        data = json.loads(formal.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "ready")
        self.assertTrue(data["data_complete"])
        self.assertEqual(data["missing_fields"], [])
        self.assertEqual(data["candidate_count"], 3)
        self.assertEqual(data["date"], "2099-01-01")
        self.assertTrue(data["generated_at"])
        self.assertTrue(data["source_updated_at"])
        self.assertTrue(chatgpt_io.is_chatgpt_input_ready(self.root, "2099-01-01"))

    def test_incomplete_stays_tmp_and_has_no_formal(self):
        payload = chatgpt_io.build_chatgpt_input(
            date="2099-01-01",
            candidates=[
                {"venue": "テスト競輪場A", "race_number": 7, "deadline": "18:20", "riders": []},
                {"venue": "テスト競輪場B", "race_number": 8, "deadline": "19:00", "riders": [{"number": 1}]},
                {"venue": "", "race_number": 9, "deadline": "", "riders": []},
            ],
        )
        path = chatgpt_io.write_chatgpt_input(self.root, payload)
        formal = chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        tmp = chatgpt_io.chatgpt_input_tmp_path(self.root, "2099-01-01")
        self.assertEqual(path, tmp)
        self.assertTrue(tmp.is_file())
        self.assertFalse(formal.exists())
        data = json.loads(tmp.read_text(encoding="utf-8"))
        self.assertNotEqual(data["status"], "ready")
        self.assertFalse(data["data_complete"])
        self.assertTrue(data["missing_fields"])
        self.assertFalse(chatgpt_io.is_chatgpt_input_ready(self.root, "2099-01-01"))
        self.assertIn("一時ファイルのみ", chatgpt_io.chatgpt_input_readiness_message(self.root, "2099-01-01"))

    def test_leftover_tmp_is_not_ready_for_chatgpt(self):
        tmp = chatgpt_io.chatgpt_input_tmp_path(self.root, "2099-01-01")
        tmp.write_text(json.dumps(self._complete_payload(), ensure_ascii=False), encoding="utf-8")
        self.assertFalse(chatgpt_io.is_chatgpt_input_ready(self.root, "2099-01-01"))
        self.assertFalse(chatgpt_io.chatgpt_input_path(self.root, "2099-01-01").exists())

    def test_incomplete_rewrite_removes_stale_formal(self):
        chatgpt_io.write_chatgpt_input(self.root, self._complete_payload())
        self.assertTrue(chatgpt_io.chatgpt_input_path(self.root, "2099-01-01").is_file())
        broken = chatgpt_io.build_chatgpt_input(date="2099-01-01", candidates=[])
        chatgpt_io.write_chatgpt_input(self.root, broken)
        self.assertFalse(chatgpt_io.chatgpt_input_path(self.root, "2099-01-01").exists())
        self.assertTrue(chatgpt_io.chatgpt_input_tmp_path(self.root, "2099-01-01").is_file())

    def test_prepare_today_writes_formal_ready_file(self):
        races = self._copy_example("races_collect.example.json")
        text = flow.prepare_today(self.root, "2099-01-01", races_file=races)
        self.assertIn("データ準備完了", text)
        self.assertIn("prediction_input_2099-01-01.json", text)
        self.assertIn("ChatGPT処理可能", text)
        formal = chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        tmp = chatgpt_io.chatgpt_input_tmp_path(self.root, "2099-01-01")
        self.assertTrue(formal.is_file())
        self.assertFalse(tmp.exists())
        data = json.loads(formal.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "ready")
        self.assertTrue(data["data_complete"])

    def test_final_ticket_count_mismatch_stops_without_fix(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = json.loads((ROOT / "examples" / "chatgpt_final.example.json").read_text(encoding="utf-8"))
        final["predictions"][0]["ticket_count"] = 99
        path = self.root / "bad_final.json"
        path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        original = path.read_text(encoding="utf-8")
        store = sheets.MemorySheetStore()
        with self.assertRaises(Exception) as ctx:
            flow.ingest_final(
                self.root,
                "2099-01-01",
                final_file=path,
                sheet_store=store,
                write_sheets=True,
            )
        self.assertEqual(type(ctx.exception).__name__, "ValidationError")
        self.assertIn("補正しません", str(ctx.exception))
        self.assertIn("記載=99", str(ctx.exception))
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(json.loads(original)["predictions"][0]["ticket_count"], 99)
        self.assertEqual(store.write_entry_calls, 0)
        self.assertFalse(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").exists())

    def test_final_unknown_rider_stops_without_fix(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = json.loads((ROOT / "examples" / "chatgpt_final.example.json").read_text(encoding="utf-8"))
        final["predictions"][0]["tickets"][0]["pick"] = "1-2-349"
        path = self.root / "unknown_rider.json"
        path.write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        store = sheets.MemorySheetStore()
        with self.assertRaises(Exception) as ctx:
            flow.ingest_final(
                self.root,
                "2099-01-01",
                final_file=path,
                sheet_store=store,
                write_sheets=True,
            )
        self.assertEqual(type(ctx.exception).__name__, "ValidationError")
        self.assertIn("実在しない車番", str(ctx.exception))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["predictions"][0]["tickets"][0]["pick"], "1-2-349")
        self.assertEqual(store.write_entry_calls, 0)

    def test_duplicate_submit_does_not_rewrite_sheet_or_chatwork(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = self._copy_example("chatgpt_final.example.json")
        store = sheets.MemorySheetStore()
        sent: list[int] = []

        def send_fn(_data):
            sent.append(1)
            return {"message_id": str(len(sent))}

        first = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            confirm_send=True,
            send_fn=send_fn,
        )
        self.assertIn("再読で完全一致", first)
        self.assertEqual(store.write_entry_calls, 1)
        self.assertEqual(sent, [1])
        state = submission.load_submission_state(self.root, "2099-01-01")
        self.assertTrue(state["sheet_written"])
        self.assertTrue(state["chatwork_sent"])

        second = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            confirm_send=True,
            send_fn=send_fn,
        )
        self.assertIn("すでに処理済み", second)
        self.assertEqual(store.write_entry_calls, 1)
        self.assertEqual(sent, [1])

    def test_partial_success_retries_chatwork_only(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = self._copy_example("chatgpt_final.example.json")
        store = sheets.MemorySheetStore()
        calls: list[str] = []

        def failing_send(_data):
            calls.append("fail")
            raise RuntimeError("Chatwork一時障害")

        def ok_send(_data):
            calls.append("ok")
            return {"message_id": "2"}

        first = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            confirm_send=True,
            send_fn=failing_send,
        )
        self.assertIn("Chatwork送信に失敗", first)
        self.assertEqual(store.write_entry_calls, 1)
        state = submission.load_submission_state(self.root, "2099-01-01")
        self.assertTrue(state["sheet_written"])
        self.assertFalse(state["chatwork_sent"])

        second = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            confirm_send=True,
            send_fn=ok_send,
        )
        self.assertIn("再書き込みしません", second)
        self.assertIn("Chatwork: ", second)
        self.assertEqual(store.write_entry_calls, 1)
        self.assertEqual(calls, ["fail", "ok"])
        state = submission.load_submission_state(self.root, "2099-01-01")
        self.assertTrue(state["chatwork_sent"])


if __name__ == "__main__":
    unittest.main()
