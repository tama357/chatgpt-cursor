# 個人予想：停止中

中央競馬・地方競馬・競艇の Cursor / GitHub Actions 運用は **2026-09-04 から停止中**。

## 現在のルール

- `PERSONAL_PREDICT_ENABLED=false` を維持する。
- `personal-predict.yml` の定期実行・手動実行を行わない。
- Cursorは予想作成、結果取得、Excel更新、Drive同期、inbox JSON、state更新、学習レポート生成を行わない。
- `verify-drive`、`bootstrap-cloud`、`ingest-inbox` など停止前の運用コマンドも実行しない。
- 既存コード、Excel、JSON、state、Drive上のファイルは削除・移動・更新しない。
- Chatwork、メール、Slack、SNSへ送信しない。
- 提出用競輪には触れない。

## 再開

ユーザーが個人予想運用の再開を明示した場合だけ、現状のコード・README・Drive構成をその時点で確認し、新しい運用方針を作る。

停止前の古い手順をそのまま再利用しない。再開時は、必要な資料だけ読んで現在の仕様を確認する。
