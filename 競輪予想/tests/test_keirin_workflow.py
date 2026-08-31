import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "keirin_workflow.py"
SPEC = importlib.util.spec_from_file_location("keirin_workflow", MODULE_PATH)
workflow = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)


class KeirinWorkflowTest(unittest.TestCase):
    def load_predictions(self):
        with (ROOT / "examples" / "predictions.example.json").open(encoding="utf-8") as handle:
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
        self.assertIn("【予想1】", message)
        self.assertIn("計5点", message)
        self.assertEqual(message.count("【予想"), 3)

    def test_example_results_are_valid(self):
        with (ROOT / "examples" / "results.example.json").open(encoding="utf-8") as handle:
            results = json.load(handle)
        workflow.validate_results(results)
        report = workflow.format_results(results)
        self.assertIn("当日的中率：66.67%", report)
        self.assertIn("当日回収率：130.67%", report)


if __name__ == "__main__":
    unittest.main()
