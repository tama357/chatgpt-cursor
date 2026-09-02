"""日次学習JSON（inbox正本）のschema・再読・100R・部分結果。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_fixtures import ProductionDataGuardMixin  # noqa: E402

from common.constants import (  # noqa: E402
    DAILY_JSON_SCHEMA_VERSION,
    DAY_STATUS_NO_MEETING,
    STATE_TIMEZONE,
)
from common.daily_json import (  # noqa: E402
    apply_results_doc_to_records,
    axis_from_tickets,
    build_predictions_payload,
    build_results_payload,
    count_completed_from_inbox,
    count_completed_races,
    empty_day_payload,
    is_completed_race,
    make_race_id,
    merge_result_races,
    prediction_reread_problems,
    records_from_predictions_doc,
    remaining_to_100,
    results_cover_predictions,
    results_reread_problems,
    save_daily_json,
)


def _ticket(pick: str = "1-2-3") -> dict:
    return {"type": "本線", "pick": pick}


def _pred_record(*, sport: str, venue: str, race: int, date: str = "2026-09-03") -> dict:
    record = {
        "date": date,
        "sport": sport,
        "venue": venue,
        "race": race,
        "number": 1,
        "prediction_score": 70,
        "confidence": "B",
        "ticket_count": 1,
        "tickets": [_ticket()],
        "axis": "1",
        "fetched_data": {"race_id": f"{venue}{race}"},
    }
    record["race_id"] = make_race_id(record)
    return record


class DailyJsonTest(ProductionDataGuardMixin, unittest.TestCase):
    def test_schema_allows_variable_race_count(self):
        for count in (0, 1, 3, 5):
            races = [
                _pred_record(sport="jra", venue="中山", race=i + 1) for i in range(count)
            ]
            payload = build_predictions_payload(
                date="2026-09-03", sport="jra", races=races
            )
            self.assertEqual(payload["schema_version"], DAILY_JSON_SCHEMA_VERSION)
            self.assertEqual(payload["timezone"], STATE_TIMEZONE)
            self.assertEqual(len(payload["races"]), count)
            self.assertEqual(prediction_reread_problems(payload, payload), [])

    def test_axis_from_hon_sen_ticket(self):
        self.assertEqual(axis_from_tickets([_ticket("4-2-135")]), "4")
        self.assertIsNone(axis_from_tickets([{"type": "抑え", "pick": "3-2-1"}]))

    def test_empty_day_reread(self):
        payload = empty_day_payload(
            date="2026-09-03", sport="nar", day_status=DAY_STATUS_NO_MEETING
        )
        self.assertEqual(payload["races"], [])
        self.assertEqual(prediction_reread_problems(payload, payload), [])

    def test_results_partial_merge_does_not_overwrite_completed(self):
        first = {
            "race_id": "nar:a",
            "status": "ハズレ",
            "stake": 100,
            "payout": 0,
            "trifecta": "1-2-3",
            "primary_miss_reason": "axis_miss",
        }
        second_new = {
            "race_id": "nar:b",
            "status": "的中",
            "stake": 100,
            "payout": 1200,
            "trifecta": "2-3-4",
        }
        overwrite = {
            "race_id": "nar:a",
            "status": "的中",
            "stake": 100,
            "payout": 9999,
            "trifecta": "9-9-9",
        }
        merged = merge_result_races([first], [overwrite, second_new])
        by_id = {row["race_id"]: row for row in merged}
        self.assertEqual(by_id["nar:a"]["trifecta"], "1-2-3")
        self.assertEqual(by_id["nar:b"]["status"], "的中")

    def test_100r_counts_only_hit_or_miss_per_sport(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        jra_races = [
            {"status": "的中", "skipped": False},
            {"status": "ハズレ"},
            {"status": "未実施"},
            {"skipped": True, "status": "ハズレ"},
            {"result": {"status": "的中"}},
        ]
        nar_races = [{"status": "的中"}]
        self.assertEqual(count_completed_races(jra_races), 3)
        self.assertFalse(is_completed_race({"status": "未実施"}))
        save_daily_json(
            tmp / "data" / "inbox" / "jra" / "2026-09-03.results.json",
            build_results_payload(
                date="2026-09-03",
                sport="jra",
                races=[
                    {
                        "race_id": "jra:1",
                        "result": {
                            "status": "的中",
                            "stake": 100,
                            "payout": 200,
                            "trifecta": "1-2-3",
                        },
                    },
                    {
                        "race_id": "jra:2",
                        "result": {
                            "status": "ハズレ",
                            "stake": 100,
                            "payout": 0,
                            "trifecta": "3-2-1",
                            "primary_miss_reason": "axis_miss",
                        },
                    },
                ],
            ),
        )
        save_daily_json(
            tmp / "data" / "inbox" / "nar" / "2026-09-03.results.json",
            build_results_payload(
                date="2026-09-03",
                sport="nar",
                races=[
                    {
                        "race_id": "nar:1",
                        "result": {
                            "status": "的中",
                            "stake": 100,
                            "payout": 300,
                            "trifecta": "1-2-3",
                        },
                    }
                ],
            ),
        )
        self.assertEqual(count_completed_from_inbox(tmp, "jra"), 2)
        self.assertEqual(count_completed_from_inbox(tmp, "nar"), 1)
        self.assertEqual(count_completed_from_inbox(tmp, "kyotei"), 0)
        self.assertEqual(remaining_to_100(2), 98)

    def test_results_cover_and_apply_to_prediction_records(self):
        pred = build_predictions_payload(
            date="2026-09-03",
            sport="kyotei",
            races=[_pred_record(sport="kyotei", venue="桐生", race=1)],
        )
        self.assertFalse(results_cover_predictions(pred, None))
        result_payload = build_results_payload(
            date="2026-09-03",
            sport="kyotei",
            races=records_from_predictions_doc(pred),
        )
        # 予想だけでは完了扱いにしない
        self.assertEqual(result_payload["races"], [])
        records = records_from_predictions_doc(pred)
        records[0]["result"] = {
            "status": "ハズレ",
            "stake": 100,
            "payout": 0,
            "trifecta": "6-5-4",
            "primary_miss_reason": "axis_miss",
        }
        result_payload = build_results_payload(
            date="2026-09-03", sport="kyotei", races=records
        )
        self.assertEqual(results_reread_problems(result_payload, result_payload), [])
        self.assertTrue(results_cover_predictions(pred, result_payload))
        fresh = records_from_predictions_doc(pred)
        apply_results_doc_to_records(fresh, result_payload)
        self.assertEqual(fresh[0]["result"]["status"], "ハズレ")
        self.assertEqual(fresh[0]["result"]["trifecta"], "6-5-4")

    def test_same_path_overwrite_does_not_create_extra_files(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "2026-09-03.predictions.json"
        first = empty_day_payload(
            date="2026-09-03", sport="jra", day_status=DAY_STATUS_NO_MEETING
        )
        save_daily_json(path, first)
        second = build_predictions_payload(
            date="2026-09-03",
            sport="jra",
            races=[_pred_record(sport="jra", venue="中山", race=11)],
        )
        save_daily_json(path, second)
        files = list(tmp.glob("*.predictions.json"))
        self.assertEqual(len(files), 1)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(loaded["races"]), 1)


if __name__ == "__main__":
    unittest.main()
