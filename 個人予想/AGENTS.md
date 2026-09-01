# 個人予想：Cursor実行ルール

## 原田さんの操作（これだけ）

| やりたいこと | Cursor チャットで伝える文言 |
|--------------|----------------------------|
| 今日の予想 | **「今日の競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成、コマンド入力、Excel 操作は **すべて Cursor が実行**する。原田さんに技術作業をさせない。

## Cursor が自動で行うこと

### 予想（predict-today）

1. 当日の出走情報を確認（netkeiba / boatrace.jp 自動取得。失敗時は Web 調査）
2. 必要なレース JSON を Cursor 側で作成・保存
3. 競馬・競艇から最大5レースずつ選定
4. 三連単予想を作成
5. Excel へ記入
6. 予想内容を分かりやすくチャット報告

内部コマンド（Cursor が実行）:

```bash
python3 個人予想/tools/workflow.py predict-today
```

### 結果確認（results-yesterday）

1. 結果 JSON を Cursor 側で作成
2. Excel 集計へ反映
3. 復習・学習レポート生成
4. 原田さんへチャット報告

内部コマンド（Cursor が実行）:

```bash
python3 個人予想/tools/workflow.py results-yesterday
```

## 自動取得に失敗した場合

Cursor が Web 調査で出走表・結果を確認し、次の保存コマンドを **Cursor 側で** 実行する。

```bash
python3 個人予想/tools/workflow.py save-races keiba /path/to/races.json --date YYYY-MM-DD
python3 個人予想/tools/workflow.py save-races kyotei /path/to/races.json --date YYYY-MM-DD
```

## ChatGPT へ Excel を渡すとき

競馬・競艇の4ファイルの場所は **`個人予想/CHATGPT_EXCEL.md`** を参照。

## 禁止

- Chatwork・メール・Slack・SNS 送信
- `競輪予想/` の変更
- 個人競輪 Excel（`競輪_個人_*.xlsx`）の使用

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

## Google Drive 同期

- 予想・結果確認のたびに `sync-drive` を自動実行
- **Drive へのアップロード成功（md5/size 一致）を確認してから**「Drive更新済み」と報告する
- ローカルのみ更新の場合はその旨を明記
- 設定: `個人予想/DRIVE_SYNC.md` / `個人予想/config/drive_excel.json`
- 認証未設定時: Cursor が Google Drive MCP でアップロード → metadata で検証
- **禁止**: `競輪予想/` の変更、個人競輪 Excel の利用
