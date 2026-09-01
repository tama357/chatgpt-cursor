# 個人予想システム（手動入力版）

原田さん個人利用の**競馬＋競輪** 予想・記録・集計・復習・学習システムです。

> **ステータス: 手動入力版**  
> レースデータJSON・結果JSONの手動配置が必要です。自動取得は未実装です。

## 提出用との分離

| 対象 | 触らない |
|------|----------|
| `競輪予想/`（提出用） | Chatwork・Google Sheets提出 |
| Drive `競艇_*.xlsx` | 競艇ファイルは競輪として使わない |

## 参照するExcelファイル

### 競馬（Drive実ファイルと同仕様）

- `excel/競馬_予想記入シート_2026年9月.xlsx`
- `excel/競馬_予想集計シート_2026年9月.xlsx`

### 競輪（個人検証専用・新規）

- `excel/競輪_個人_予想記入シート.xlsx`
- `excel/競輪_個人_予想集計シート.xlsx`

### 共通シート名（12か月）

`202609` `202610` `202611` `202612` `202701` `202702` `202703` `202704` `202705` `202706` `202707` `202708`

実行日から対象月を判定し、上記 `YYYYMM` シートへ書き込みます。日別タブは作りません。

## 買い目点数

| 競技 | 目安 |
|------|------|
| 競馬 | 12〜30点（上限30） |
| 競輪（個人） | 原則10点以内 |

## セットアップ

```bash
pip install -r 個人予想/requirements.txt
python3 個人予想/tools/workflow.py init-excel
```

`init-excel` で実Excelを検査し、`excel/sheet_mapping.json` に列マッピングを出力します。

## 実行コマンド

```bash
# 予想（先に data/races/...json を配置）
python3 個人予想/tools/workflow.py predict-keiba --date 2026-09-01
python3 個人予想/tools/workflow.py predict-keirin --date 2026-09-01
python3 個人予想/tools/workflow.py predict-all --date 2026-09-01

# 結果（先に results JSON を apply-results で反映）
python3 個人予想/tools/workflow.py apply-results keiba 個人予想/examples/keiba_results.sample.json --date 2026-09-01
python3 個人予想/tools/workflow.py results-all --date 2026-09-01

# 学習・成績
python3 個人予想/tools/workflow.py learning-keiba
python3 個人予想/tools/workflow.py learning-keirin
python3 個人予想/tools/workflow.py report-all --date 2026-09-01
```

## 手動作業（現状必須）

1. `data/races/keiba/YYYY-MM-DD.json` … 当日レース情報
2. `data/races/keirin/YYYY-MM-DD.json` … 同上
3. 結果確定後 … `apply-results` 用の結果JSON
4. Excel実ファイルの更新はDrive側で行い、必要なら `excel/` へ再配置

## テスト

```bash
python3 -m unittest discover -s 個人予想/tests -v
python3 -m unittest discover -s 競輪予想/tests -v
```
