# 個人予想：Cursor実行ルール

**運用停止（2026-09-04）。** `PERSONAL_PREDICT_ENABLED=false`。

中央競馬・地方競馬・競艇の Cursor / GitHub Actions 運用は終了した。
Cursorは予想作成・結果取得・Excel更新・Google Drive同期・inbox JSON作成・state合成・学習レポート生成を行わない。
`personal-predict.yml` は無効。毎日 4:00 の results-yesterday と 6:00 の predict-today は動かない。手動実行もしない。
コード・Excel・JSON・state・Drive上の既存ファイルは残す。競輪には触れない。Chatwork・メール・Slack へは送らない。
原田さんが明示的に再開を指示するまで、この停止を維持する。

以下は停止前の記録である。
