from __future__ import annotations

from dataclasses import dataclass

MAX_RACES = 5
BLOCK_HEIGHT = 15
FIRST_MAIN_ROW = 2

# 予想記入シート列（1-indexed）
COL_PRED_NUM = 1       # A
COL_SPORT = 2          # B
COL_VENUE = 3          # C
COL_RACE = 4           # D
COL_CLOSE = 5          # E
COL_TARGET = 6         # F
COL_PRED_SCORE = 7     # G  prediction_score
COL_CONFIDENCE = 8     # H  confidence
COL_AXIS = 9           # I
COL_MAIN = 10          # J  本線
COL_COVER = 11         # K  抑え
COL_TOTAL = 12         # L  合計点数（Pythonが計算値を書込）
COL_RATIONALE = 13     # M
COL_SCENARIO = 14      # N
COL_RISKS = 15         # O
COL_SKIP = 16          # P  見送り判断
COL_RESULT = 17        # Q  三連単結果
COL_PAYOUT = 18        # R  払戻金
COL_STATUS = 19        # S  的中/ハズレ
COL_POINTS = 20        # T  購入点数

PREDICTION_INPUT_COLS = {
    COL_PRED_NUM,
    COL_SPORT,
    COL_VENUE,
    COL_RACE,
    COL_CLOSE,
    COL_TARGET,
    COL_PRED_SCORE,
    COL_CONFIDENCE,
    COL_AXIS,
    COL_MAIN,
    COL_COVER,
    COL_TOTAL,
    COL_RATIONALE,
    COL_SCENARIO,
    COL_RISKS,
    COL_SKIP,
}
RESULT_INPUT_COLS = {COL_RESULT, COL_PAYOUT, COL_STATUS, COL_POINTS}


@dataclass(frozen=True)
class PredictionBlock:
    index: int
    main_row: int

    @property
    def end_row(self) -> int:
        return self.main_row + BLOCK_HEIGHT - 1


def main_rows() -> list[int]:
    return [FIRST_MAIN_ROW + i * BLOCK_HEIGHT for i in range(MAX_RACES)]


def blocks() -> list[PredictionBlock]:
    return [PredictionBlock(i + 1, row) for i, row in enumerate(main_rows())]


def sheet_tab_name(date_str: str) -> str:
    """YYYY-MM-DD -> Excelタブ名（/ は使えないため - を使用）"""
    return date_str


def summary_tab_name(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


# 集計シート
SUMMARY_FORMULA_START_COL = 2   # B-O は数式（触らない）
SUMMARY_INPUT_START_COL = 16    # P列から
SUMMARY_RACE_COLS = list(range(16, 21))  # P-T（5レース）
SUMMARY_ROWS_PER_DAY = 3


def summary_day_start_row(day: int) -> int:
    """月内日付(1-31)から開始行。1日目=行2"""
    return 2 + (day - 1) * SUMMARY_ROWS_PER_DAY
