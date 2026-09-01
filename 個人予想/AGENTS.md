# 個人予想：Cursor実行ルール（手動入力版）

## 禁止

- Chatwork・メール・Slack・SNS送信
- `競輪予想/` の変更
- Drive `競艇_*.xlsx` の編集・競輪としての利用

## Excel仕様（Drive実ファイル準拠）

### 予想記入シート

- 1か月1シート（`YYYYMM`）
- 1日5行（予想番号1〜5）
- 入力列 A〜N（数式・書式は上書きしない）
- `prediction_score` はExcel列なし → 解説文＋state.jsonへ保存
- `confidence` は D列（自信度）

### 集計シート

- 入力列 P〜T（1本目〜5本目）
- B〜O列は自動計算 → 触らない

## 学習

- 100レース未満: 配点変更なし
- `recommended_weights` は提案のみ

## 報告

CLI出力をCursorチャットへ報告。「処理しました」だけで終わらない。
