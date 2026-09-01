# Google Drive 同期（個人予想）

対象は **既存の6つのExcel** です。同名ファイルの新規作成はしません。ID指定で上書きだけします。

学習データ（競技別の state / 学習レポート）は同じフォルダ内の固定名で保存します。Excel 6ファイルとは別に扱います。

## 対象Excel（ID指定・新規作成しない）

| キー | ファイル名 | Drive ID |
|------|-----------|----------|
| jra_entry | 中央競馬_予想記入シート_2026年9月.xlsx | `1mUCUb2mti2RLoCvfJ-5TooghUZzETKTV` |
| jra_summary | 中央競馬_予想集計シート_2026年9月.xlsx | `16CG5ETf0X-vQHrRUn22w-QpOIREEkydJ` |
| nar_entry | 地方競馬_予想記入シート_2026年9月.xlsx | `1sbXJiVIM6EbYl399UWYmRY0OdP3uyZ6w` |
| nar_summary | 地方競馬_予想集計シート_2026年9月.xlsx | `1ItNNqAkG0pROupUh765tfASQhICkk7nQ` |
| kyotei_entry | 競艇_予想記入シート_2026年9月.xlsx | `10qbVsaqW6RfqNgdSdjOmiSF5JEsIK2W5` |
| kyotei_summary | 競艇_予想集計シート_2026年9月.xlsx | `1YCv2VU01kMiwN2RzV4PUpCvfdBhIIJvy` |

**触らない**: 個人競輪 Excel、旧 `競馬_予想*.xlsx`、提出用 `競輪予想/`、Chatwork

## Drive フォルダ

- フォルダ名: ChatGPT
- URL: https://drive.google.com/drive/folders/1jSFuaBXq3PC0426VPk8Y3DHSZrs70G1f
- 設定: `個人予想/config/drive_excel.json`

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
4. PR #8 を main へマージする（定期実行は無効なので 4:00 / 6:00 は動かない）
5. Actions で `verify-drive` を手動実行する（書き込みなし）
6. 6ファイルの読み取り成功後、**PC版 Cursor** から現在の Excel・state・学習データを一度だけ初期移行する
7. Drive上の9月2日Excelと state を確認する
8. Variable を `true` にする
9. 4:00・6:00 の定期実行を開始する

初期移行は GitHub Actions では行いません。Actions の checkout には、Windows ローカルの Git管理外 state が無いためです。

必要なローカルファイル（PC版 Cursor）:

- `excel/` の最新6ファイル（mainに保存済みのもの）
- `data/jra/state.json`
- `data/nar/state.json`
- `data/kyotei/state.json`
- 各学習レポート（あれば送る）

state が1つでも無い場合、初期移行は失敗終了します。成功扱いしません。

## クラウド実行の動き

| 日本時間 | UTC cron | 内容 |
|----------|----------|------|
| 毎日 4:00 | `0 19 * * *` | 前日の正式結果、Excel集計、復習、学習 |
| 毎日 6:00 | `0 21 * * *` | 当日の公式出走、最大5レースずつ予想、Excel記入 |

開始時に Drive から最新Excelと学習データを取得し、終了時に Excel・state・学習を Drive へ保存します。

- 定期実行は `PERSONAL_PREDICT_ENABLED=true` のときだけ動く。未設定または false なら 4:00 / 6:00 は何もしない
- `verify-drive` と `bootstrap-cloud` はスイッチがオフでも手動実行できる
- `verify-drive` は1件でも読めなければ失敗終了する
- Excel または学習データの保存が1件でも失敗したら失敗終了する
- Excel は既存IDを更新するだけ。無い場合は作らず失敗にする
- 日々のExcel更新では PR を作らない
- 同時実行は GitHub Actions の concurrency とファイルロックで防ぐ
- 結果が一部だけ取れた日付は処理済みにしない。次回は未取得レースだけ再取得する

## 報告ルール

- Driveへ書けなかった場合は「ローカルのみ更新」と明記する
- 成功確認前に Drive更新済みと報告しない
