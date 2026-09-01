# 個人予想システム

原田さん個人利用の**中央競馬・地方競馬・競艇** 予想・記録・集計・復習・学習システムです。

3区分は設定・保存先・学習データを混ぜません。

## 原田さんの使い方（チャットのみ）

| やりたいこと | Cursor チャット |
|--------------|-----------------|
| 今日の予想 | **「今日の中央競馬と地方競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成やコマンド入力は **Cursor がすべて実行**します。

## 提出用との分離

| 対象 | 扱い |
|------|------|
| `競輪予想/`（提出用） | **一切変更しない**（Chatwork・1日3レース） |
| 個人競輪 Excel | 使用しない |
| 旧 `競馬_予想*.xlsx` | 使用しない（中央／地方に分割済み） |

## Excelファイル（6つ）

| 区分 | 記入 | 集計 |
|------|------|------|
| 中央競馬 | `excel/中央競馬_予想記入シート_2026年9月.xlsx` | `excel/中央競馬_予想集計シート_2026年9月.xlsx` |
| 地方競馬 | `excel/地方競馬_予想記入シート_2026年9月.xlsx` | `excel/地方競馬_予想集計シート_2026年9月.xlsx` |
| 競艇 | `excel/競艇_予想記入シート_2026年9月.xlsx` | `excel/競艇_予想集計シート_2026年9月.xlsx` |

各ファイルに `202609`〜`202708` の月別シートがあります。1日最大5レースです。

## Cursor 内部コマンド

```bash
python3 個人予想/tools/workflow.py predict-today
python3 個人予想/tools/workflow.py results-yesterday
python3 個人予想/tools/workflow.py predict-all --date 2026-09-01
python3 個人予想/tools/workflow.py results-all --date 2026-09-01
```

`predict-all` は中央競馬・地方競馬・競艇の3種類です。

## データ自動取得

| 区分 | ソース | 保存先 |
|------|--------|--------|
| 中央競馬 | netkeiba（JRA開催日のみ） | `data/races/jra` / `data/results/jra` / `data/jra` |
| 地方競馬 | nar.netkeiba | `data/races/nar` / `data/results/nar` / `data/nar` |
| 競艇 | boatrace.jp | `data/races/kyotei` / `data/results/kyotei` / `data/kyotei` |

## テスト

```bash
python3 -m unittest discover -s 個人予想/tests -v
python3 個人予想/tests/run_e2e_excel_copy_test.py
```

提出用競輪のテストは `競輪予想/` 側で別管理します（このシステムでは変更しません）。

## 詳細ルール

- Cursor 実行手順: `個人予想/AGENTS.md`
- ChatGPT 用 Excel パス: `個人予想/CHATGPT_EXCEL.md`
