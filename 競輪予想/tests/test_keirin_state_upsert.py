import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "keirin_workflow.py"
SPEC = importlib.util.spec_from_file_location("keirin_workflow_state", MODULE_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _old_format_state() -> dict:
    return {
        "version": 1,
        "days": [
            {
                "date": "2099-01-01",
                "low_quality_day": False,
                "candidates": [
                    {
                        "venue": "テスト競輪場A",
                        "race": 7,
                        "close_time": "18:20",
                        "prediction_score": 85,
                        "score_breakdown": {
                            "axis_reliability": 18,
                            "line_clarity": 13,
                            "ability_gap": 13,
                            "scenario_simplicity": 13,
                            "recent_form": 13,
                            "track_style_fit": 9,
                            "risk_absence": 8,
                        },
                        "penalties": [{"code": "other", "points": 2}],
                        "selected": True,
                        "selection_rank": 1,
                    },
                    {
                        "venue": "テスト競輪場B",
                        "race": 10,
                        "close_time": "19:30",
                        "prediction_score": 78,
                        "score_breakdown": {
                            "axis_reliability": 17,
                            "line_clarity": 12,
                            "ability_gap": 12,
                            "scenario_simplicity": 12,
                            "recent_form": 12,
                            "track_style_fit": 8,
                            "risk_absence": 8,
                        },
                        "penalties": [{"code": "evenly_matched", "points": 3}],
                        "selected": True,
                        "selection_rank": 2,
                    },
                    {
                        "venue": "テスト競輪場C",
                        "race": 12,
                        "close_time": "20:15",
                        "prediction_score": 72,
                        "score_breakdown": {
                            "axis_reliability": 16,
                            "line_clarity": 11,
                            "ability_gap": 11,
                            "scenario_simplicity": 11,
                            "recent_form": 11,
                            "track_style_fit": 8,
                            "risk_absence": 7,
                        },
                        "penalties": [{"code": "fragmented_race", "points": 3}],
                        "selected": True,
                        "selection_rank": 3,
                    },
                ],
                "predictions": [
                    {
                        "number": 1,
                        "venue": "テスト競輪場A",
                        "race": 7,
                        "target": "鉄板",
                        "confidence": "A",
                        "prediction_score": 85,
                        "score_breakdown": {
                            "axis_reliability": 18,
                            "line_clarity": 13,
                            "ability_gap": 13,
                            "scenario_simplicity": 13,
                            "recent_form": 13,
                            "track_style_fit": 9,
                            "risk_absence": 8,
                        },
                        "penalties": [{"code": "other", "points": 2}],
                        "first_place_candidate_count": 1,
                        "ticket_count": 5,
                        "result": {
                            "status": "的中",
                            "stake": 500,
                            "payout": 720,
                            "primary_miss_reason": None,
                            "secondary_miss_reasons": [],
                        },
                    },
                    {
                        "number": 2,
                        "venue": "テスト競輪場B",
                        "race": 10,
                        "target": "鉄板",
                        "confidence": "B",
                        "prediction_score": 78,
                        "score_breakdown": {
                            "axis_reliability": 17,
                            "line_clarity": 12,
                            "ability_gap": 12,
                            "scenario_simplicity": 12,
                            "recent_form": 12,
                            "track_style_fit": 8,
                            "risk_absence": 8,
                        },
                        "penalties": [{"code": "evenly_matched", "points": 3}],
                        "first_place_candidate_count": 2,
                        "ticket_count": 5,
                        "result": {
                            "status": "ハズレ",
                            "stake": 500,
                            "payout": 0,
                            "primary_miss_reason": "axis_miss",
                            "secondary_miss_reasons": ["line_collapse"],
                        },
                    },
                    {
                        "number": 3,
                        "venue": "テスト競輪場C",
                        "race": 12,
                        "target": "中穴",
                        "confidence": "B",
                        "prediction_score": 72,
                        "score_breakdown": {
                            "axis_reliability": 16,
                            "line_clarity": 11,
                            "ability_gap": 11,
                            "scenario_simplicity": 11,
                            "recent_form": 11,
                            "track_style_fit": 8,
                            "risk_absence": 7,
                        },
                        "penalties": [{"code": "fragmented_race", "points": 3}],
                        "first_place_candidate_count": 1,
                        "ticket_count": 5,
                        "result": {
                            "status": "的中",
                            "stake": 500,
                            "payout": 1240,
                            "primary_miss_reason": None,
                            "secondary_miss_reasons": [],
                        },
                    },
                ],
            }
        ],
    }


class KeirinStateUpsertTest(unittest.TestCase):
    def setUp(self):
        self.day = json.loads((ROOT / "examples" / "day_predictions.example.json").read_text(encoding="utf-8"))
        self.results = json.loads((ROOT / "examples" / "results.example.json").read_text(encoding="utf-8"))

    def test_default_state_path_is_not_example(self):
        path = workflow.default_state_path()
        self.assertEqual(path.name, "state.json")
        self.assertEqual(path.parent.name, "state")
        self.assertNotEqual(path.name, "state.example.json")

    def test_extract_axis_from_main_line(self):
        self.assertEqual(
            workflow.extract_axis(
                [{"type": "本線", "pick": "1-2-345"}, {"type": "抑え", "pick": "2-1-34"}]
            ),
            "1",
        )

    def test_extract_axis_rejects_missing_or_ambiguous_main(self):
        with self.assertRaises(workflow.ValidationError):
            workflow.extract_axis([{"type": "抑え", "pick": "2-1-34"}])
        with self.assertRaises(workflow.ValidationError):
            workflow.extract_axis(
                [
                    {"type": "本線", "pick": "1-2-345"},
                    {"type": "本線", "pick": "2-1-345"},
                ]
            )

    def test_close_miss_definition(self):
        tickets = [
            {"type": "本線", "pick": "1-2-345"},
            {"type": "抑え", "pick": "2-1-34"},
        ]
        self.assertFalse(
            workflow.compute_close_miss(status="的中", axis="1", tickets=tickets, trifecta="1-2-3")
        )
        self.assertTrue(
            workflow.compute_close_miss(status="ハズレ", axis="1", tickets=tickets, trifecta="1-7-3")
        )
        self.assertTrue(
            workflow.compute_close_miss(status="ハズレ", axis="1", tickets=tickets, trifecta="1-2-7")
        )
        self.assertFalse(
            workflow.compute_close_miss(status="ハズレ", axis="1", tickets=tickets, trifecta="1-7-2")
        )
        self.assertFalse(
            workflow.compute_close_miss(status="ハズレ", axis="1", tickets=tickets, trifecta="7-2-1")
        )

    def test_record_predictions_writes_axis_and_tickets(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["days"]), 1)
            preds = saved["days"][0]["predictions"]
            self.assertEqual(len(preds), 3)
            self.assertEqual(preds[0]["axis"], "1")
            self.assertEqual(preds[1]["axis"], "3")
            self.assertEqual(preds[2]["axis"], "5")
            self.assertTrue(preds[0]["tickets"])
            self.assertIsNone(preds[0]["result"])
            self.assertNotIn("explanation", preds[0])
            self.assertFalse(saved["days"][0]["low_quality_day"])
            self.assertEqual(saved["days"][0]["candidates"][0]["selection_rank"], 1)
            completed = workflow.validate_state(saved)
            self.assertEqual(len(completed), 0)

    def test_record_predictions_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            workflow.record_predictions(self.day, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["days"]), 1)
            self.assertEqual(len(saved["days"][0]["predictions"]), 3)

    def test_record_results_upserts_same_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            workflow.record_results(self.results, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["days"]), 1)
            preds = saved["days"][0]["predictions"]
            self.assertEqual(preds[0]["result"]["status"], "的中")
            self.assertFalse(preds[0]["result"]["close_miss"])
            self.assertEqual(preds[1]["result"]["primary_miss_reason"], "axis_miss")
            self.assertEqual(preds[1]["result"]["secondary_miss_reasons"], ["line_collapse"])
            self.assertFalse(preds[1]["result"]["close_miss"])
            self.assertEqual(preds[1]["result"]["trifecta"], "7-2-1")
            self.assertEqual(preds[0]["result"]["stake"], 500)
            completed = workflow.validate_state(saved)
            self.assertEqual(len(completed), 3)

    def test_record_results_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            workflow.record_results(self.results, state_path)
            workflow.record_results(self.results, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["days"]), 1)
            self.assertEqual(len(saved["days"][0]["predictions"]), 3)

    def test_rerun_predictions_keeps_existing_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            workflow.record_results(self.results, state_path)
            workflow.record_predictions(self.day, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["days"][0]["predictions"][1]["result"]["status"], "ハズレ")
            self.assertEqual(saved["days"][0]["predictions"][1]["result"]["trifecta"], "7-2-1")

    def test_record_results_without_predictions_fails_and_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with self.assertRaises(workflow.ValidationError):
                workflow.record_results(self.results, state_path)
            self.assertFalse(state_path.exists())

    def test_corrupt_state_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("{not-json", encoding="utf-8")
            before = state_path.read_bytes()
            with self.assertRaises(workflow.ValidationError):
                workflow.record_predictions(self.day, state_path)
            self.assertEqual(state_path.read_bytes(), before)

    def test_invalid_input_keeps_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            before = _sha256(state_path)
            broken = copy.deepcopy(self.day)
            del broken["predictions"][0]["prediction_score"]
            with self.assertRaises(workflow.ValidationError):
                workflow.record_predictions(broken, state_path)
            self.assertEqual(_sha256(state_path), before)
            self.assertFalse(state_path.with_name("state.json.writing").exists())

    def test_failed_save_keeps_old_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            before = _sha256(state_path)
            with mock.patch.object(workflow, "save_state_atomic", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    workflow.record_predictions(self.day, state_path)
            self.assertEqual(_sha256(state_path), before)

    def test_old_format_state_still_validates(self):
        completed = workflow.validate_state(_old_format_state())
        self.assertEqual(len(completed), 3)
        self.assertNotIn("axis", completed[0])
        self.assertNotIn("close_miss", completed[0]["result"])

    def test_record_results_rejects_old_record_without_tickets(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.save_state_atomic(state_path, _old_format_state())
            before = _sha256(state_path)
            with self.assertRaises(workflow.ValidationError):
                workflow.record_results(self.results, state_path)
            self.assertEqual(_sha256(state_path), before)

    def test_learning_report_counts_only_completed_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            pending = json.loads(state_path.read_text(encoding="utf-8"))
            pending_report = workflow.build_learning_report(pending)
            self.assertEqual(pending_report["overall"]["n"], 0)
            workflow.record_results(self.results, state_path)
            done = json.loads(state_path.read_text(encoding="utf-8"))
            report = workflow.build_learning_report(done)
            self.assertEqual(report["overall"]["n"], 3)
            self.assertEqual(report["overall"]["hits"], 2)

    def test_close_miss_saved_on_near_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            workflow.record_predictions(self.day, state_path)
            near = copy.deepcopy(self.results)
            near["results"][0] = {
                "number": 1,
                "trifecta": "1-7-3",
                "payout": 0,
                "status": "ハズレ",
                "points": 5,
                "primary_miss_reason": "second_place_miss",
                "secondary_miss_reasons": [],
            }
            workflow.record_results(near, state_path)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertTrue(saved["days"][0]["predictions"][0]["result"]["close_miss"])

    def test_cli_record_commands_use_explicit_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            pred_file = ROOT / "examples" / "day_predictions.example.json"
            result_file = ROOT / "examples" / "results.example.json"
            code1 = workflow.main(
                ["record-predictions", str(pred_file), "--state", str(state_path)]
            )
            code2 = workflow.main(
                ["record-results", str(result_file), "--state", str(state_path)]
            )
            self.assertEqual(code1, 0)
            self.assertEqual(code2, 0)
            self.assertTrue(state_path.exists())
            production = workflow.default_state_path()
            self.assertNotEqual(state_path.resolve(), production.resolve())

    def test_example_state_with_new_fields_is_valid(self):
        data = json.loads((ROOT / "state" / "state.example.json").read_text(encoding="utf-8"))
        completed = workflow.validate_state(data)
        self.assertEqual(len(completed), 3)
        self.assertEqual(completed[0]["axis"], "1")
        self.assertFalse(completed[0]["result"]["close_miss"])


if __name__ == "__main__":
    unittest.main()
