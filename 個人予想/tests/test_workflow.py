import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "tools" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("personal_workflow", WORKFLOW_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

TICKETS_PATH = ROOT / "tools" / "common" / "tickets.py"
TSPEC = importlib.util.spec_from_file_location("tickets", TICKETS_PATH)
tickets = importlib.util.module_from_spec(TSPEC)
assert TSPEC.loader is not None
sys.modules[TSPEC.name] = tickets
TSPEC.loader.exec_module(tickets)

TEST_DATE = "2026-09-01"


class PersonalWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = ROOT / "data"
        for sport in ("keiba", "kyotei"):
            sport_dir = self.data_dir / sport
            races_dir = self.data_dir / "races" / sport
            if sport_dir.exists():
                for f in sport_dir.glob("*.json"):
                    f.unlink()
            races_dir.mkdir(parents=True, exist_ok=True)
            for f in races_dir.glob("*.json"):
                f.unlink()
            sample = ROOT / "examples" / f"{sport}_races.sample.json"
            if sample.exists():
                shutil.copy2(sample, races_dir / f"{TEST_DATE}.json")

    def test_expand_pick(self):
        self.assertEqual(
            tickets.expand_pick("4-2-135"),
            ("4-2-1", "4-2-3", "4-2-5"),
        )

    def test_init_excel_checks_files(self):
        msg = workflow.init_excel_cmd()
        self.assertIn("手動入力版", msg)
        self.assertIn("sheet_mapping.json", msg)
        excel = workflow.ensure_workbooks(workflow.ROOT)
        self.assertIn("kyotei_entry", excel)
        self.assertIn("kyotei_summary", excel)
        self.assertNotIn("keirin_entry", excel)
        for path in excel.values():
            self.assertTrue(path.exists())

    def test_predict_keiba_from_sample(self):
        report = workflow.run_predict("keiba", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("競馬", report)
        self.assertIn("中山", report)
        state = workflow.load_json(workflow.state_path("keiba"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 5)

    def test_predict_kyotei_from_sample(self):
        report = workflow.run_predict("kyotei", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("競艇", report)
        self.assertIn("多摩川", report)
        state = workflow.load_json(workflow.state_path("kyotei"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 5)
        for rec in selected:
            self.assertLessEqual(rec.get("ticket_count", 0), 20)

    def test_predict_keirin_not_used(self):
        msg = workflow.run_predict("keirin", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("未対応", msg)

    def test_idempotent_predict_without_force(self):
        workflow.run_predict("keiba", TEST_DATE, force=True, sync_drive=False)
        second = workflow.run_predict("keiba", TEST_DATE, force=False, sync_drive=False)
        self.assertIn("二重登録防止", second)

    def test_apply_results_and_review(self):
        workflow.run_predict("keiba", TEST_DATE, force=True, sync_drive=False)
        results_file = ROOT / "examples" / "keiba_results.sample.json"
        report = workflow.apply_results_from_file("keiba", TEST_DATE, results_file, sync_drive=False)
        self.assertIn("結果報告", report)
        state = workflow.load_json(workflow.state_path("keiba"))
        completed = [r for r in state["records"] if r.get("review")]
        self.assertGreater(len(completed), 0)

    def test_learning_report_collection_phase(self):
        workflow.run_predict("kyotei", TEST_DATE, force=True, sync_drive=False)
        results_file = ROOT / "examples" / "kyotei_results.sample.json"
        workflow.apply_results_from_file("kyotei", TEST_DATE, results_file, sync_drive=False)
        report = workflow.run_learning_report("kyotei")
        self.assertIn("100レースまでの残り", report)
        self.assertIn("自動反映", report)

    def test_prediction_score_and_confidence_separate(self):
        workflow.run_predict("keiba", TEST_DATE, force=True, sync_drive=False)
        state = workflow.load_json(workflow.state_path("keiba"))
        for record in state["records"]:
            if record.get("tickets"):
                self.assertIn("prediction_score", record)
                self.assertIn("confidence", record)


if __name__ == "__main__":
    unittest.main()
