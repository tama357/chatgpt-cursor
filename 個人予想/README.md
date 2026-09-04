# 個人予想システム

原田さん個人利用の**中央競馬・地方競馬・競艇** 予想・記録・集計・復習・学習システムです。

**運用停止（2026-09-04）。** `PERSONAL_PREDICT_ENABLED=false`。
Cursor / GitHub Actions からの予想・結果・Excel・Drive・inbox・state・学習は行わない。
コードと過去データは残してある。明示的な再開指示があるまで実行しない。

3区分は設定・保存先・学習データを混ぜません。

## 原田さんの使い方（チャットのみ）

停止中。再開指示があるまで Cursor は次を実行しない。

| やりたいこと | Cursor チャット（停止前） |
|--------------|-----------------|
| 今日の予想 | **「今日の中央競馬と地方競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

## 提出用との分離

| 対象 | 扱い |
|------|------|
| `競輪予想/`（提出用） | 別系統。Cursorはデータのみ、ChatGPTが最終予想。既存シート構造は変えない |
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

**停止中。** `PERSONAL_PREDICT_ENABLED=false`。`personal-predict.yml` は無効。

| 日本時間 | 内容 | 状態 |
|----------|------|------|
| 毎日 4:00 | 前日の予想JSONを正本に正式結果、Excel集計、結果JSON保存 | 停止 |
| 毎日 6:00 | 当日の公式出走、最大5レースずつ予想、Excel記入、予想JSON保存 | 停止 |

再開指示があるまで定期実行も手動実行もしない。

日次の正本は Drive inbox の日次JSONです。正規stateは日次ジョブから更新しません。学習JSONの保存失敗では Excel 成功を取り消さず、「学習JSON未保存」と報告します。

初期移行は **PC版 Cursor** から一度だけ行います。Driveの古いExcelは取得しません。

最初の設定は `個人予想/DRIVE_SYNC.md` を見てください。秘密鍵は GitHub Secret にだけ置きます。

## Cursor 内部コマンド

停止中。再開指示があるまで次は実行しない。

```bash
python3 個人予想/tools/workflow.py init-state --start-date 2026-09-03 --i-confirm-init-state
python3 個人予想/tools/workflow.py predict-today
python3 個人予想/tools/workflow.py results-yesterday
python3 個人予想/tools/workflow.py ingest-inbox --date YYYY-MM-DD
python3 個人予想/tools/workflow.py verify-drive
python3 個人予想/tools/workflow.py cloud-predict
python3 個人予想/tools/workflow.py cloud-results
```

`init-state` は確認フラグがあるときだけ、中央競馬・地方競馬・競艇の正規stateを新規作成します。開始日は 2026-09-03（JST）です。3つとも成功するか、この実行で作ったstateを1つも残さないかのどちらかです。既存stateは上書きしません。Excel は変更しません。日次の予想・結果には必須ではありません。

クラウドの予想・結果は Excel と日次JSON（inbox）を使います。正規stateが無くても止まりません。`jra_state.json` 等は日次ジョブから更新しません。`ingest-inbox` は後から Cursor が正規stateへ合成するときだけ使います。

`predict-all` は中央競馬・地方競馬・競艇の3種類です。

## データ自動取得

| 区分 | 出走 | 結果 | 保存先 |
|------|------|------|--------|
| 中央競馬 | race.netkeiba.com（開催日のみ。非開催は正常終了） | race.netkeiba.com / db.netkeiba.com の三連単。`race_id` が無い記録は取得失敗 | `data/races/jra` / `data/results/jra` / `data/inbox/jra` |
| 地方競馬 | nar.netkeiba.com（取れなければこの競技だけ中止） | nar.netkeiba.com の三連単。取れなければ取得失敗 | `data/races/nar` / `data/results/nar` / `data/inbox/nar` |
| 競艇 | boatrace.jp（取れなければこの競技だけ中止） | boatrace.jp の `raceresult`。取れなければ取得失敗 | `data/races/kyotei` / `data/results/kyotei` / `data/inbox/kyotei` |

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
