"""本番コマンドが examples にフォールバックしないことのテスト。"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

WORKFLOW_PATH = ROOT / "tools" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("personal_workflow", WORKFLOW_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

from fetch import jra as fetch_jra  # noqa: E402
from fetch import kyotei as fetch_kyotei  # noqa: E402
from fetch import nar as fetch_nar  # noqa: E402
from fetch.base import load_race_data  # noqa: E402
TEST_DATE = "2026-09-01"


class NoSampleFallbackTest(unittest.TestCase):
    def setUp(self):
        self.data_dir = ROOT / "data"
        for sport in ("jra", "nar", "kyotei"):
            races_dir = self.data_dir / "races" / sport
            races_dir.mkdir(parents=True, exist_ok=True)
            for path in races_dir.glob("*.json"):
                path.unlink()
            sport_dir = self.data_dir / sport
            if sport_dir.exists():
                for path in sport_dir.glob("*.json"):
                    path.unlink()

    def test_fetch_defaults_disallow_sample(self):
        for fn in (fetch_jra.fetch_races, fetch_nar.fetch_races, fetch_kyotei.fetch_races):
            default = inspect.signature(fn).parameters["allow_sample"].default
            self.assertIs(default, False)

    def test_jra_2026_09_01_no_meeting_production_zero(self):
        """本番モード: 2026-09-01 は JRA非開催。サンプルの中山・阪神・新潟を使わない。"""
        with patch.object(fetch_jra, "auto_fetch", return_value=[]):
            races = fetch_jra.fetch_races(
                ROOT, TEST_DATE, allow_sample=False, try_auto=True
            )
            self.assertEqual(races, [])
            races_default = fetch_jra.fetch_races(ROOT, TEST_DATE)
            self.assertEqual(races_default, [])
            report = workflow.run_predict("jra", TEST_DATE, force=True, sync_drive=False)
        self.assertIn("開催なし", report)
        self.assertNotIn("中山", report)
        self.assertNotIn("阪神", report)
        self.assertNotIn("新潟", report)
        state = workflow.load_json(workflow.state_path("jra"))
        selected = [r for r in state.get("records", []) if r.get("tickets")]
        self.assertEqual(selected, [])

    def test_examples_only_when_allow_sample_true(self):
        with patch.object(fetch_jra, "auto_fetch", return_value=[]):
            denied = fetch_jra.fetch_races(
                ROOT, TEST_DATE, allow_sample=False, try_auto=True
            )
            allowed = fetch_jra.fetch_races(
                ROOT, TEST_DATE, allow_sample=True, try_auto=False
            )
        self.assertEqual(denied, [])
        self.assertGreaterEqual(len(allowed), 1)
        self.assertTrue(any(r.get("venue") == "中山" for r in allowed))

    def test_nar_kyotei_fetch_failure_does_not_use_sample(self):
        with patch.object(fetch_nar, "auto_fetch", return_value=[]):
            nar_races = fetch_nar.fetch_races(
                ROOT, TEST_DATE, allow_sample=False, try_auto=True
            )
            nar_report = workflow.run_predict(
                "nar", TEST_DATE, force=True, sync_drive=False
            )
        with patch.object(fetch_kyotei, "auto_fetch", return_value=[]):
            kyotei_races = fetch_kyotei.fetch_races(
                ROOT, TEST_DATE, allow_sample=False, try_auto=True
            )
            kyotei_report = workflow.run_predict(
                "kyotei", TEST_DATE, force=True, sync_drive=False
            )
        self.assertEqual(nar_races, [])
        self.assertEqual(kyotei_races, [])
        self.assertIn("取得失敗", nar_report)
        self.assertIn("取得失敗", kyotei_report)
        self.assertNotIn("大井", nar_report)
        self.assertNotIn("多摩川", kyotei_report)

    def test_leftover_sample_json_is_ignored_in_production(self):
        dest = ROOT / "data" / "races" / "jra" / f"{TEST_DATE}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(
                {
                    "source": "sample",
                    "races": [{"venue": "中山", "race": 11, "entries": [{"number": 1}]}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        loaded = load_race_data(ROOT, "jra", TEST_DATE, allow_sample=False)
        self.assertEqual(loaded, [])
        with patch.object(fetch_jra, "auto_fetch", return_value=[]):
            races = fetch_jra.fetch_races(ROOT, TEST_DATE, allow_sample=False)
        self.assertEqual(races, [])

    def test_production_predict_commands_pass_allow_sample_false(self):
        recorded: list[tuple[str, bool]] = []

        def fake_jra(_base, _date, *, allow_sample=True, try_auto=True):
            recorded.append(("jra", allow_sample))
            return []

        def fake_nar(_base, _date, *, allow_sample=True, try_auto=True):
            recorded.append(("nar", allow_sample))
            return []

        def fake_kyotei(_base, _date, *, allow_sample=True, try_auto=True):
            recorded.append(("kyotei", allow_sample))
            return []

        with (
            patch.object(workflow.fetch_jra, "fetch_races", fake_jra),
            patch.object(workflow.fetch_nar, "fetch_races", fake_nar),
            patch.object(workflow.fetch_kyotei, "fetch_races", fake_kyotei),
        ):
            workflow.main(["predict-jra", "--date", TEST_DATE, "--force"])
            workflow.main(["predict-nar", "--date", TEST_DATE, "--force"])
            workflow.main(["predict-kyotei", "--date", TEST_DATE, "--force"])
            workflow.main(["predict-all", "--date", TEST_DATE, "--force"])
            workflow.main(["predict-today", "--date", TEST_DATE, "--force"])

        self.assertGreaterEqual(len(recorded), 8)
        self.assertTrue(all(flag is False for _, flag in recorded), recorded)
        self.assertEqual({sport for sport, _ in recorded}, {"jra", "nar", "kyotei"})


if __name__ == "__main__":
    unittest.main()
