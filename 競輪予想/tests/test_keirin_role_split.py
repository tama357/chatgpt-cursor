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


workflow = _load("keirin_workflow", TOOLS / "keirin_workflow.py")
flow = _load("keirin_cursor_flow", TOOLS / "keirin_cursor_flow.py")
chatgpt_io = _load("keirin_chatgpt_io", TOOLS / "keirin_chatgpt_io.py")
sheets = _load("keirin_sheets", TOOLS / "keirin_sheets.py")
submission = _load("keirin_submission_state", TOOLS / "keirin_submission_state.py")


class KeirinRoleSplitTest(unittest.TestCase):
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
        src = ROOT / "examples" / name
        dest = self.root / name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        return dest

    def test_prepare_today_extracts_candidates_without_tickets(self):
        races = self._copy_example("races_collect.example.json")
        text = flow.prepare_today(self.root, "2099-01-01", races_file=races)
        self.assertIn("データ準備完了", text)
        self.assertIn("第一予想をinputへ入れました", text)
        self.assertIn("シート転記もChatwork送信も行いません", text)
        path = chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["role"], "chatgpt_input")
        self.assertEqual(data["status"], "ready")
        self.assertTrue(data["data_complete"])
        self.assertGreaterEqual(len(data["candidates"]), 5)
        self.assertLessEqual(len(data["candidates"]), 10)
        self.assertIn("cursor_first_prediction", data)
        self.assertFalse(data["cursor_first_prediction"]["is_final"])
        for item in data["candidates"]:
            self.assertIn("prediction_score", item)
            self.assertIn("riders", item)
            self.assertIn("risk_factors", item)
            self.assertIn("source", item)
            self.assertNotIn("tickets", item)
            self.assertGreaterEqual(item["deadline"] or item["close_time"], "18:00")
        self.assertTrue(all("17:50" not in (c.get("deadline") or "") for c in data["candidates"]))
        self.assertFalse(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").exists())

    def test_predict_today_stops_without_final(self):
        races = self._copy_example("races_collect.example.json")
        text = flow.run_today_or_stop(self.root, "2099-01-01", races_file=races)
        self.assertIn(flow.STOP_NO_FINAL, text)
        data = json.loads(chatgpt_io.chatgpt_input_path(self.root, "2099-01-01").read_text(encoding="utf-8"))
        self.assertTrue(all("tickets" not in item for item in data["candidates"]))
        self.assertNotIn("predictions", data)

    def test_ingest_stops_when_final_missing(self):
        text = flow.ingest_final(self.root, "2099-01-01", write_sheets=False)
        self.assertIn(flow.STOP_NO_FINAL, text)

    def test_ingest_stops_when_required_fields_missing(self):
        broken = {
            "date": "2099-01-01",
            "predictions": [
                {"number": 1, "venue": "テスト競輪場A", "race": 7},
                {"number": 2, "venue": "テスト競輪場B", "race": 10},
                {"number": 3, "venue": "テスト競輪場C", "race": 12},
            ],
        }
        path = self.root / "broken.json"
        path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        text = flow.ingest_final(self.root, "2099-01-01", final_file=path, write_sheets=False)
        self.assertIn("停止", text)
        self.assertIn("tickets", text)

    def test_cursor_must_not_create_prediction(self):
        with self.assertRaises(flow.CursorMustNotPredict):
            flow.refuse_cursor_prediction()

    def test_ingest_writes_sheets_and_rereads_chatgpt_values(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = self._copy_example("chatgpt_final.example.json")
        store = sheets.MemorySheetStore()
        text = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
        )
        self.assertIn("再読で完全一致", text)
        self.assertIn("改変していません", text)
        tab = "2099/01/01"
        self.assertEqual(store.read_entry(tab, ["B2"])["B2"], "鉄板")
        self.assertEqual(store.read_entry(tab, ["D2"])["D2"], "テスト競輪場A")
        self.assertEqual(store.read_entry(tab, ["H2"])["H2"], "1-2-345")
        self.assertEqual(store.read_entry(tab, ["D32"])["D32"], "テスト競輪場D")
        self.assertIsNone(store.read_entry(tab, ["J2"]).get("J2"))
        self.assertIsNone(store.read_entry(tab, ["L2"]).get("L2"))
        pred_doc = json.loads(chatgpt_io.predictions_inbox_path(self.root, "2099-01-01").read_text(encoding="utf-8"))
        venues = {(item["venue"], item["race"]) for item in pred_doc["predictions"]}
        self.assertIn(("テスト競輪場D", 11), venues)
        self.assertNotIn(("テスト競輪場C", 12), venues)

    def test_sheet_writer_refuses_formula_columns(self):
        with self.assertRaises(sheets.SheetStructureGuard):
            sheets._assert_entry_updates_safe(
                [sheets.CellUpdate("J2", 5, "合計")], allowed=sheets.ENTRY_INPUT_COLS
            )
        with self.assertRaises(sheets.SheetStructureGuard):
            sheets._assert_summary_updates_safe([sheets.CellUpdate("C13", "触るな", "式")])

    def test_results_write_learning_json_not_sheet_structure(self):
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
        )
        results = {
            "date": "2099-01-01",
            "results": [
                {"number": 1, "venue": "テスト競輪場A", "race": 7, "trifecta": "1-2-3", "payout": 720},
                {"number": 2, "venue": "テスト競輪場B", "race": 10, "trifecta": "7-2-1", "payout": 0},
                {"number": 3, "venue": "テスト競輪場D", "race": 11, "trifecta": "7-6-1", "payout": 1100},
            ],
        }
        results_file = self.root / "official.json"
        results_file.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
        text = flow.process_results(
            self.root,
            "2099-01-01",
            results_file=results_file,
            sheet_store=store,
            write_sheets=True,
        )
        self.assertIn("M/N/O", text)
        self.assertIn("P〜R", text)
        learning = json.loads(chatgpt_io.learning_inbox_path(self.root, "2099-01-01").read_text(encoding="utf-8"))
        self.assertFalse(learning["sheet_structure_changed"])
        self.assertEqual(len(learning["races"]), 3)
        first = learning["races"][0]
        self.assertEqual(first["actual_order"], "1-2-3")
        self.assertEqual(first["status"], "的中")
        self.assertEqual(first["axis_place"], 1)
        self.assertIn("prediction_score", first)
        self.assertIn("close_miss", first)
        self.assertIn("low_quality_day", first)
        self.assertEqual(store.read_entry("2099/01/01", ["O2"])["O2"], "的中")
        self.assertEqual(store.read_summary("2099/01", ["P13"])["P13"], "的中")

    def test_cli_prepare_and_ingest_guards(self):
        races = ROOT / "examples" / "races_collect.example.json"
        with tempfile.TemporaryDirectory() as tmp:
            # CLI uses repo root, so call functions via main only for help/guards
            code = workflow.main(["ingest-final", str(self.root / "missing.json"), "--skip-sheets", "--date", "2099-01-01"])
            self.assertEqual(code, 0)
        text = flow.prepare_today(self.root, "2099-01-01", races_file=races)
        self.assertIn("ChatGPT入力JSON", text)

    def test_chatgpt_can_select_non_top_score(self):
        data = json.loads((ROOT / "examples" / "day_predictions.example.json").read_text(encoding="utf-8"))
        data["predictions"][2]["venue"] = "テスト競輪場D"
        data["predictions"][2]["race"] = 11
        data["predictions"][2]["close_time"] = "20:00"
        data["predictions"][2]["prediction_score"] = 61
        data["predictions"][2]["score_breakdown"] = data["candidates"][3]["score_breakdown"]
        data["predictions"][2]["penalties"] = data["candidates"][3]["penalties"]
        data["low_quality_day"] = True
        for cand in data["candidates"]:
            key = (cand["venue"], cand["race"])
            if key == ("テスト競輪場D", 11):
                cand["selected"] = True
                cand["selection_rank"] = 3
            elif key == ("テスト競輪場C", 12):
                cand["selected"] = False
                cand["selection_rank"] = None
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(data, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["days"][0]["low_quality_day"])
            preds = {(p["venue"], p["race"]) for p in saved["days"][0]["predictions"]}
            self.assertIn(("テスト競輪場D", 11), preds)
            self.assertNotIn(("テスト競輪場C", 12), preds)

    def test_personal_sheet_ids_and_retired_guard(self):
        self.assertEqual(
            sheets.ENTRY_SHEET_NAME, "原田｜競輪予想記入シート（個人運用）"
        )
        self.assertEqual(
            sheets.SUMMARY_SHEET_NAME, "原田｜競輪予想集計シート（個人運用）"
        )
        self.assertEqual(
            sheets.DEFAULT_ENTRY_SHEET_ID,
            "1eDdrUF2KMwm4RN7S1PDfh6mDeCHPSr6xW5C15DAaIgs",
        )
        self.assertEqual(
            sheets.DEFAULT_SUMMARY_SHEET_ID,
            "18wtjSxN0QADJR7SK97d1p8kD1kntL2sQhZNH2T5eTas",
        )
        with mock.patch.dict(
            os.environ,
            {
                "KEIRIN_ENTRY_SHEET_ID": "1jpAV0wKu8FrRK2WX36nEoHo7dp1p8jq8jCv_aDcCjG8",
                "KEIRIN_SUMMARY_SHEET_ID": "18wtjSxN0QADJR7SK97d1p8kD1kntL2sQhZNH2T5eTas",
            },
        ):
            with self.assertRaises(sheets.SheetError) as ctx:
                sheets.resolve_sheet_ids()
            self.assertIn("旧提出用シート", str(ctx.exception))
        entry_id, summary_id = sheets.resolve_sheet_ids()
        self.assertEqual(entry_id, sheets.DEFAULT_ENTRY_SHEET_ID)
        self.assertEqual(summary_id, sheets.DEFAULT_SUMMARY_SHEET_ID)

    def test_chatwork_disabled_does_not_send_or_retry(self):
        self._copy_example("chatgpt_input.example.json").replace(
            chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        )
        final = self._copy_example("chatgpt_final.example.json")
        store = sheets.MemorySheetStore()
        sent: list[int] = []

        def send_fn(_data):
            sent.append(1)
            return {"message_id": "1"}

        text = flow.ingest_final(
            self.root,
            "2099-01-01",
            final_file=final,
            sheet_store=store,
            write_sheets=True,
            confirm_send=True,
            send_fn=send_fn,
        )
        self.assertIn("再読で完全一致", text)
        self.assertIn("Chatwork送信は停止中", text)
        self.assertEqual(sent, [])
        state = submission.load_submission_state(self.root, "2099-01-01")
        self.assertTrue(state["sheet_written"])
        self.assertFalse(state["chatwork_sent"])
        self.assertTrue(submission.already_fully_processed(state))

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
        self.assertEqual(sent, [])

    def test_send_predictions_cli_stays_disabled(self):
        pred_path = ROOT / "examples" / "predictions.example.json"
        with mock.patch.object(workflow, "send_chatwork") as send:
            code = workflow.main(["send-predictions", str(pred_path), "--confirm-send"])
        self.assertEqual(code, 1)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
