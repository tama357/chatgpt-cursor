"""本番コマンドが examples / test_fixture にフォールバックしないことのテスト。"""

from __future__ import annotations

import importlib.util
import inspect
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
    write_leftover_sample,
)

ROOT = PRODUCTION_ROOT
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
from orchestrator import run_predict_today  # noqa: E402


class NoSampleFallbackTest(ProductionDataGuardMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, self.sandbox, True)
        self._orig_root = workflow.ROOT
        workflow.ROOT = self.sandbox
        self.addCleanup(setattr, workflow, "ROOT", self._orig_root)

    def test_fetch_defaults_disallow_sample(self):
        for fn in (fetch_jra.fetch_races, fetch_nar.fetch_races, fetch_kyotei.fetch_races):
            default = inspect.signature(fn).parameters["allow_sample"].default
            self.assertIs(default, False)
        self.assertIs(
            inspect.signature(workflow.run_predict).parameters["allow_sample"].default,
            False,
        )

    def test_predict_today_has_no_allow_sample_parameter(self):
        self.assertNotIn(
            "allow_sample", inspect.signature(run_predict_today).parameters
        )
        src = inspect.getsource(workflow.main)
        self.assertNotIn("allow_sample=True", src)

    def test_cli_rejects_allow_sample_flag(self):
        with self.assertRaises(SystemExit):
            workflow.build_parser().parse_args(["predict-jra", "--allow-sample"])
        with self.assertRaises(SystemExit):
            workflow.build_parser().parse_args(["predict-today", "--allow-sample"])
        with self.assertRaises(SystemExit):
            workflow.build_parser().parse_args(["predict-all", "--allow-sample", "true"])

    def test_jra_2026_09_01_no_meeting_production_zero(self):
        """本番モード: 2026-09-01 は JRA非開催。サンプルの中山・阪神・新潟を使わない。"""
        with patch.object(fetch_jra, "auto_fetch", return_value=[]):
            races = fetch_jra.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=False, try_auto=True
            )
            self.assertEqual(races, [])
            races_default = fetch_jra.fetch_races(self.sandbox, TEST_DATE)
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
                self.sandbox, TEST_DATE, allow_sample=False, try_auto=True
            )
            allowed = fetch_jra.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=True, try_auto=False
            )
        self.assertEqual(denied, [])
        self.assertGreaterEqual(len(allowed), 1)
        self.assertTrue(any(r.get("venue") == "中山" for r in allowed))

    def test_nar_kyotei_fetch_failure_does_not_use_sample(self):
        with patch.object(fetch_nar, "auto_fetch", return_value=[]):
            nar_races = fetch_nar.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=False, try_auto=True
            )
            nar_report = workflow.run_predict(
                "nar", TEST_DATE, force=True, sync_drive=False
            )
        with patch.object(fetch_kyotei, "auto_fetch", return_value=[]):
            kyotei_races = fetch_kyotei.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=False, try_auto=True
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
        dest = write_leftover_sample(self.sandbox, "jra", "sample", "中山")
        loaded = load_race_data(self.sandbox, "jra", TEST_DATE, allow_sample=False)
        self.assertEqual(loaded, [])
        with patch.object(fetch_jra, "auto_fetch", return_value=[]):
            races = fetch_jra.fetch_races(self.sandbox, TEST_DATE, allow_sample=False)
        self.assertEqual(races, [])
        self.assertTrue(dest.exists())

    def test_test_fixture_json_is_ignored_in_production(self):
        """source=test_fixture が残っていても本番モードでは中央競馬0件。"""
        dest = write_leftover_sample(self.sandbox, "jra", "test_fixture", "中山")
        loaded = load_race_data(self.sandbox, "jra", TEST_DATE, allow_sample=False)
        self.assertEqual(loaded, [])
        with patch.object(fetch_jra, "auto_fetch", return_value=[]):
            races = fetch_jra.fetch_races(
                self.sandbox, TEST_DATE, allow_sample=False, try_auto=True
            )
            report = workflow.run_predict("jra", TEST_DATE, force=True, sync_drive=False)
        self.assertEqual(races, [])
        self.assertIn("開催なし", report)
        self.assertNotIn("中山", report)
        self.assertNotIn("阪神", report)
        self.assertNotIn("新潟", report)
        self.assertTrue(dest.exists())

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

    def test_install_test_races_rejects_production_data(self):
        from test_fixtures import install_test_races

        with self.assertRaises(RuntimeError):
            install_test_races(ROOT, "jra", TEST_DATE)

    def test_leftover_fixture_does_not_require_deleting_files(self):
        for sport, venue in (("jra", "中山"), ("nar", "大井"), ("kyotei", "多摩川")):
            dest = write_leftover_sample(self.sandbox, sport, "test_fixture", venue)
            self.assertTrue(dest.exists())
        with (
            patch.object(fetch_jra, "auto_fetch", return_value=[]),
            patch.object(fetch_nar, "auto_fetch", return_value=[]),
            patch.object(fetch_kyotei, "auto_fetch", return_value=[]),
        ):
            report = run_predict_today(
                self.sandbox,
                target_date=TEST_DATE,
                force=True,
                run_predict_fn=workflow.run_predict,
            )
        self.assertIn("開催なし", report)
        self.assertNotIn("中山", report)
        self.assertNotIn("阪神", report)
        self.assertNotIn("新潟", report)
        self.assertIn("サンプルデータは使いません", report)
        self.assertNotIn("大井", report)
        self.assertNotIn("多摩川", report)
        for sport in ("jra", "nar", "kyotei"):
            leftover = self.sandbox / "data" / "races" / sport / f"{TEST_DATE}.json"
            self.assertTrue(leftover.exists())


if __name__ == "__main__":
    unittest.main()
