# 個人予想システム

原田さん個人利用の**競馬＋競輪** 予想・記録・集計・復習・学習システムです。

## 原田さんの使い方（チャットのみ）

| やりたいこと | Cursor チャット |
|--------------|-----------------|
| 今日の予想 | **「今日の競馬と個人競輪を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成やコマンド入力は **Cursor がすべて実行**します。

## 提出用との分離

| 対象 | 触らない |
|------|----------|
| `競輪予想/`（提出用） | Chatwork・Google Sheets提出 |
| Drive `競艇_*.xlsx` | 競艇ファイルは競輪として使わない |

## Excelファイル

### 競馬

- `excel/競馬_予想記入シート_2026年9月.xlsx`
- `excel/競馬_予想集計シート_2026年9月.xlsx`

### 個人競輪（ChatGPT共有は CHATGPT_EXCEL.md 参照）

- `excel/競輪_個人_予想記入シート.xlsx`
- `excel/競輪_個人_予想集計シート.xlsx`

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

## データ自動取得

| 競技 | ソース |
|------|--------|
| 競馬 | netkeiba（失敗時は Cursor が Web 調査） |
| 個人競輪 | keirin.jp 公式 JSON API |

保存先:

- 出走: `data/races/{keiba,keirin}/YYYY-MM-DD.json`
- 結果: `data/results/{keiba,keirin}/YYYY-MM-DD.json`

## テスト

```bash
python3 -m unittest discover -s 個人予想/tests -v
python3 -m unittest discover -s 競輪予想/tests -v
```

## 詳細ルール

- Cursor 実行手順: `個人予想/AGENTS.md`
- ChatGPT 用 Excel パス: `個人予想/CHATGPT_EXCEL.md`
