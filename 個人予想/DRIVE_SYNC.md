# Google Drive 同期（個人予想）

対象は **既存の6つのExcel** です。同名ファイルの新規作成はしません。ID指定で上書きだけします。場所・IDは変更しません。

日次の学習正本は Excel とは別に、各競技の **inbox 日次JSON** です。正規state（`jra_state.json` 等）は日次ジョブから更新しません。

提出用競輪の `マイドライブ / ChatGPT / 競輪学習 / inbox` は、個人予想ジョブからは変更しません。提出用競輪側が完成済みの `prediction_input_YYYY-MM-DD.json` / `prediction_final_YYYY-MM-DD.json` を置くことがあります。

## 対象Excel（ID指定・新規作成しない）

| キー | ファイル名 | Drive ID |
|------|-----------|----------|
| jra_entry | 中央競馬_予想記入シート_2026年9月.xlsx | `1mUCUb2mti2RLoCvfJ-5TooghUZzETKTV` |
| jra_summary | 中央競馬_予想集計シート_2026年9月.xlsx | `16CG5ETf0X-vQHrRUn22w-QpOIREEkydJ` |
| nar_entry | 地方競馬_予想記入シート_2026年9月.xlsx | `1sbXJiVIM6EbYl399UWYmRY0OdP3uyZ6w` |
| nar_summary | 地方競馬_予想集計シート_2026年9月.xlsx | `1ItNNqAkG0pROupUh765tfASQhICkk7nQ` |
| kyotei_entry | 競艇_予想記入シート_2026年9月.xlsx | `10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5` |
| kyotei_summary | 競艇_予想集計シート_2026年9月.xlsx | `1YCv2VU01kMiwN2RzV4PUpCvfdBhIIJvy` |

**触らない**: 個人競輪 Excel、旧 `競馬_予想*.xlsx`、提出用 `競輪予想/`、Chatwork、競輪学習フォルダ

## Drive フォルダ

- フォルダ名: ChatGPT
- URL: https://drive.google.com/drive/folders/1jSFuaBXq3PC0426VPk8Y3DHSZrs70G1f
- 設定: `個人予想/config/drive_excel.json`

### 学習用 inbox（日次JSONの正本）

| 競技 | Driveパス | ファイル |
|------|-----------|----------|
| 中央競馬 | マイドライブ / ChatGPT / 予想学習 / 中央競馬 / inbox | `YYYY-MM-DD.predictions.json` / `YYYY-MM-DD.results.json` |
| 地方競馬 | マイドライブ / ChatGPT / 予想学習 / 地方競馬 / inbox | 同上 |
| 競艇 | マイドライブ / ChatGPT / 予想学習 / 競艇 / inbox | 同上 |

フォルダが無いときは、**保存時に自動作成**します。原田さんが先に手で作る必要はありません。同名ファイルがあるときは更新し、重複作成しません。保存後は必ず再読します。

4:00 の結果処理は、正規stateではなく **前日の predictions.json** を予想の正本にします。部分取得したレース分だけ results.json と Excel を更新できます。

学習JSONの保存に失敗しても、すでに成功した Excel 記入は取り消しません。報告に「学習JSON未保存」と書きます。後からその日の日次JSONだけ穴埋めできます。

## 認証

サービスアカウント方式です。秘密鍵は GitHub Actions の Secret にだけ置きます。

- Secret名: `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`
- リポジトリ・ログ・PR に JSON を書かない
- ローカル（PC版 Cursor）に置く場合は `個人予想/.drive/service_account.json`（gitignore済み）

`PERSONAL_PREDICT_ENABLED=false` でも、手動の `verify-drive` と `bootstrap-cloud` ではサービスアカウントを使えます。

## 正しい実行順（最初の1回）

1. サービスアカウントを作成し、ChatGPTフォルダを編集者で共有する
2. GitHub Secret に `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` を設定する
3. Variable `PERSONAL_PREDICT_ENABLED` を `false` にする
4. PR を main へマージする（定期実行は無効なので 4:00 / 6:00 は動かない）
5. Actions で `verify-drive` を手動実行する（書き込みなし）
6. 必要なら PC版 Cursor で `init-state` を実行する（後からの正規state合成用。日次予想の必須条件ではない。既存があれば上書きせず失敗）
7. 6ファイルの読み取り成功後、**PC版 Cursor** から現在の Excel を一度だけ初期移行する（許可があるまで実行しない）
8. Drive上のExcelを確認する
9. Variable を `true` にする
10. 4:00・6:00 の定期実行を開始する

初期移行は GitHub Actions では行いません。Actions の checkout には、Windows ローカルの Git管理外 state が無いためです。

必要なローカルファイル（PC版 Cursor・初期移行時）:

- `excel/` の最新6ファイル（mainに保存済みのもの）
- あれば `data/jra/state.json` など（日次では使わない。後からの合成用）

開始日は **2026-09-03（JST）** です。`timezone` は `Asia/Tokyo` です。それより前の日付は結果取得・学習の対象外です。9月2日のExcel記録は残します。

`init-state` は3競技のstateを一時ファイルで作って検証し、全部成功したときだけ確定します。途中で失敗したら、この実行で作ったstateは残しません。既存stateは削除・上書きしません。

## クラウド実行の動き

| 日本時間 | UTC cron | 内容 |
|----------|----------|------|
| 毎日 4:00 | `0 19 * * *` | 前日の predictions.json を正本に正式結果・Excel集計・results.json |
| 毎日 6:00 | `0 21 * * *` | 当日の公式出走、最大5レースずつ予想、Excel記入、predictions.json |

開始時に Drive から最新Excelを取得します。正規stateは日次では取得しません。終了時に Excel を保存し、日次JSONを inbox へ保存します。

- 定期実行は `PERSONAL_PREDICT_ENABLED=true` のときだけ動く。未設定または false なら 4:00 / 6:00 は何もしない
- `verify-drive` と `bootstrap-cloud` はスイッチがオフでも手動実行できる
- `verify-drive` は1件でも読めなければ失敗終了する
- Excel の保存が1件でも失敗したら失敗終了する
- 学習JSON（inbox）の保存失敗ではジョブ全体を失敗扱いにしない。報告に「学習JSON未保存」と書く
- Excel は既存IDを更新するだけ。無い場合は作らず失敗にする
- 日々のExcel更新では PR を作らない
- 同時実行は GitHub Actions の concurrency とファイルロックで防ぐ
- 結果が一部だけ取れた日付は処理済みにしない。次回は未取得レースだけ再取得する
- `jra_state.json` / `nar_state.json` / `kyotei_state.json` は日次ジョブから更新・pushしない

## 報告ルール

- Driveへ書けなかった場合は「ローカルのみ更新」と明記する
- 学習JSONだけ失敗した場合は「学習JSON未保存」と明記する
- 成功確認前に Drive更新済みと報告しない
