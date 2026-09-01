import importlib.util
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fixtures import (  # noqa: E402
    PRODUCTION_ROOT,
    TEST_DATE,
    ProductionDataGuardMixin,
    make_sandbox,
    write_canonical_states,
)

ROOT = PRODUCTION_ROOT
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

SPORTS = ("jra", "nar", "kyotei")
EXCEL_KEYS = (
    "jra_entry",
    "jra_summary",
    "nar_entry",
    "nar_summary",
    "kyotei_entry",
    "kyotei_summary",
)


class PersonalWorkflowTest(ProductionDataGuardMixin, unittest.TestCase):
    """通し確認は一時ディレクトリ＋ allow_sample=True（テストデータ使用）。"""

    def setUp(self):
        super().setUp()
        self.sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, self.sandbox, True)
        write_canonical_states(self.sandbox, start_date=TEST_DATE)
        self._orig_root = workflow.ROOT
        workflow.ROOT = self.sandbox
        self.addCleanup(setattr, workflow, "ROOT", self._orig_root)

    def _predict(self, sport: str, **kwargs):
        kwargs.setdefault("force", True)
        kwargs.setdefault("sync_drive", False)
        kwargs.setdefault("allow_sample", True)
        kwargs.setdefault("try_auto", False)
        return workflow.run_predict(sport, TEST_DATE, **kwargs)

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
        """テストデータ使用: allow_sample=True で中央競馬の通しを確認する。"""
        report = self._predict("jra")
        self.assertIn("中央競馬", report)
        self.assertIn("中山", report)
        state = workflow.load_json(workflow.state_path("jra"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 5)
        self.assertTrue(all(r.get("sport") == "jra" for r in selected))

    def test_predict_nar_max_five(self):
        """テストデータ使用: 地方競馬は最大5レース。"""
        report = self._predict("nar")
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
        report = self._predict("kyotei")
        self.assertIn("競艇", report)
        state = workflow.load_json(workflow.state_path("kyotei"))
        selected = [r for r in state["records"] if r["date"] == TEST_DATE and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertLessEqual(len(selected), 5)

    def test_predict_keiba_and_keirin_not_used(self):
        self.assertIn("未対応", workflow.run_predict("keiba", TEST_DATE, force=True, sync_drive=False))
        self.assertIn("未対応", workflow.run_predict("keirin", TEST_DATE, force=True, sync_drive=False))

    def test_learning_data_is_separated(self):
        self._predict("jra")
        self._predict("nar")
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
        self.assertTrue((workflow.ROOT / "data" / "jra" / "learning_report.json").exists())
        self.assertTrue((workflow.ROOT / "data" / "nar" / "learning_report.json").exists())
        self.assertNotEqual(
            workflow.state_path("jra"),
            workflow.state_path("nar"),
        )

    def test_idempotent_predict_without_force(self):
        self._predict("jra")
        second = self._predict("jra", force=False)
        self.assertIn("二重登録防止", second)

    def test_apply_results_and_review(self):
        self._predict("jra")
        report = workflow.apply_results_from_file(
            "jra", TEST_DATE, ROOT / "examples" / "jra_results.sample.json", sync_drive=False
        )
        self.assertIn("結果報告", report)
        state = workflow.load_json(workflow.state_path("jra"))
        completed = [r for r in state["records"] if r.get("review")]
        self.assertGreater(len(completed), 0)

    def test_partial_results_are_not_marked_processed(self):
        self._predict("nar")
        state = workflow.load_json(workflow.state_path("nar"))
        selected = [
            r
            for r in state["records"]
            if r.get("date") == TEST_DATE and r.get("tickets")
        ]
        self.assertGreaterEqual(len(selected), 2)
        first, rest = selected[0], selected[1:]
        from fetch.race_builder import save_results_json

        save_results_json(
            workflow.ROOT,
            "nar",
            TEST_DATE,
            [
                {
                    "venue": first["venue"],
                    "race": first["race"],
                    "trifecta": "1-2-3",
                    "payout": 1200,
                }
            ],
            source="auto_fetch",
        )
        with patch("orchestrator.fetch_keiba_results", return_value=[]):
            report = workflow.run_results("nar", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("処理済みにはしません", report)
        state = workflow.load_json(workflow.state_path("nar"))
        self.assertFalse(
            workflow.is_processed(
                state, f"results:{TEST_DATE}", {"date": TEST_DATE, "sport": "nar"}
            )
        )
        with_result = [
            r for r in state["records"] if r.get("date") == TEST_DATE and r.get("result")
        ]
        self.assertEqual(len(with_result), 1)
        self.assertEqual(with_result[0]["venue"], first["venue"])

        remaining_payload = [
            {
                "venue": r["venue"],
                "race": r["race"],
                "trifecta": "2-3-4",
                "payout": 800,
            }
            for r in rest
        ]
        with patch("orchestrator.fetch_keiba_results", return_value=remaining_payload):
            second = workflow.run_results("nar", TEST_DATE, force=True, sync_drive=False)
        self.assertNotIn("処理済みにはしません", second)
        state = workflow.load_json(workflow.state_path("nar"))
        self.assertTrue(
            workflow.is_processed(
                state, f"results:{TEST_DATE}", {"date": TEST_DATE, "sport": "nar"}
            )
        )
        again = workflow.run_results("nar", TEST_DATE, force=False, sync_drive=False)
        self.assertIn("二重登録防止", again)
        # 取得済みは上書きしない
        first_after = next(
            r
            for r in state["records"]
            if r.get("venue") == first["venue"] and r.get("race") == first["race"]
        )
        self.assertEqual(first_after["result"]["trifecta"], "1-2-3")


if __name__ == "__main__":
    unittest.main()
