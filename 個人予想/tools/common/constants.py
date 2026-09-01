from __future__ import annotations

MISS_REASONS = frozenset(
    {
        "axis_miss",
        "second_place_miss",
        "third_place_miss",
        "scenario_miss",
        "line_collapse",
        "unexpected_position",
        "upset",
        "condition_miss",
        "accident",
        "data_shortage",
        "overconfidence",
        "too_many_combinations",
        "too_few_combinations",
        "other",
    }
)

ALLOWED_STATUS = frozenset({"的中", "ハズレ", "未実施"})
ALLOWED_TARGETS = frozenset({"鉄板", "中穴", "大穴"})
ALLOWED_CONFIDENCE = frozenset({"A", "B", "C"})
ALLOWED_TICKET_TYPES = frozenset({"本線", "抑え"})

SPORTS = frozenset({"keiba", "kyotei"})
