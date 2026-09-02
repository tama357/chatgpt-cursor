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
        self.assertIn("最終3Rと買い目は作っていません", text)
        path = chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["role"], "chatgpt_input")
        self.assertGreaterEqual(len(data["candidates"]), 5)
        self.assertLessEqual(len(data["candidates"]), 10)
        for item in data["candidates"]:
            self.assertIn("prediction_score", item)
            self.assertIn("riders", item)
            self.assertIn("risk_factors", item)
            self.assertIn("source", item)
            self.assertNotIn("tickets", item)
            self.assertGreaterEqual(item["deadline"] or item["close_time"], "18:00")
        self.assertTrue(all("17:50" not in (c.get("deadline") or "") for c in data["candidates"]))

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


if __name__ == "__main__":
    unittest.main()
