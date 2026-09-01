"""正式な初回state初期化。本番 data / Excel / Drive には書かない。"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_fixtures import (  # noqa: E402
    PRODUCTION_ROOT,
    ProductionDataGuardMixin,
    is_under_production_data,
    make_sandbox,
    snapshot_tree,
    write_canonical_states,
)

from common.constants import DEFAULT_START_DATE, SPORTS, STATE_TIMEZONE, STATE_VERSION  # noqa: E402
from common.state import (  # noqa: E402
    canonical_state_problems,
    get_start_date,
    init_personal_states,
    is_before_start_date,
    is_canonical_state,
    load_json,
    new_state,
    records_since_start,
    save_json,
)
from common.tickets import ValidationError  # noqa: E402
from cloud_runner import CloudJobError, run_bootstrap_cloud  # noqa: E402
from orchestrator import run_predict_today, run_results_yesterday  # noqa: E402
import cloud_runner  # noqa: E402

ROOT = PRODUCTION_ROOT
WORKFLOW_PATH = ROOT / "tools" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("personal_workflow_init", WORKFLOW_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

START = DEFAULT_START_DATE
BEFORE = "2026-09-02"
EXCEL_NAMES = (
    "中央競馬_予想記入シート_2026年9月.xlsx",
    "中央競馬_予想集計シート_2026年9月.xlsx",
    "地方競馬_予想記入シート_2026年9月.xlsx",
    "地方競馬_予想集計シート_2026年9月.xlsx",
    "競艇_予想記入シート_2026年9月.xlsx",
    "競艇_予想集計シート_2026年9月.xlsx",
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _completed_record(date: str, *, sport: str = "jra", hit: bool = True) -> dict:
    return {
        "date": date,
        "sport": sport,
        "venue": "東京",
        "race": 11,
        "number": 1,
        "prediction_score": 70,
        "confidence": "B",
        "ticket_count": 4,
        "tickets": [{"type": "本線", "pick": "1-2-3"}],
        "score_breakdown": {"recent_form": 10},
        "result": {
            "status": "的中" if hit else "ハズレ",
            "stake": 400,
            "payout": 1200 if hit else 0,
            "trifecta": "1-2-3",
        },
    }


class InitStateTest(ProductionDataGuardMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="personal-init-state-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.assertFalse(is_under_production_data(self.tmp / "data"))
        self._orig_root = workflow.ROOT
        workflow.ROOT = self.tmp
        self.addCleanup(setattr, workflow, "ROOT", self._orig_root)

    def test_init_three_sports_success(self):
        report = init_personal_states(self.tmp, start_date=START, confirm=True)
        self.assertIn(START, report)
        self.assertIn(STATE_TIMEZONE, report)
        for sport in SPORTS:
            path = self.tmp / "data" / sport / "state.json"
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(is_canonical_state(data, sport))
            self.assertEqual(data["version"], STATE_VERSION)
            self.assertEqual(data["sport"], sport)
            self.assertEqual(data["start_date"], START)
            self.assertEqual(data["timezone"], STATE_TIMEZONE)
            self.assertEqual(data["records"], [])
            self.assertEqual(data["processed"], {})
            self.assertEqual(data["fetch_failures"], [])
            self.assertNotIn("sample", json.dumps(data))
            self.assertNotIn("test_fixture", json.dumps(data))
        self.assertEqual(canonical_state_problems(self.tmp), [])

    def test_reinit_is_refused_and_does_not_overwrite(self):
        init_personal_states(self.tmp, start_date=START, confirm=True)
        before = {
            sport: _file_hash(self.tmp / "data" / sport / "state.json") for sport in SPORTS
        }
        with self.assertRaises(ValidationError) as ctx:
            init_personal_states(self.tmp, start_date=START, confirm=True)
        self.assertIn("上書きしません", str(ctx.exception))
        after = {
            sport: _file_hash(self.tmp / "data" / sport / "state.json") for sport in SPORTS
        }
        self.assertEqual(before, after)

    def test_confirm_flag_required(self):
        with self.assertRaises(ValidationError) as ctx:
            init_personal_states(self.tmp, start_date=START, confirm=False)
        self.assertIn("--i-confirm-init-state", str(ctx.exception))
        for sport in SPORTS:
            self.assertFalse((self.tmp / "data" / sport / "state.json").exists())

    def test_cli_without_confirm_does_not_write(self):
        code = workflow.main(["init-state", "--start-date", START])
        self.assertEqual(code, 1)
        for sport in SPORTS:
            self.assertFalse((self.tmp / "data" / sport / "state.json").exists())

    def test_cli_official_command_writes_only_tmp(self):
        code = workflow.main(
            ["init-state", "--start-date", START, "--i-confirm-init-state"]
        )
        self.assertEqual(code, 0)
        for sport in SPORTS:
            data = load_json(self.tmp / "data" / sport / "state.json")
            self.assertTrue(is_canonical_state(data, sport))
        self.assertFalse(is_under_production_data(self.tmp / "data"))

    def test_existing_one_sport_refuses_all(self):
        jra = self.tmp / "data" / "jra" / "state.json"
        save_json(jra, new_state("jra", START))
        before = _file_hash(jra)
        with self.assertRaises(ValidationError) as ctx:
            init_personal_states(self.tmp, start_date=START, confirm=True)
        self.assertIn("data/jra/state.json", str(ctx.exception))
        self.assertEqual(before, _file_hash(jra))
        self.assertFalse((self.tmp / "data" / "nar" / "state.json").exists())
        self.assertFalse((self.tmp / "data" / "kyotei" / "state.json").exists())

    def test_init_does_not_use_examples_or_change_excel(self):
        sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, sandbox, True)
        examples_before = snapshot_tree(ROOT / "examples")
        excel_before = snapshot_tree(sandbox / "excel")
        init_personal_states(sandbox, start_date=START, confirm=True)
        self.assertEqual(snapshot_tree(ROOT / "examples"), examples_before)
        self.assertEqual(snapshot_tree(sandbox / "excel"), excel_before)
        src = inspect.getsource(init_personal_states)
        self.assertNotIn("examples/", src)
        self.assertNotIn("sample.json", src)
        self.assertNotIn("test_fixture", src)
        self.assertNotIn("service_account", src)
        self.assertNotIn("GOOGLE_DRIVE", src)

    def test_sept2_results_and_predict_are_excluded(self):
        sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, sandbox, True)
        init_personal_states(sandbox, start_date=START, confirm=True)
        workflow.ROOT = sandbox
        pending = {
            "date": BEFORE,
            "sport": "jra",
            "venue": "東京",
            "race": 11,
            "number": 1,
            "tickets": [{"type": "本線", "pick": "1-2-3"}],
            "ticket_count": 1,
        }
        state = load_json(sandbox / "data" / "jra" / "state.json")
        state["records"] = [pending]
        save_json(sandbox / "data" / "jra" / "state.json", state)
        excel_before = snapshot_tree(sandbox / "excel")
        state_before = _file_hash(sandbox / "data" / "jra" / "state.json")

        with (
            patch.object(
                workflow.fetch_jra,
                "fetch_races_outcome",
                side_effect=AssertionError("予想取得してはいけない"),
            ),
            patch.object(
                workflow,
                "ensure_result_data",
                side_effect=AssertionError("結果取得してはいけない"),
            ),
            patch(
                "orchestrator.ensure_result_data",
                side_effect=AssertionError("結果取得してはいけない"),
            ),
            patch(
                "orchestrator.ensure_race_data",
                side_effect=AssertionError("出走取得してはいけない"),
            ),
            patch(
                "orchestrator.fetch_keiba_results",
                side_effect=AssertionError("結果取得してはいけない"),
            ),
        ):
            predict = workflow.run_predict("jra", BEFORE, force=True, sync_drive=False)
            results = workflow.run_results("jra", BEFORE, force=True, sync_drive=False)
            applied = workflow.apply_results_from_file(
                "jra", BEFORE, ROOT / "examples" / "jra_results.sample.json", sync_drive=False
            )
            pred_today = run_predict_today(
                sandbox, target_date=BEFORE, force=True, run_predict_fn=workflow.run_predict
            )
            yest = run_results_yesterday(
                sandbox,
                target_date=BEFORE,
                force=True,
                apply_results_fn=workflow.apply_results_from_file,
                run_results_fn=workflow.run_results,
                run_learning_fn=workflow.run_learning_report,
                find_day_records_fn=workflow.find_day_records,
                load_state_fn=lambda sport: load_json(
                    sandbox / "data" / sport / "state.json"
                ),
            )

        self.assertIn("対象外", predict)
        self.assertIn("対象外", results)
        self.assertIn("対象外", applied)
        self.assertIn("対象外", pred_today)
        self.assertIn("対象外", yest)
        self.assertIn("Excelは変更していません", results)
        self.assertEqual(snapshot_tree(sandbox / "excel"), excel_before)
        self.assertEqual(_file_hash(sandbox / "data" / "jra" / "state.json"), state_before)

    def test_sept2_learning_excluded_sept3_included(self):
        sandbox = make_sandbox(ROOT, copy_excel=False)
        self.addCleanup(shutil.rmtree, sandbox, True)
        init_personal_states(sandbox, start_date=START, confirm=True)
        state = load_json(sandbox / "data" / "jra" / "state.json")
        state["records"] = [
            _completed_record(BEFORE, hit=True),
            _completed_record(START, hit=False),
        ]
        save_json(sandbox / "data" / "jra" / "state.json", state)
        kept = records_since_start(state, with_result=True)
        self.assertEqual([r["date"] for r in kept], [START])
        workflow.ROOT = sandbox
        text = workflow.run_learning_report("jra")
        report = json.loads(
            (sandbox / "data" / "jra" / "learning_report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["race_count"], 1)
        self.assertIn("100レースまでの残り", text)

    def test_sept3_normal_predict_results_learning(self):
        sandbox = make_sandbox(ROOT, copy_excel=True)
        self.addCleanup(shutil.rmtree, sandbox, True)
        init_personal_states(sandbox, start_date=START, confirm=True)
        workflow.ROOT = sandbox
        report = workflow.run_predict(
            "jra",
            START,
            force=True,
            sync_drive=False,
            allow_sample=True,
            try_auto=False,
        )
        self.assertIn("中央競馬", report)
        self.assertNotIn("対象外", report)
        applied = workflow.apply_results_from_file(
            "jra", START, ROOT / "examples" / "jra_results.sample.json", sync_drive=False
        )
        self.assertIn("結果報告", applied)
        learn = workflow.run_learning_report("jra")
        self.assertIn("100レースまでの残り", learn)
        state = load_json(sandbox / "data" / "jra" / "state.json")
        selected = [r for r in state["records"] if r.get("date") == START and r.get("tickets")]
        self.assertGreaterEqual(len(selected), 1)
        self.assertTrue(any(r.get("review") for r in selected))

    def test_missing_start_date_falls_back_to_default(self):
        state = {"version": 2, "sport": "nar", "records": [], "processed": {}}
        self.assertEqual(get_start_date(state), START)
        self.assertTrue(is_before_start_date(state, BEFORE))
        self.assertTrue(is_before_start_date(state, "2026-09-01"))
        self.assertFalse(is_before_start_date(state, START))
        self.assertFalse(is_before_start_date(state, "2026-09-04"))

    def test_sample_payload_is_not_canonical(self):
        self.assertFalse(
            is_canonical_state({"version": 2, "sport": "jra", "source": "sample"}, "jra")
        )
        self.assertFalse(
            is_canonical_state(
                {
                    "version": 2,
                    "sport": "jra",
                    "start_date": START,
                    "timezone": STATE_TIMEZONE,
                    "records": [],
                    "processed": {},
                    "source": "test_fixture",
                },
                "jra",
            )
        )
        self.assertFalse(is_canonical_state(new_state("jra", START), "nar"))

    def test_bootstrap_requires_three_canonical_states(self):
        (self.tmp / "config").mkdir()
        shutil.copy(ROOT / "config" / "drive_excel.json", self.tmp / "config" / "drive_excel.json")
        (self.tmp / "excel").mkdir()
        for name in EXCEL_NAMES:
            (self.tmp / "excel" / name).write_bytes(b"xlsx")

        class OkReport:
            failed = 0
            succeeded = 6
            results: list = []

            def format_report(self):
                return "ok"

        with (
            patch.object(cloud_runner, "pull_excel_files") as mock_pull,
            patch.object(cloud_runner, "sync_excel_files") as mock_sync,
            patch.object(cloud_runner, "push_learning_data") as mock_push,
        ):
            with self.assertRaises(CloudJobError) as ctx:
                run_bootstrap_cloud(self.tmp, confirm=True)
            self.assertIn("data/jra/state.json", str(ctx.exception))
            self.assertIn("成功扱いにしません", str(ctx.exception))
            mock_pull.assert_not_called()
            mock_sync.assert_not_called()
            mock_push.assert_not_called()

        write_canonical_states(self.tmp, start_date="2026-09-01")
        jra = json.loads((self.tmp / "data" / "jra" / "state.json").read_text(encoding="utf-8"))
        del jra["start_date"]
        (self.tmp / "data" / "jra" / "state.json").write_text(
            json.dumps(jra, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with (
            patch.object(cloud_runner, "sync_excel_files") as mock_sync,
            patch.object(cloud_runner, "push_learning_data") as mock_push,
        ):
            with self.assertRaises(CloudJobError) as ctx:
                run_bootstrap_cloud(self.tmp, confirm=True)
            self.assertIn("正規stateではない", str(ctx.exception))
            mock_sync.assert_not_called()
            mock_push.assert_not_called()

        shutil.rmtree(self.tmp / "data")
        init_personal_states(self.tmp, start_date=START, confirm=True)
        with (
            patch.object(cloud_runner, "pull_excel_files") as mock_pull,
            patch.object(cloud_runner, "sync_excel_files", return_value=OkReport()),
            patch.object(cloud_runner, "push_learning_data", return_value=OkReport()),
        ):
            text = run_bootstrap_cloud(self.tmp, confirm=True)
        self.assertIn("初期移行", text)
        mock_pull.assert_not_called()

    def test_workflow_yml_keeps_schedule_off_without_switch(self):
        text = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows" / "personal-predict.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("PERSONAL_PREDICT_ENABLED", text)
        self.assertIn(
            "steps.gate.outputs.enabled == 'true' && steps.decide.outputs.job == 'results-yesterday'",
            text,
        )
        self.assertIn(
            "steps.gate.outputs.enabled == 'true' && steps.decide.outputs.job == 'predict-today'",
            text,
        )
        self.assertNotIn("init-state", text)
        self.assertNotIn("競輪予想", text)
        self.assertNotIn("chatwork", text.lower())


if __name__ == "__main__":
    unittest.main()
