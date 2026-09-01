import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from orchestrator import ensure_race_data, run_predict_today  # noqa: E402

WORKFLOW_PATH = ROOT / "tools" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("personal_workflow", WORKFLOW_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

TEST_DATE = "2026-09-01"


class OrchestratorTest(unittest.TestCase):
    def test_ensure_keirin_race_data(self):
        races, status = ensure_race_data(ROOT, "keirin", TEST_DATE)
        path = ROOT / "data" / "races" / "keirin" / f"{TEST_DATE}.json"
        if races:
            self.assertTrue(path.exists())
            self.assertIn("✅", status)
        else:
            self.assertIn("⚠", status)

    def test_predict_today_runs(self):
        report = run_predict_today(
            ROOT,
            target_date=TEST_DATE,
            force=True,
            run_predict_fn=workflow.run_predict,
        )
        self.assertIn("今日の予想", report)
        self.assertIn("個人競輪", report)


if __name__ == "__main__":
    unittest.main()
