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

## 毎日の自動実行（GitHub Actions）

PCがオフでも動きます。時刻は日本時間です。

| 日本時間 | 内容 |
|----------|------|
| 毎日 4:00 | 前日の正式結果、Excel集計、復習、学習 |
| 毎日 6:00 | 当日の公式出走、最大5レースずつ予想、Excel記入 |

定期実行は GitHub Actions Variable `PERSONAL_PREDICT_ENABLED=true` のときだけ動きます。

手動の `verify-drive` と初期移行は、スイッチがオフでも使えます。4:00 / 6:00 は `true` のときだけ動きます。

初期移行は **PC版 Cursor** から一度だけ行います。GitHub Actions の checkout には Windows ローカルの state が無いため、Actions 側の bootstrap は state なしでは失敗終了します。Driveの古いExcelは取得しません。

最初の設定は `個人予想/DRIVE_SYNC.md` を見てください。秘密鍵は GitHub Secret にだけ置きます。

## Cursor 内部コマンド

```bash
python3 個人予想/tools/workflow.py predict-today
python3 個人予想/tools/workflow.py results-yesterday
python3 個人予想/tools/workflow.py verify-drive
python3 個人予想/tools/workflow.py cloud-predict
python3 個人予想/tools/workflow.py cloud-results
```

`predict-all` は中央競馬・地方競馬・競艇の3種類です。

## データ自動取得

| 区分 | 出走 | 結果 | 保存先 |
|------|------|------|--------|
| 中央競馬 | race.netkeiba.com（開催日のみ。非開催は正常終了） | race.netkeiba.com / db.netkeiba.com の三連単。`race_id` が無い記録は取得失敗 | `data/races/jra` / `data/results/jra` / `data/jra` |
| 地方競馬 | nar.netkeiba.com（取れなければこの競技だけ中止） | nar.netkeiba.com の三連単。取れなければ取得失敗 | `data/races/nar` / `data/results/nar` / `data/nar` |
| 競艇 | boatrace.jp（取れなければこの競技だけ中止） | boatrace.jp の `raceresult`。取れなければ取得失敗 | `data/races/kyotei` / `data/results/kyotei` / `data/kyotei` |

本番では examples / sample / test_fixture を使いません。推測では記入しません。

## テスト

```bash
python3 -m unittest discover -s 個人予想/tests -v
python3 個人予想/tests/run_e2e_excel_copy_test.py
```

提出用競輪のテストは `競輪予想/` 側で別管理します（このシステムでは変更しません）。

## 詳細ルール

- Cursor 実行手順: `個人予想/AGENTS.md`
- ChatGPT 用 Excel パス: `個人予想/CHATGPT_EXCEL.md`
