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
- ローカルに置く場合は `個人予想/.drive/service_account.json`（gitignore済み）

## 原田さんが最初に1回だけ行う設定

1. Google Cloud でプロジェクトを用意し、**Google Drive API を有効化**する
2. サービスアカウントを作成し、JSON鍵をダウンロードする（中身は開かない・貼らない）
3. ChatGPTフォルダを、サービスアカウントのメールアドレスに **編集者** で共有する
4. GitHub の Settings → Secrets and variables → Actions に `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` を追加し、JSON全文を貼る
5. リポジトリの Actions を有効化する
6. 最初は Actions の手動実行（`workflow_dispatch`）で **verify-drive** だけ走らせる（書き込みなし）
7. 6ファイルの読み取り成功を確認してから、毎日の定期実行を使う

## クラウド実行の動き

| 日本時間 | UTC cron | 内容 |
|----------|----------|------|
| 毎日 4:00 | `0 19 * * *` | 前日の正式結果、Excel集計、復習、学習 |
| 毎日 6:00 | `0 21 * * *` | 当日の公式出走、最大5レースずつ予想、Excel記入 |

開始時に Drive から最新Excelと学習データを取得し、終了時に Excel・state・学習を Drive へ保存します。

- Excel は既存IDを更新するだけ。無い場合は作らず失敗にする
- 学習JSONが未作成なら、初回だけ固定名で保存する（Excelは作らない）
- 日々のExcel更新では PR を作らない
- 同時実行は GitHub Actions の concurrency とファイルロックで防ぐ

## 報告ルール

- Driveへ書けなかった場合は「ローカルのみ更新」と明記する
- 成功確認前に Drive更新済みと報告しない
