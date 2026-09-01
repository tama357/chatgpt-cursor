# Google Drive 同期セットアップ（個人予想）

個人予想の Excel は **ローカル更新後に Google Drive へアップロードし、md5/size が一致することを確認**してから報告します。

## 対象ファイル（4つのみ）

| キー | ファイル名 |
|------|-----------|
| keiba_entry | 競馬_予想記入シート_2026年9月.xlsx |
| keiba_summary | 競馬_予想集計シート_2026年9月.xlsx |
| kyotei_entry | 競艇_予想記入シート_2026年9月.xlsx |
| kyotei_summary | 競艇_予想集計シート_2026年9月.xlsx |

**触らない**: 個人競輪 Excel、`競輪予想/`（提出用）

## Drive フォルダ

- フォルダ名: ChatGPT
- URL: https://drive.google.com/drive/folders/1jSFuaBXq3PC0426VPk8Y3DHSZrs70G1f
- 設定: `個人予想/config/drive_excel.json`

## 認証（いずれか1つ）

### A. サービスアカウント（推奨・自動化向け）

1. GCP でサービスアカウントを作成し、Drive API を有効化
2. JSON キーをダウンロード
3. Drive の ChatGPT フォルダを、そのサービスアカウントのメールアドレスに **編集者** で共有
4. JSON を `個人予想/.drive/service_account.json` に保存（Git に上げない）

### B. OAuth トークン

1. `個人予想/.drive/token.json` に refresh_token 等を保存
2. または環境変数 `GOOGLE_DRIVE_ACCESS_TOKEN` を設定

## コマンド

```bash
python3 個人予想/tools/workflow.py sync-drive
```

`predict-today` / `results-yesterday` / 各 predict・results コマンドの末尾でも自動実行されます。

## 報告ルール

- ✅ Drive の md5/size がローカルと一致 → 「Drive更新成功」と報告可
- ❌ 認証なし・検証失敗 → 「ローカルのみ更新」と明記。Drive更新済みと報告しない
- Cursor が Google Drive MCP でアップロードした場合も、**get_file_metadata で md5/size を確認**してから成功報告

## MCP でアップロードする場合（Cursor）

既存ファイル更新は MCP に update content がないため:

1. `trash_file` で旧ファイルをゴミ箱へ（提出用競輪・個人競輪ファイルは絶対に触らない）
2. `create_file` で同じフォルダ・同じファイル名で xlsx を再アップロード
3. 返却された新 `fileId` を `config/drive_excel.json` に反映
4. `get_file_metadata` で size / md5Checksum をローカルと照合
