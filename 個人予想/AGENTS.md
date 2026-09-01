# 個人予想：Cursor実行ルール

原田真羽さん個人利用の競馬・競輪予想システム。`競輪予想/`（提出用）とは触らない。

## 禁止

- Chatwork・メール・Slack・SNS送信
- 自動投票・外部ログイン
- `競輪予想/` 配下の変更
- Google Sheets提出用ファイルの編集

## 実行トリガー

| 依頼 | コマンド |
|------|----------|
| 本日の競馬予想 | `predict-keiba` |
| 本日の競輪予想 | `predict-keirin` |
| 本日の全予想 | `predict-all` |
| 競馬結果・復習 | `apply-results keiba ...` → `results-keiba` |
| 競輪結果・復習 | `apply-results keirin ...` → `results-keirin` |
| 学習レポート | `learning-keiba` / `learning-keirin` |

## Excel書き込み範囲

予想記入シート（入力のみ）: A-P列の予想行、Q-T列の結果行
集計シート（入力のみ）: P-T列（5レース分）、B-O列の数式は触らない

## 学習

- 100レース未満: 履歴収集・傾向分析のみ。配点は変更しない
- `recommended_weights` は提案のみ。原田さん承認前に反映しない

## 報告

CLI出力をCursorチャットへそのまま報告する。「処理しました」だけで終わらない。
