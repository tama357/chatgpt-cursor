"""実サイトの過去正式結果を一時確認する。Drive・本番Excel・本番stateには書かない。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_fixtures import PRODUCTION_ROOT, ProductionDataGuardMixin  # noqa: E402

from fetch.kyotei_auto import fetch_result_trifecta as fetch_kyotei_result  # noqa: E402
from fetch.netkeiba import fetch_result_trifecta  # noqa: E402


class LiveOfficialResultsTest(ProductionDataGuardMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="personal-live-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.assertNotEqual(self.tmp.resolve(), (PRODUCTION_ROOT / "data").resolve())

    def test_jra_official_trifecta_and_payout(self):
        parsed = fetch_result_trifecta("202601020401", circuit="jra")
        self.assertIsNotNone(parsed, "中央競馬の公式結果を取得できませんでした")
        self.assertEqual(parsed["trifecta"], "1-4-7")
        self.assertEqual(parsed["payout"], 21300)

    def test_nar_official_trifecta_and_payout(self):
        parsed = fetch_result_trifecta("202630090101", circuit="nar")
        self.assertIsNotNone(parsed, "地方競馬の公式結果を取得できませんでした")
        self.assertEqual(parsed["trifecta"], "6-4-10")
        self.assertEqual(parsed["payout"], 490)

    def test_kyotei_official_trifecta_and_payout(self):
        parsed = fetch_kyotei_result("04", 1, "20260831")
        self.assertIsNotNone(parsed, "競艇の公式結果を取得できませんでした")
        self.assertEqual(parsed["trifecta"], "1-2-3")
        self.assertEqual(parsed["payout"], 1020)

    def test_live_test_does_not_write_production(self):
        data = PRODUCTION_ROOT / "data"
        before = {p: p.stat().st_mtime for p in data.rglob("*") if p.is_file()} if data.exists() else {}
        fetch_result_trifecta("202601020401", circuit="jra")
        after = {p: p.stat().st_mtime for p in data.rglob("*") if p.is_file()} if data.exists() else {}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
