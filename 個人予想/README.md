# 個人予想システム

原田さん個人利用の競馬・競輪 予想・記録・集計・復習・学習システムです。

**提出用競輪案件（`競輪予想/`）とは完全に分離**しています。Chatwork送信、Google Sheets提出用ファイル、外部アカウントログインは行いません。

## できること

1. レース選定（1日最大5レース、基準未達は見送り）
2. 三連単予想作成（原則10点以内）
3. Excelシートへの記載（入力セルのみ）
4. 結果確認・記載（正式結果JSONから）
5. 的中率・回収率の集計
6. 予想内容の復習（ハズレ理由分類含む）
7. 学習履歴の保存・レポート（100レース未満は配点自動変更なし）
8. Cursorチャットへの報告（CLI標準出力）

## ファイル構成

```
個人予想/
├── config/          # 競馬・競輪（個人）のルール
├── excel/           # Excelテンプレート（自動生成）
├── examples/        # サンプルレース・結果JSON
├── data/            # 個人データ（Git管理外）
├── tools/workflow.py
└── tests/
```

## セットアップ

```bash
pip install -r 個人予想/requirements.txt
python3 個人予想/tools/workflow.py init-templates
```

## 実行コマンド

```bash
# 予想
python3 個人予想/tools/workflow.py predict-keiba --date 2026-09-01
python3 個人予想/tools/workflow.py predict-keirin --date 2026-09-01
python3 個人予想/tools/workflow.py predict-all --date 2026-09-01

# 結果反映（先に結果JSONを配置）
python3 個人予想/tools/workflow.py apply-results keiba 個人予想/examples/keiba_results.sample.json --date 2099-01-01
python3 個人予想/tools/workflow.py results-keiba --date 2026-09-01
python3 個人予想/tools/workflow.py results-all --date 2026-09-01

# 学習・成績
python3 個人予想/tools/workflow.py learning-keiba
python3 個人予想/tools/workflow.py learning-keirin
python3 個人予想/tools/workflow.py report-all --date 2026-09-01
```

## レースデータの渡し方

本番運用時は次のJSONを配置してください。

- `個人予想/data/races/keiba/YYYY-MM-DD.json`
- `個人予想/data/races/keirin/YYYY-MM-DD.json`
- `個人予想/data/results/keiba/YYYY-MM-DD.json`（結果用、`apply-results` に渡す）

サンプルが無い場合は `examples/*_races.sample.json` を参照します（テスト用）。

## 提出用競輪との分離

| 項目 | 提出用（競輪予想/） | 個人（個人予想/） |
|------|---------------------|-------------------|
| レース数 | 3 | 最大5 |
| Excel | Google Sheets | ローカルxlsx |
| Chatwork | あり | **なし** |
| データ | state（提出用） | data/keirin（個人） |

## テスト

```bash
python3 -m unittest discover -s 個人予想/tests -v
```
