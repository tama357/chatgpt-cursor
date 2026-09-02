import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "keirin_workflow.py"
SPEC = importlib.util.spec_from_file_location("keirin_workflow", MODULE_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)


GOLDEN_CHATWORK = "\n".join(
    [
        "【予想1】",
        "",
        "狙い：鉄板",
        "自信度：A",
        "",
        "テスト競輪場7R 締切時刻18:20",
        "",
        "●本線",
        "1-2-345 　3点",
        "",
        "●抑え",
        "2-1-34 　2点",
        "",
        "計5点",
        "",
        "●解説",
        "テスト用の架空データです。実際の予想には使用しません。",
        "",
        "【予想2】",
        "",
        "狙い：鉄板",
        "自信度：B",
        "",
        "テスト競輪場10R 締切時刻19:30",
        "",
        "●本線",
        "3-4-125 　3点",
        "",
        "●抑え",
        "4-3-12 　2点",
        "",
        "計5点",
        "",
        "●解説",
        "テスト用の架空データです。実際の予想には使用しません。",
        "",
        "【予想3】",
        "",
        "狙い：中穴",
        "自信度：B",
        "",
        "テスト競輪場12R 締切時刻20:15",
        "",
        "●本線",
        "5-6-123 　3点",
        "",
        "●抑え",
        "6-5-12 　2点",
        "",
        "計5点",
        "",
        "●解説",
        "テスト用の架空データです。実際の予想には使用しません。",
    ]
)

LEARNING_LEAK_TERMS = (
    "prediction_score",
    "score_breakdown",
    "penalties",
    "close_miss",
    "primary_miss_reason",
    "secondary_miss_reasons",
    "low_quality_day",
    "axis_reliability",
    "line_clarity",
    "ability_gap",
    "scenario_simplicity",
    "recent_form",
    "track_style_fit",
    "risk_absence",
    "first_place_candidate_count",
    "selection_rank",
)


class KeirinWorkflowTest(unittest.TestCase):
    def load_predictions(self):
        with (ROOT / "examples" / "predictions.example.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    def load_state(self):
        with (ROOT / "state" / "state.example.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_expand_pick(self):
        self.assertEqual(
            workflow.expand_pick("7-3-1456"),
            ("7-3-1", "7-3-4", "7-3-5", "7-3-6"),
        )

    def test_example_is_valid(self):
        expanded = workflow.validate_predictions(self.load_predictions())
        self.assertEqual([sum(len(ticket.combinations) for ticket in group) for group in expanded], [5, 5, 5])

    def test_rejects_close_time_before_18(self):
        data = self.load_predictions()
        data["predictions"][0]["close_time"] = "17:59"
        with self.assertRaises(workflow.ValidationError):
            workflow.validate_predictions(data)

    def test_rejects_more_than_ten_combinations(self):
        data = self.load_predictions()
        data["predictions"][0]["tickets"] = [
            {"type": "本線", "pick": "1-2-3456789"},
            {"type": "抑え", "pick": "2-1-34567"},
        ]
        with self.assertRaises(workflow.ValidationError):
            workflow.validate_predictions(data)

    def test_rejects_duplicate_expanded_combination(self):
        data = self.load_predictions()
        data["predictions"][0]["tickets"].append({"type": "抑え", "pick": "1-2-3"})
        with self.assertRaises(workflow.ValidationError):
            workflow.validate_predictions(data)

    def test_formats_chatwork_message(self):
        message = workflow.format_predictions(self.load_predictions())
        self.assertEqual(message, GOLDEN_CHATWORK)
        self.assertIn("【予想1】", message)
        self.assertIn("計5点", message)
        self.assertEqual(message.count("【予想"), 3)
        self.assertNotIn("prediction_score", message)
        self.assertNotIn("penalties", message)
        self.assertNotIn("axis", message)
        for term in LEARNING_LEAK_TERMS:
            self.assertNotIn(term, message)

    def test_send_predictions_uses_unchanged_format_and_does_not_send_without_confirm(self):
        pred_path = ROOT / "examples" / "predictions.example.json"
        with mock.patch.object(workflow, "format_predictions", wraps=workflow.format_predictions) as fmt:
            with mock.patch.object(workflow, "send_chatwork") as send:
                code = workflow.main(["send-predictions", str(pred_path)])
        self.assertEqual(code, 1)
        fmt.assert_called_once()
        send.assert_not_called()
        self.assertEqual(workflow.format_predictions(self.load_predictions()), GOLDEN_CHATWORK)

    def test_record_predictions_does_not_touch_chatwork(self):
        import tempfile

        data = json.loads((ROOT / "examples" / "day_predictions.example.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with mock.patch.object(workflow, "format_predictions") as fmt:
                with mock.patch.object(workflow, "send_chatwork") as send:
                    workflow.record_predictions(data, state_path)
            fmt.assert_not_called()
            send.assert_not_called()
        self.assertEqual(workflow.format_predictions(self.load_predictions()), GOLDEN_CHATWORK)

    def test_example_results_are_valid(self):
        with (ROOT / "examples" / "results.example.json").open(encoding="utf-8") as handle:
            results = json.load(handle)
        workflow.validate_results(results)
        report = workflow.format_results(results)
        self.assertIn("当日的中率：66.67%", report)
        self.assertIn("当日回収率：130.67%", report)

    def test_internal_state_example_is_valid(self):
        completed = workflow.validate_state(self.load_state())
        self.assertEqual(len(completed), 3)

    def test_prediction_score_and_confidence_are_independent(self):
        data = self.load_state()
        data["days"][0]["predictions"][0]["confidence"] = "C"
        completed = workflow.validate_state(data)
        self.assertEqual(completed[0]["prediction_score"], 85)
        self.assertEqual(completed[0]["confidence"], "C")

    def test_rejects_incorrect_prediction_score(self):
        data = self.load_state()
        data["days"][0]["candidates"][0]["prediction_score"] = 84
        with self.assertRaises(workflow.ValidationError):
            workflow.validate_state(data)

    def test_rejects_incorrect_low_quality_day(self):
        data = self.load_state()
        data["days"][0]["low_quality_day"] = True
        with self.assertRaises(workflow.ValidationError):
            workflow.validate_state(data)

    def test_rejects_missing_primary_miss_reason(self):
        data = self.load_state()
        result = data["days"][0]["predictions"][1]["result"]
        result["primary_miss_reason"] = None
        with self.assertRaises(workflow.ValidationError):
            workflow.validate_state(data)

    def test_learning_report_contains_requested_dimensions(self):
        report = workflow.build_learning_report(self.load_state())
        self.assertIn("prediction_score_band_performance", report)
        self.assertIn("low_quality_day_performance", report)
        self.assertIn("scoring_item_relationships", report)
        self.assertIn("first_place_candidate_count_performance", report)
        self.assertIn("ticket_count_performance", report)
        self.assertEqual(report["miss_reason_summary"]["axis_miss"]["primary_count"], 1)
        self.assertEqual(report["miss_reason_summary"]["axis_miss"]["loss_amount"], 500)

    def test_recommended_weights_are_proposal_only(self):
        report = workflow.build_learning_report(self.load_state())
        recommendation = report["recommended_weights"]
        self.assertFalse(recommendation["auto_applied"])
        self.assertFalse(report["weights_auto_applied"])
        self.assertEqual(sum(recommendation["weights"].values()), 100)
        self.assertEqual(report["initial_weights"], workflow.load_rules()["scoring_rubric"]["initial_weights"])


if __name__ == "__main__":
    unittest.main()
