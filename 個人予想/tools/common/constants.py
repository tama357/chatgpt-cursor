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

# Excel「外れ型」列の表示用。state.jsonのprimary_miss_reasonは14種すべて1対1で保持し、
# 情報を圧縮しない（secondary_miss_reasonsは今回Excelへは出力しない）。
MISS_TYPE_MAP = {
    "axis_miss": "軸外れ",
    "second_place_miss": "2着外れ",
    "third_place_miss": "3着外れ",
    "scenario_miss": "展開読み外れ",
    "line_collapse": "ライン崩壊",
    "unexpected_position": "想定外位置取り",
    "upset": "波乱",
    "condition_miss": "条件読み外れ",
    "accident": "事故",
    "data_shortage": "データ不足",
    "overconfidence": "過信",
    "too_many_combinations": "買い目過多",
    "too_few_combinations": "買い目不足",
    "other": "その他",
}
MISS_TYPE_NONE = "-"

# 個人予想の正式3区分。keiba（統合）と keirin は未使用。
SPORTS = ("jra", "nar", "kyotei")
STATE_VERSION = 2
STATE_TIMEZONE = "Asia/Tokyo"
# 予想・結果・集計・復習・学習の開始日（JST）。これより前は対象外。
DEFAULT_START_DATE = "2026-09-03"
DAILY_JSON_SCHEMA_VERSION = 1
LEARNING_JSON_UNSAVED = "学習JSON未保存"
COMPLETED_RESULT_STATUSES = frozenset({"的中", "ハズレ"})
DAY_STATUS_PREDICTED = "predicted"
DAY_STATUS_NO_MEETING = "no_meeting"
DAY_STATUS_FETCH_FAILED = "fetch_failed"
INBOX_ROOT_NAME = "予想学習"
INBOX_DIR_NAME = "inbox"
INBOX_SPORT_FOLDERS = {
    "jra": "中央競馬",
    "nar": "地方競馬",
    "kyotei": "競艇",
}
SPORT_LABELS = {
    "jra": "中央競馬",
    "nar": "地方競馬",
    "kyotei": "競艇",
}
EXCEL_FILENAMES = {
    "jra_entry": "中央競馬_予想記入シート_2026年9月.xlsx",
    "jra_summary": "中央競馬_予想集計シート_2026年9月.xlsx",
    "nar_entry": "地方競馬_予想記入シート_2026年9月.xlsx",
    "nar_summary": "地方競馬_予想集計シート_2026年9月.xlsx",
    "kyotei_entry": "競艇_予想記入シート_2026年9月.xlsx",
    "kyotei_summary": "競艇_予想集計シート_2026年9月.xlsx",
}
SPORT_EXCEL_KEYS = {
    "jra": ["jra_entry", "jra_summary"],
    "nar": ["nar_entry", "nar_summary"],
    "kyotei": ["kyotei_entry", "kyotei_summary"],
}
RULE_FILES = {
    "jra": "jra_rules.json",
    "nar": "nar_rules.json",
    "kyotei": "kyotei_rules.json",
}
MONTH_SHEETS = [
    "202609",
    "202610",
    "202611",
    "202612",
    "202701",
    "202702",
    "202703",
    "202704",
    "202705",
    "202706",
    "202707",
    "202708",
]
