import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_fixtures import ProductionDataGuardMixin  # noqa: E402

from common.jst import JST, today_str  # noqa: E402
from excel import drive_sync  # noqa: E402
from fetch.base import is_dummy_entry_name, reject_dummy_races  # noqa: E402
from fetch.netkeiba import parse_kaisai_venues, parse_result_trifecta, parse_shutuba  # noqa: E402
from cloud_runner import exclusive_lock, CloudLockError, record_fetch_failure  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "personal-predict.yml"


class CloudActionsTest(ProductionDataGuardMixin, unittest.TestCase):
    def test_workflow_cron_is_jst_4_and_6(self):
        text = WORKFLOW_YML.read_text(encoding="utf-8")
        self.assertIn('cron: "0 19 * * *"', text)
        self.assertIn('cron: "0 21 * * *"', text)
        self.assertIn("workflow_dispatch", text)
        self.assertIn("verify-drive", text)
        self.assertIn("cloud-results", text)
        self.assertIn("cloud-predict", text)
        self.assertIn("personal-predict-cloud", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON", text)
        self.assertNotIn("競輪予想", text)
        self.assertNotIn("chatwork", text.lower())
        self.assertNotIn("gh pr create", text)
        self.assertIn("pull-requests: none", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("PERSONAL_PREDICT_ENABLED", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("bootstrap-cloud", text)
        self.assertIn("migrate-sept2", text)
        self.assertIn(
            "steps.decide.outputs.job == 'verify-drive' || steps.decide.outputs.job == 'bootstrap-cloud'",
            text,
        )
        self.assertIn(
            "steps.gate.outputs.enabled == 'true' && steps.decide.outputs.job == 'results-yesterday'",
            text,
        )
        self.assertIn(
            "steps.gate.outputs.enabled == 'true' && steps.decide.outputs.job == 'predict-today'",
            text,
        )
        self.assertNotIn("init-state", text)

    def test_today_str_uses_jst(self):
        from datetime import datetime

        expected = datetime.now(JST).date().isoformat()
        self.assertEqual(today_str(), expected)

    def test_dummy_races_rejected(self):
        self.assertTrue(is_dummy_entry_name("馬1"))
        self.assertTrue(is_dummy_entry_name("3号艇"))
        self.assertFalse(is_dummy_entry_name("ゼットカレン"))
        races = [
            {"entries": [{"name": "馬1", "number": 1}]},
            {"entries": [{"name": "ゼットカレン", "number": 4}, {"name": "ヒオウギ", "number": 2}]},
        ]
        kept = reject_dummy_races(races)
        self.assertEqual(len(kept), 1)

    def test_parse_official_shutuba_not_dummy(self):
        html = """
        20:00発走 /<span> ダ1200m
        <td class="Umaban1">1</td>
        <span class="HorseName"><a id="umalink_1">リオンセーラス</a></span>
        <td class="Popular Txt_C "><span>2</span></td>
        <tr class="HorseList"
        <td class="Umaban2">2</td>
        <span class="HorseName"><a id="umalink_2">イイデヒロイン</a></span>
        <td class="Popular Txt_C "><span>1</span></td>
        <tr class="HorseList"
        <td class="Umaban3">3</td>
        <span class="HorseName"><a id="umalink_3">エアプレイ</a></span>
        <td class="Popular Txt_C "><span>3</span></td>
        <tr class="HorseList"
        <td class="Umaban4">4</td>
        <span class="HorseName"><a id="umalink_4">メイショウマーブル</a></span>
        <td class="Popular Txt_C "><span>4</span></td>
        """
        parsed = parse_shutuba(html, "202630090211", "nar", {"2026300902": "門別"})
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["venue"], "門別")
        self.assertEqual(parsed["close_time"], "20:00")
        self.assertFalse(any(is_dummy_entry_name(e["name"]) for e in parsed["entries"]))
        self.assertEqual(len(parsed["entries"]), 4)

    def test_parse_kaisai_and_result(self):
        html = '<a href="?kaisai_id=2026300902&kaisai_date=20260902">門別</a>'
        self.assertEqual(parse_kaisai_venues(html)["2026300902"], "門別")
        result = parse_result_trifecta("3連単 1-5-3 12,340円")
        self.assertEqual(result["trifecta"], "1-5-3")
        self.assertEqual(result["payout"], 12340)

    def test_verify_drive_does_not_write_or_create(self):
        metas = {
            "1mUCUb2mti2RLoCvfJ-5TooghUZzETKTV": {
                "id": "1mUCUb2mti2RLoCvfJ-5TooghUZzETKTV",
                "name": "中央競馬_予想記入シート_2026年9月.xlsx",
                "size": "1",
                "trashed": False,
            },
            "16CG5ETf0X-vQHrRUn22w-QpOIREEkydJ": {
                "id": "16CG5ETf0X-vQHrRUn22w-QpOIREEkydJ",
                "name": "中央競馬_予想集計シート_2026年9月.xlsx",
                "size": "1",
                "trashed": False,
            },
            "1sbXJiVIM6EbYl399UWYmRY0OdP3uyZ6w": {
                "id": "1sbXJiVIM6EbYl399UWYmRY0OdP3uyZ6w",
                "name": "地方競馬_予想記入シート_2026年9月.xlsx",
                "size": "1",
                "trashed": False,
            },
            "1ItNNqAkG0pROupUh765tfASQhICkk7nQ": {
                "id": "1ItNNqAkG0pROupUh765tfASQhICkk7nQ",
                "name": "地方競馬_予想集計シート_2026年9月.xlsx",
                "size": "1",
                "trashed": False,
            },
            "10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5": {
                "id": "10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5",
                "name": "競艇_予想記入シート_2026年9月.xlsx",
                "size": "1",
                "trashed": False,
            },
            "1YCv2VU01kMiwN2RzV4PUpCvfdBhIIJvy": {
                "id": "1YCv2VU01kMiwN2RzV4PUpCvfdBhIIJvy",
                "name": "競艇_予想集計シート_2026年9月.xlsx",
                "size": "1",
                "trashed": False,
            },
        }

        def fake_meta(_token, file_id):
            return metas[file_id]

        with (
            patch.object(drive_sync, "_get_access_token", return_value="token"),
            patch.object(drive_sync, "_drive_get_metadata", side_effect=fake_meta),
            patch.object(drive_sync, "_drive_upload_replace") as mock_up,
            patch.object(drive_sync, "_drive_create") as mock_create,
        ):
            report = drive_sync.verify_excel_readable(ROOT)
            self.assertEqual(report.succeeded, 6)
            self.assertEqual(report.failed, 0)
            mock_up.assert_not_called()
            mock_create.assert_not_called()

    def test_excel_sync_never_creates(self):
        cfg = json.loads((ROOT / "config" / "drive_excel.json").read_text(encoding="utf-8"))
        cfg["files"]["kyotei_entry"]["drive_file_id"] = ""
        with (
            patch.object(drive_sync, "load_drive_config", return_value=cfg),
            patch.object(drive_sync, "_get_access_token", return_value="token"),
            patch.object(drive_sync, "_drive_create") as mock_create,
        ):
            report = drive_sync.sync_excel_files(ROOT, keys=["kyotei_entry"])
            self.assertEqual(report.failed, 1)
            self.assertIn("新規作成", report.results[0].message)
            mock_create.assert_not_called()

    @unittest.skipUnless(sys.platform != "win32", "fcntl lock is Unix")
    def test_lock_prevents_concurrent(self):
        import tempfile
        import shutil

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        with exclusive_lock(tmp):
            with self.assertRaises(CloudLockError):
                with exclusive_lock(tmp):
                    pass

    def test_record_fetch_failure_keeps_sports_separate(self):
        state = {"sport": "nar", "records": []}
        record_fetch_failure(state, date="2026-09-02", reason="取得失敗")
        self.assertEqual(state["fetch_failures"][0]["reason"], "取得失敗")
        self.assertEqual(state["sport"], "nar")

    def test_verify_drive_fails_when_one_file_unreadable(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "personal_workflow_verify", ROOT / "tools" / "workflow.py"
        )
        wf = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(wf)

        class BadReport:
            failed = 1
            succeeded = 5

        with (
            patch.object(wf, "run_verify_drive", side_effect=wf.CloudJobError("読めません")),
        ):
            code = wf.main(["verify-drive"])
        self.assertEqual(code, 1)

    def test_push_raises_on_drive_save_failure(self):
        from cloud_runner import CloudJobError, _push_excel

        class FailReport:
            failed = 1
            succeeded = 5

            def format_report(self):
                return "failed"

        import cloud_runner

        with patch.object(cloud_runner, "sync_excel_files", return_value=FailReport()):
            with self.assertRaises(CloudJobError):
                _push_excel(ROOT)

    def test_inbox_push_failure_does_not_fail_cloud_job(self):
        from cloud_runner import LEARNING_JSON_UNSAVED, run_cloud_predict
        from excel.drive_sync import DriveSyncReport, FileSyncResult
        from pathlib import Path
        import tempfile
        import shutil

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)

        class OkReport:
            failed = 0
            succeeded = 6

            def format_report(self):
                return "excel ok"

        fail = DriveSyncReport()
        fail.attempted = 1
        fail.failed = 1
        fail.results.append(
            FileSyncResult(
                key="jra:x",
                local_name="2026-09-03.predictions.json",
                local_path=tmp / "x.json",
                drive_file_id=None,
                status="failed",
                message="mock fail",
            )
        )

        import cloud_runner

        with (
            patch.object(cloud_runner, "pull_excel_files", return_value=OkReport()),
            patch.object(cloud_runner, "_push_excel", return_value="excel ok"),
            patch.object(cloud_runner, "push_inbox_for_date", return_value=fail),
            patch.object(cloud_runner, "push_learning_data") as mock_state,
        ):
            text = run_cloud_predict(
                tmp,
                target_date="2026-09-03",
                force=True,
                run_predict_today_fn=lambda *a, **k: "予想OK",
                run_predict_fn=lambda *a, **k: "予想OK",
            )
        self.assertIn("予想OK", text)
        self.assertIn(LEARNING_JSON_UNSAVED, text)
        mock_state.assert_not_called()

    def test_bootstrap_refuses_without_confirm_and_never_pulls(self):
        from cloud_runner import CloudJobError, run_bootstrap_cloud

        with (
            patch.object(drive_sync, "pull_excel_files") as mock_pull,
            patch.object(drive_sync, "sync_excel_files") as mock_sync,
        ):
            with self.assertRaises(CloudJobError):
                run_bootstrap_cloud(ROOT, confirm=False)
            mock_pull.assert_not_called()
            mock_sync.assert_not_called()

    def test_bootstrap_fails_without_local_state(self):
        import shutil
        import tempfile

        from cloud_runner import CloudJobError, run_bootstrap_cloud

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "config").mkdir()
        shutil.copy(ROOT / "config" / "drive_excel.json", tmp / "config" / "drive_excel.json")
        (tmp / "excel").mkdir()
        for name in (
            "中央競馬_予想記入シート_2026年9月.xlsx",
            "中央競馬_予想集計シート_2026年9月.xlsx",
            "地方競馬_予想記入シート_2026年9月.xlsx",
            "地方競馬_予想集計シート_2026年9月.xlsx",
            "競艇_予想記入シート_2026年9月.xlsx",
            "競艇_予想集計シート_2026年9月.xlsx",
        ):
            (tmp / "excel" / name).write_bytes(b"xlsx")

        with (
            patch.object(drive_sync, "pull_excel_files") as mock_pull,
            patch.object(drive_sync, "sync_excel_files") as mock_sync,
            patch.object(drive_sync, "push_learning_data") as mock_push,
        ):
            with self.assertRaises(CloudJobError) as ctx:
                run_bootstrap_cloud(tmp, confirm=True)
            self.assertIn("data/nar/state.json", str(ctx.exception))
            self.assertIn("成功扱いにしません", str(ctx.exception))
            mock_pull.assert_not_called()
            mock_sync.assert_not_called()
            mock_push.assert_not_called()

    def test_parse_official_result_html_jra_and_nar(self):
        jra_html = (
            '<tr class="Tan3"> <th>3連単</th> <td class="Result"> '
            "<ul> <li><span>1</span></li> <li><span>4</span></li> "
            '<li><span>7</span></li> </ul> </td> '
            '<td class="Payout"><span>21,300円</span></td>'
        )
        nar_html = (
            '<tr class="Tan3"> <th>3連単</th> <td  class="Result"> '
            "<ul> <li><span>6</span></li> <li><span>4</span></li> "
            '<li><span>10</span></li> </ul>   </td> '
            '<td class="Payout"><span>490円</span></td>'
        )
        jra = parse_result_trifecta(jra_html)
        nar = parse_result_trifecta(nar_html)
        self.assertEqual(jra["trifecta"], "1-4-7")
        self.assertEqual(jra["payout"], 21300)
        self.assertEqual(nar["trifecta"], "6-4-10")
        self.assertEqual(nar["payout"], 490)

    def test_official_trifecta_with_10_is_not_a_hit(self):
        from common.tickets import check_hit

        self.assertFalse(
            check_hit("6-4-10", [{"type": "本線", "pick": "6-4-123"}])
        )


if __name__ == "__main__":
    unittest.main()
