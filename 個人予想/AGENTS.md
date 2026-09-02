# 個人予想：Cursor実行ルール

## 原田さんの操作（これだけ）

| やりたいこと | Cursor チャットで伝える文言 |
|--------------|----------------------------|
| 今日の予想 | **「今日の中央競馬と地方競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成、コマンド入力、Excel 操作は **すべて Cursor が実行**する。原田さんに技術作業をさせない。

## 2026-09-03 からの開始

予想・結果・集計・復習・学習の開始日は **2026-09-03（日本時間）** です。それより前の日付は結果取得にも学習にも使いません。9月2日のExcel記録はそのまま残します。

日次の正本は **各競技の Drive inbox にある日次JSON** です。正規state（`jra_state.json` 等）は日次ジョブから直接更新しません。後から Cursor が `ingest-inbox` で合成します。

正規stateが必要なのは、後からの合成と学習レポートです。日次の予想・結果・Excel記入は、正規stateが無くても止まりません。既存stateは削除しません。開始時点は空なので移行は不要です。

```bash
python3 個人予想/tools/workflow.py init-state --start-date 2026-09-03 --i-confirm-init-state
```

このコマンドは Excel・Drive・提出用 `競輪予想/` を変更しません。3競技とも成功するか、1つも残さないかのどちらかです。既存stateは上書きしません。

## Cursor が自動で行うこと

### 予想（predict-today）

1. 中央競馬は JRA 開催日のみ出走を確認（netkeiba）
2. 地方競馬は NAR 開催から最大5レース選定
3. 競艇は boatrace.jp から最大5レース選定
4. それぞれ三連単予想を作成し、対応する Excel へ記入
5. 完了後に当日の `YYYY-MM-DD.predictions.json` を各競技 inbox へ保存し、再読する
6. 予想内容を分かりやすくチャット報告

内部コマンド:

```bash
python3 個人予想/tools/workflow.py predict-today
```

### 結果確認（results-yesterday）

1. 前日の `predictions.json` を予想の正本として結果を紐付ける
2. 取れたレース分だけ Excel 集計へ反映する（部分取得可）
3. `YYYY-MM-DD.results.json` を保存し、再読する
4. 原田さんへチャット報告

正規stateが無いことでは止めません。学習レポートの生成と正規state更新は日次では行いません。

```bash
python3 個人予想/tools/workflow.py results-yesterday
```

### 正規stateへ合成（日次ジョブでは呼ばない）

```bash
python3 個人予想/tools/workflow.py ingest-inbox --date YYYY-MM-DD
```

## 自動取得に失敗した場合

```bash
python3 個人予想/tools/workflow.py save-races jra /path/to/races.json --date YYYY-MM-DD
python3 個人予想/tools/workflow.py save-races nar /path/to/races.json --date YYYY-MM-DD
python3 個人予想/tools/workflow.py save-races kyotei /path/to/races.json --date YYYY-MM-DD
```

学習JSONだけ欠けた日は、Excel成功を取り消さず「学習JSON未保存」と報告します。後からその日の日次JSONだけ穴埋めできます。

## 提出用競輪との分離

この `predict-today` は中央競馬・地方競馬・競艇だけ。提出用競輪の予想はしない。

提出用競輪は `競輪予想/` で、Cursor＝データ、ChatGPT＝最終予想に分離している。ChatGPTに渡すのは完成済み `prediction_input_YYYY-MM-DD.json` だけ。操作は `競輪予想/AGENTS.md`。

## 禁止

- Chatwork・メール・Slack・SNS 送信
- 提出用競輪の既存シート構造の変更
- 個人競輪 Excel の使用
- 中央競馬と地方競馬の成績・学習データの混在
- 日次ジョブからの `jra_state.json` / `nar_state.json` / `kyotei_state.json` 更新

## Excel仕様

- ファイルは6つ（中央競馬・地方競馬・競艇 × 記入／集計）
- 1か月1シート（`202609`〜`202708`）
- 1日5行（予想番号1〜5）
- 集計シートの B〜O 列は数式（触らない）

## 学習

- 日次の正本は `data/inbox/{jra,nar,kyotei}/YYYY-MM-DD.predictions.json` と `YYYY-MM-DD.results.json`
- Drive保存先（フォルダが無ければ保存時に自動作成。手動作成は不要）:
  - マイドライブ / ChatGPT / 予想学習 / 中央競馬 / inbox
  - マイドライブ / ChatGPT / 予想学習 / 地方競馬 / inbox
  - マイドライブ / ChatGPT / 予想学習 / 競艇 / inbox
- 正規stateは `data/{jra,nar,kyotei}/state.json`。Cursorの `ingest-inbox` の出力先
- `start_date`（既定 2026-09-03 JST）より前の記録は学習しない
- 100レースは競技ごとに独立。的中／ハズレまで確定したレースだけを数える
- 100レース未満: 配点変更なし
- `recommended_weights` は提案のみ

## Google Drive / GitHub Actions

- 認証はサービスアカウント。秘密鍵は GitHub Secret `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` のみ
- 定期実行は Variable `PERSONAL_PREDICT_ENABLED=true` のときだけ
- `verify-drive` と `bootstrap-cloud` はスイッチがオフでもサービスアカウントを使う
- 既存6 Excel は ID指定で更新する。同名ファイルは新規作成しない。場所・IDは変更しない
- 開始時に Drive から Excel を取得する。正規stateは日次では取得・保存しない
- 終了時に Excel を保存し、日次JSONを各競技 inbox へ保存する（同名は更新、重複作成しない）
- 学習JSON保存失敗ではジョブ全体を失敗扱いにしない。完了報告に「学習JSON未保存」と書く
- Excel保存失敗はジョブ失敗にする
- 学習データは競技ごとに分離する
- 日々のExcel更新では PR を作らない
- 最初の確認は `verify-drive`（読み取りのみ。失敗したら終了コード1）
- 初期移行は PC版 Cursor から行う。原田さんの許可があるまで実行しない
- 詳細は `個人予想/DRIVE_SYNC.md`
