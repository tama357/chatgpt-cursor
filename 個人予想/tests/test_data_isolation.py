"""本番 data をテストが変更・削除しないことの確認。"""

from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fixtures import (  # noqa: E402
    PRODUCTION_ROOT,
    TEST_DATE,
    ProductionDataGuardMixin,
    make_sandbox,
    seed_dummy_runtime,
    snapshot_tree,
)

ROOT = PRODUCTION_ROOT
sys.path.insert(0, str(ROOT / "tools"))

from fetch import jra as fetch_jra  # noqa: E402
from fetch import kyotei as fetch_kyotei  # noqa: E402
from fetch import nar as fetch_nar  # noqa: E402


class DataIsolationTest(ProductionDataGuardMixin, unittest.TestCase):
    def test_e2e_script_does_not_write_report_file(self):
        src = (PRODUCTION_ROOT / "tests" / "run_e2e_excel_copy_test.py").read_text(encoding="utf-8")
        self.assertNotIn("write_text", src)
        self.assertNotIn(".write(", src)

    def test_cleanup_production_helper_is_gone(self):
        fixtures = importlib.import_module("test_fixtures")
        self.assertFalse(hasattr(fixtures, "cleanup_production_runtime_files"))

    def test_write_leftover_sample_rejects_production_data(self):
        from test_fixtures import write_leftover_sample

        with self.assertRaises(RuntimeError):
            write_leftover_sample(PRODUCTION_ROOT, "jra", "test_fixture", "中山")

    def test_seed_dummy_rejects_production_data(self):
        with self.assertRaises(RuntimeError):
            seed_dummy_runtime(PRODUCTION_ROOT)

    def test_dummy_runtime_files_survive_predict_flow(self):
        """別ルートのダミー state / 学習 / レース結果は、テスト実行後もハッシュが一致する。"""
        verify = Path(tempfile.mkdtemp(prefix="personal-verify-"))
        sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, verify, True)
        self.addCleanup(shutil.rmtree, sandbox, True)
        seed_dummy_runtime(verify)
        before = snapshot_tree(verify)
        self.assertIn("data/jra/state.json", before)
        self.assertIn("data/nar/learning_report.json", before)
        self.assertIn(f"data/races/jra/{TEST_DATE}.json", before)
        self.assertIn(f"data/results/kyotei/{TEST_DATE}.json", before)
        self.assertIn("data/keiba/state.json", before)

        with (
            patch.object(fetch_jra, "auto_fetch", return_value=[]),
            patch.object(fetch_nar, "auto_fetch", return_value=[]),
            patch.object(fetch_kyotei, "auto_fetch", return_value=[]),
        ):
            fetch_jra.fetch_races(sandbox, TEST_DATE, allow_sample=False, try_auto=True)
            fetch_nar.fetch_races(sandbox, TEST_DATE, allow_sample=False, try_auto=True)
            fetch_kyotei.fetch_races(sandbox, TEST_DATE, allow_sample=False, try_auto=True)

        after = snapshot_tree(verify)
        self.assertEqual(before, after)
        self.assertEqual(before["data/keiba/state.json"], after["data/keiba/state.json"])
