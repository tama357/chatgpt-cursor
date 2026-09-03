import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load("keirin_workflow", TOOLS / "keirin_workflow.py")
flow = _load("keirin_cursor_flow", TOOLS / "keirin_cursor_flow.py")
chatgpt_io = _load("keirin_chatgpt_io", TOOLS / "keirin_chatgpt_io.py")
first = _load("keirin_first_prediction", TOOLS / "keirin_first_prediction.py")
sheets = _load("keirin_sheets", TOOLS / "keirin_sheets.py")
submission = _load("keirin_submission_state", TOOLS / "keirin_submission_state.py")


def _riders(*rows: tuple) -> list[dict]:
    out = []
    for number, style, kyuhan, firsts in rows:
        out.append(
            {
                "number": number,
                "name": f"選手{number}",
                "winning_style": style,
                "kyuhan": kyuhan,
                "recent_results": {"first": firsts, "second": 1, "third": 1, "out": 6},
            }
        )
    return out


class KeirinFirstPredictionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data" / "inbox").mkdir(parents=True)
        (self.root / "current_rules.json").write_text(
            (ROOT / "current_rules.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_does_not_pick_top_three_by_score(self):
        candidates = [
            {
                "venue": "割れ場",
                "race_number": 12,
                "deadline": "20:00",
                "prediction_score": 90,
                "score_breakdown": {"axis_reliability": 10, "scenario_simplicity": 6, "line_clarity": 6, "ability_gap": 5},
                "penalties": [{"code": "fragmented_race", "points": 3}],
                "riders": _riders((1, "逃", "S1", 3), (2, "逃", "S2", 3), (3, "逃", "A1", 2), (4, "追", "A2", 1)),
            },
            {
                "venue": "本線場",
                "race_number": 7,
                "deadline": "18:20",
                "prediction_score": 85,
                "score_breakdown": {"axis_reliability": 18, "scenario_simplicity": 13, "line_clarity": 13, "ability_gap": 13},
                "penalties": [],
                "riders": _riders((1, "逃", "S1", 5), (2, "両", "S2", 3), (3, "追", "A1", 2), (4, "マ", "A2", 1)),
            },
            {
                "venue": "次点場",
                "race_number": 10,
                "deadline": "19:30",
                "prediction_score": 80,
                "score_breakdown": {"axis_reliability": 16, "scenario_simplicity": 12, "line_clarity": 12, "ability_gap": 10},
                "penalties": [{"code": "evenly_matched", "points": 3}],
                "riders": _riders((3, "逃", "S1", 4), (4, "両", "S2", 2), (1, "追", "A1", 1), (2, "マ", "A2", 1)),
            },
            {
                "venue": "不足場",
                "race_number": 8,
                "deadline": "18:40",
                "prediction_score": 78,
                "score_breakdown": {"axis_reliability": 17, "scenario_simplicity": 12, "line_clarity": 12, "ability_gap": 11},
                "penalties": [],
                "riders": _riders((1, "逃", "S1", 2)),
            },
            {
                "venue": "穴場",
                "race_number": 11,
                "deadline": "20:10",
                "prediction_score": 60,
                "score_breakdown": {"axis_reliability": 15, "scenario_simplicity": 11, "line_clarity": 11, "ability_gap": 10},
                "penalties": [],
                "riders": _riders((7, "逃", "A1", 2), (6, "両", "A2", 1), (5, "追", "A3", 1), (4, "マ", "A3", 0)),
            },
        ]
        payload = first.build_cursor_first_prediction(candidates, {"minimum_close_time": "18:00"})
        keys = {(item["venue"], item["race"]) for item in payload["selected_races"]}
        self.assertIn(("本線場", 7), keys)
        self.assertIn(("次点場", 10), keys)
        self.assertIn(("穴場", 11), keys)
        self.assertNotIn(("割れ場", 12), keys)
        self.assertNotIn(("不足場", 8), keys)
        self.assertFalse(payload["is_final"])
        self.assertTrue(payload["chatgpt_may_revise"])
        self.assertEqual(len(payload["selected_races"]), 3)
        self.assertEqual(payload["target"], [item["target"] for item in payload["selected_races"]])
        self.assertEqual(payload["confidence"], [item["confidence"] for item in payload["selected_races"]])
        self.assertNotIn("C", payload["confidence"])

    def test_tickets_are_valid_trifecta_and_match_points(self):
        riders = _riders((1, "逃", "S1", 5), (2, "両", "S2", 3), (3, "追", "A1", 2), (4, "マ", "A2", 1), (5, "追", "A3", 1))
        tickets = first.build_line_tickets(riders)
        self.assertIsNotNone(tickets)
        assert tickets is not None
        total = first.tickets_point_count(tickets)
        self.assertGreaterEqual(total, 1)
        self.assertLessEqual(total, 10)
        expanded = []
        for ticket in tickets:
            combos = workflow.expand_pick(ticket["pick"])
            expanded.extend(combos)
        self.assertEqual(len(expanded), len(set(expanded)))
        self.assertEqual(total, len(expanded))
        firsts = {ticket["pick"].split("-")[0] for ticket in tickets if ticket["type"] == "本線"}
        self.assertEqual(firsts, {"1"})
        main_thirds = set(tickets[0]["pick"].split("-")[2])
        self.assertTrue({"3", "4", "5"} <= main_thirds or {"3", "4"} <= main_thirds)

    def test_shortfall_is_recorded_not_filled(self):
        candidates = [
            {
                "venue": "本線場",
                "race_number": 7,
                "deadline": "18:20",
                "prediction_score": 85,
                "score_breakdown": {"axis_reliability": 18, "scenario_simplicity": 13, "line_clarity": 13, "ability_gap": 13},
                "riders": _riders((1, "逃", "S1", 5), (2, "両", "S2", 3), (3, "追", "A1", 2), (4, "マ", "A2", 1)),
            },
            {
                "venue": "不足場",
                "race_number": 8,
                "deadline": "18:40",
                "prediction_score": 80,
                "riders": _riders((1, "逃", "S1", 2)),
            },
        ]
        payload = first.build_cursor_first_prediction(candidates)
        self.assertEqual(len(payload["selected_races"]), 1)
        self.assertIn("推測で埋めていません", payload["shortfall_reason"])
        self.assertTrue(payload["rejected_races"])

    def test_prepare_today_saves_first_prediction_without_final_or_send(self):
        races = ROOT / "examples" / "races_collect.example.json"
        store = sheets.MemorySheetStore()
        sent: list[int] = []

        def send_fn(_data):
            sent.append(1)
            return {"message_id": "1"}

        text = flow.prepare_today(self.root, "2099-01-01", races_file=races, sync_drive=False)
        self.assertIn("第一予想", text)
        self.assertIn("シート転記もChatwork送信も行いません", text)
        self.assertNotIn("最終3Rと買い目は作っていません", text)
        formal = chatgpt_io.chatgpt_input_path(self.root, "2099-01-01")
        data = json.loads(formal.read_text(encoding="utf-8"))
        self.assertIn("cursor_first_prediction", data)
        self.assertGreaterEqual(len(data["candidates"]), 5)
        first_pred = data["cursor_first_prediction"]
        self.assertFalse(first_pred["is_final"])
        self.assertTrue(first_pred["chatgpt_may_revise"])
        self.assertIn("selected_races", first_pred)
        self.assertIn("target", first_pred)
        self.assertIn("confidence", first_pred)
        self.assertIn("main_bets", first_pred)
        self.assertIn("backup_bets", first_pred)
        self.assertIn("total_points", first_pred)
        self.assertIn("reasoning", first_pred)
        keys = {(item["venue"], item["race"]) for item in first_pred["selected_races"]}
        self.assertNotIn(("テスト競輪場E", 8), keys)
        self.assertFalse(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").exists())
        self.assertEqual(store.write_entry_calls, 0)
        self.assertEqual(sent, [])
        state = submission.load_submission_state(self.root, "2099-01-01")
        self.assertFalse(state["sheet_written"])
        self.assertFalse(state["chatwork_sent"])
        for item in data["candidates"]:
            self.assertNotIn("tickets", item)

        # 誤ってingestしない限りシートも送信もしない
        self.assertEqual(
            flow.prepare_today(self.root, "2099-01-01", races_file=races, sync_drive=False).count("Chatwork送信も行いません"),
            1,
        )
        self.assertFalse(chatgpt_io.chatgpt_final_path(self.root, "2099-01-01").exists())


if __name__ == "__main__":
    unittest.main()
