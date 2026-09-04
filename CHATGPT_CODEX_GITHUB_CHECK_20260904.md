# ChatGPT Work／Codex GitHub操作の移行確認（2026-09-04）

ChatGPT Work／CodexからGitHub操作を確認した記録です。
今回の操作はCodexデスクトップと接続済みGitHubツールで行い、Cursorは使用していません。

- 対象: `tama357/chatgpt-cursor`
- 基点: `main` / `d79ba67b580754bb586fc7d9a1d83ffb8fe46097`
- テスト用ブランチ: `codex/github-migration-check-20260904-02`
- 確認済み: GitHub認証、リポジトリ読み取り、作業ルール、既存PR、Actions状態、ブランチ作成。
- 本ファイルの追加をコミットし、`main` 向けの未マージPRとして確認する。

変更はこのMarkdownファイルのみです。既存コード・設定・Secrets・スプレッドシート・Google Drive・Chatworkは変更しません。
競輪・競馬・競艇の旧処理、GitHub Actionsの実行・有効化、PRのマージは行いません。

文書用の既存テストはありません。既存の予想処理テストは停止方針に従って実行せず、追加内容と変更差分を確認します。
この確認はGitHub基本操作の検証であり、アプリケーションコードの動作テストやChatGPT Workクラウド環境の検証は含みません。
