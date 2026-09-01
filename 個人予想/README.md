# 個人予想システム

原田さん個人利用の**競馬＋競艇** 予想・記録・集計・復習・学習システムです。

## 原田さんの使い方（チャットのみ）

| やりたいこと | Cursor チャット |
|--------------|-----------------|
| 今日の予想 | **「今日の競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成やコマンド入力は **Cursor がすべて実行**します。

## 提出用との分離

| 対象 | 扱い |
|------|------|
| `競輪予想/`（提出用） | **一切変更しない**（Chatwork・1日3レース） |
| 個人競輪 Excel | 使用しない |

## Excelファイル

### 競馬

- `excel/競馬_予想記入シート_2026年9月.xlsx`
- `excel/競馬_予想集計シート_2026年9月.xlsx`

### 競艇

- `excel/競艇_予想記入シート_2026年9月.xlsx`
- `excel/競艇_予想集計シート_2026年9月.xlsx`

各ファイルに `202609`〜`202708` の月別シートがあります。

## セットアップ（初回のみ・Cursor が実行）

```bash
pip install -r 個人予想/requirements.txt
python3 個人予想/tools/workflow.py init-excel
```

## Cursor 内部コマンド

```bash
python3 個人予想/tools/workflow.py predict-today
python3 個人予想/tools/workflow.py results-yesterday
python3 個人予想/tools/workflow.py predict-all --date 2026-09-01
python3 個人予想/tools/workflow.py results-all --date 2026-09-01
```

`predict-all` は競馬＋競艇です。個人競輪（predict-keirin）は使いません。

## データ自動取得

| 競技 | ソース |
|------|--------|
| 競馬 | netkeiba（失敗時は Cursor が Web 調査） |
| 競艇 | boatrace.jp 公式（出走表・展示・モーター・選手・オッズ・結果） |

保存先:

- 出走: `data/races/{keiba,kyotei}/YYYY-MM-DD.json`
- 結果: `data/results/{keiba,kyotei}/YYYY-MM-DD.json`

## テスト

```bash
python3 -m unittest discover -s 個人予想/tests -v
```

提出用競輪のテストは `競輪予想/` 側で別管理します（このシステムでは変更しません）。

## 詳細ルール

- Cursor 実行手順: `個人予想/AGENTS.md`
- ChatGPT 用 Excel パス: `個人予想/CHATGPT_EXCEL.md`
