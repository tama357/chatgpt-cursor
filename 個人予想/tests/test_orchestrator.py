import importlib.util
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


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


def _copy_sample(sport: str) -> Path:
    src = ROOT / "examples" / f"{sport}_races.sample.json"
    dest = ROOT / "data" / "races" / sport / f"{TEST_DATE}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


class OrchestratorTest(unittest.TestCase):
    def test_ensure_kyotei_race_data(self):
        path = _copy_sample("kyotei")
        races, status = ensure_race_data(ROOT, "kyotei", TEST_DATE)
        self.assertTrue(path.exists())
        self.assertGreaterEqual(len(races), 1)
        self.assertIn("✅", status)
        self.assertIn("競艇", status)

    def test_predict_today_runs(self):
        _copy_sample("keiba")
        _copy_sample("kyotei")
        report = run_predict_today(
            ROOT,
            target_date=TEST_DATE,
            force=True,
            run_predict_fn=workflow.run_predict,
        )
        self.assertIn("今日の予想", report)
        self.assertIn("競艇", report)
        self.assertNotIn("個人競輪", report)


if __name__ == "__main__":
    unittest.main()
