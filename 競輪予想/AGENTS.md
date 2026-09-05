# 競輪予想：Cursor連携停止中

競輪予想の Cursor / GitHub Actions 連携は終了している。現在はChatGPT側の個人運用を前提とし、このリポジトリから競輪の自動処理を行わない。

## 現在のルール

- `keirin-submit` / `keirin-ingest` を実行しない。
- Cursorは開催データ収集、候補抽出、第一予想、最終予想取り込み、結果記載、Sheets書き込み、Chatwork送信、Artifact作成、Drive同期を行わない。
- 競輪関連のGitHub Actionsを手動実行しない。
- 停止確認のためだけに本番処理や広範囲テストを実行しない。
- 既存コード、過去データ、シート、JSON、stateは削除・移動・更新しない。
- Chatworkやその他外部サービスへ送信しない。
- `personal-predict.yml` には触れない。

## 再開

ユーザーが競輪のCursor/GitHub連携再開を明示した場合だけ、その時点の目的と運用方式を確認して再設計する。

停止前の役割分担、Artifact、Drive inbox、旧トリガー、旧コマンドを現行ルールとして扱わない。必要になった情報だけREADME・コード・履歴から確認する。
