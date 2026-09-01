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
)

ROOT = PRODUCTION_ROOT
sys.path.insert(0, str(ROOT / "tools"))

from orchestrator import ensure_race_data, run_predict_today  # noqa: E402
from fetch import jra as fetch_jra  # noqa: E402
from fetch import nar as fetch_nar  # noqa: E402
from fetch import kyotei as fetch_kyotei  # noqa: E402

WORKFLOW_PATH = ROOT / "tools" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("personal_workflow", WORKFLOW_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

FETCH_MODS = (
    ("jra", "中央競馬", fetch_jra),
    ("nar", "地方競馬", fetch_nar),
    ("kyotei", "競艇", fetch_kyotei),
)


class OrchestratorTest(ProductionDataGuardMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, self.sandbox, True)
        self._orig_root = workflow.ROOT
        workflow.ROOT = self.sandbox
        self.addCleanup(setattr, workflow, "ROOT", self._orig_root)

    def test_ensure_three_sports(self):
        for sport, needle, fetch_mod in FETCH_MODS:
            sample = fetch_mod.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=True, try_auto=False
            )
            with patch.object(fetch_mod, "auto_fetch", return_value=sample):
                races, status = ensure_race_data(self.sandbox, sport, TEST_DATE)
            self.assertGreaterEqual(len(races), 1)
            self.assertIn("✅", status)
            self.assertIn(needle, status)

    def test_predict_today_runs_three_sports(self):
        samples = {
            sport: fetch_mod.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=True, try_auto=False
            )
            for sport, _needle, fetch_mod in FETCH_MODS
        }
        with (
            patch.object(fetch_jra, "auto_fetch", return_value=samples["jra"]),
            patch.object(fetch_nar, "auto_fetch", return_value=samples["nar"]),
            patch.object(fetch_kyotei, "auto_fetch", return_value=samples["kyotei"]),
        ):
            report = run_predict_today(
                self.sandbox,
                target_date=TEST_DATE,
                force=True,
                run_predict_fn=workflow.run_predict,
            )
        self.assertIn("今日の予想", report)
        self.assertIn("中央競馬", report)
        self.assertIn("地方競馬", report)
        self.assertIn("競艇", report)
        self.assertNotIn("個人競輪", report)
        self.assertIn("中央競馬_予想記入シート", report)


if __name__ == "__main__":
    unittest.main()
