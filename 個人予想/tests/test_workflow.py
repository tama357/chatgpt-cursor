import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fixtures import install_test_races  # noqa: E402

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
SPORTS = ("jra", "nar", "kyotei")
EXCEL_KEYS = (
    "jra_entry",
    "jra_summary",
    "nar_entry",
    "nar_summary",
    "kyotei_entry",
    "kyotei_summary",
)


class PersonalWorkflowTest(unittest.TestCase):
    """通し確認は examples を test_fixture として置く（テストデータ使用。本番フォールバックではない）。"""

    def setUp(self):
        self.data_dir = ROOT / "data"
        for sport in SPORTS:
            sport_dir = self.data_dir / sport
            races_dir = self.data_dir / "races" / sport
            if sport_dir.exists():
                for f in sport_dir.glob("*.json"):
                    f.unlink()
            races_dir.mkdir(parents=True, exist_ok=True)
            for f in races_dir.glob("*.json"):
                f.unlink()
            install_test_races(ROOT, sport, TEST_DATE)

    def test_expand_pick(self):
        self.assertEqual(
            tickets.expand_pick("4-2-135"),
            ("4-2-1", "4-2-3", "4-2-5"),
        )

    def test_init_excel_six_files_and_months(self):
        msg = workflow.init_excel_cmd()
        self.assertIn("中央競馬", msg)
        self.assertIn("地方競馬", msg)
        self.assertIn("競艇", msg)
        excel = workflow.ensure_workbooks(workflow.ROOT)
        for key in EXCEL_KEYS:
            self.assertIn(key, excel)
            self.assertTrue(excel[key].exists())
        self.assertNotIn("keiba_entry", excel)
        self.assertNotIn("keirin_entry", excel)
        from openpyxl import load_workbook
        from common.constants import MONTH_SHEETS

        for path in excel.values():
            wb = load_workbook(path, read_only=True)
            for month in MONTH_SHEETS:
                self.assertIn(month, wb.sheetnames, f"{path.name} に {month} がない")
            wb.close()

    def test_predict_jra_from_sample(self):
        """テストデータ使用: examples を test_fixture として中央競馬の通しを確認する。"""
        report = workflow.run_predict("jra", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("中央競馬", report)
        self.assertIn("中山", report)
        state = workflow.load_json(workflow.state_path("jra"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 5)
        self.assertTrue(all(r.get("sport") == "jra" for r in selected))

    def test_predict_nar_max_five(self):
        """テストデータ使用: 地方競馬は最大5レース。"""
        report = workflow.run_predict("nar", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("地方競馬", report)
        self.assertIn("大井", report)
        state = workflow.load_json(workflow.state_path("nar"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertEqual(len(selected), 5)
        self.assertTrue(all(r.get("sport") == "nar" for r in selected))
        venues = {r["venue"] for r in selected}
        self.assertNotIn("中山", venues)

    def test_predict_kyotei_from_sample(self):
        """テストデータ使用: 競艇の通しを確認する。"""
        report = workflow.run_predict("kyotei", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("競艇", report)
        state = workflow.load_json(workflow.state_path("kyotei"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 5)

    def test_predict_keiba_and_keirin_not_used(self):
        self.assertIn("未対応", workflow.run_predict("keiba", TEST_DATE, force=True, sync_drive=False))
        self.assertIn("未対応", workflow.run_predict("keirin", TEST_DATE, force=True, sync_drive=False))

    def test_learning_data_is_separated(self):
        workflow.run_predict("jra", TEST_DATE, force=True, sync_drive=False)
        workflow.run_predict("nar", TEST_DATE, force=True, sync_drive=False)
        workflow.apply_results_from_file(
            "jra", TEST_DATE, ROOT / "examples" / "jra_results.sample.json", sync_drive=False
        )
        workflow.apply_results_from_file(
            "nar", TEST_DATE, ROOT / "examples" / "nar_results.sample.json", sync_drive=False
        )
        jra_state = workflow.load_json(workflow.state_path("jra"))
        nar_state = workflow.load_json(workflow.state_path("nar"))
        jra_venues = {r.get("venue") for r in jra_state["records"] if r.get("tickets")}
        nar_venues = {r.get("venue") for r in nar_state["records"] if r.get("tickets")}
        self.assertTrue(jra_venues)
        self.assertTrue(nar_venues)
        self.assertFalse(jra_venues & nar_venues)
        jra_learn = workflow.run_learning_report("jra")
        nar_learn = workflow.run_learning_report("nar")
        self.assertIn("100レースまでの残り", jra_learn)
        self.assertIn("100レースまでの残り", nar_learn)
        self.assertTrue((ROOT / "data" / "jra" / "learning_report.json").exists())
        self.assertTrue((ROOT / "data" / "nar" / "learning_report.json").exists())
        self.assertNotEqual(
            workflow.state_path("jra"),
            workflow.state_path("nar"),
        )

    def test_idempotent_predict_without_force(self):
        workflow.run_predict("jra", TEST_DATE, force=True, sync_drive=False)
        second = workflow.run_predict("jra", TEST_DATE, force=False, sync_drive=False)
        self.assertIn("二重登録防止", second)

    def test_apply_results_and_review(self):
        workflow.run_predict("jra", TEST_DATE, force=True, sync_drive=False)
        report = workflow.apply_results_from_file(
            "jra", TEST_DATE, ROOT / "examples" / "jra_results.sample.json", sync_drive=False
        )
        self.assertIn("結果報告", report)
        state = workflow.load_json(workflow.state_path("jra"))
        completed = [r for r in state["records"] if r.get("review")]
        self.assertGreater(len(completed), 0)


if __name__ == "__main__":
    unittest.main()
