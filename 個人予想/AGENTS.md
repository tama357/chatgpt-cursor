# 個人予想：Cursor実行ルール

## 原田さんの操作（これだけ）

| やりたいこと | Cursor チャットで伝える文言 |
|--------------|----------------------------|
| 今日の予想 | **「今日の中央競馬と地方競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成、コマンド入力、Excel 操作は **すべて Cursor が実行**する。原田さんに技術作業をさせない。

## 2026-09-03 からの開始

予想・結果・集計・復習・学習の開始日は **2026-09-03（日本時間）** です。それより前の日付は結果取得にも学習にも使いません。9月2日のExcel記録はそのまま残します。

初回だけ、確認フラグ付きの初期化コマンドで3競技の state を作ります。手作業で空JSONは作りません。既存 state があるときは上書きせず失敗します。

```bash
python3 個人予想/tools/workflow.py init-state --start-date 2026-09-03 --i-confirm-init-state
```

このコマンドは Excel・Drive・提出用 `競輪予想/` を変更しません。3競技とも成功するか、1つも残さないかのどちらかです。既存stateは上書きしません。

## Cursor が自動で行うこと

### 予想（predict-today）

1. 中央競馬は JRA 開催日のみ出走を確認（netkeiba）
2. 地方競馬は NAR 開催から最大5レース選定
3. 競艇は boatrace.jp から最大5レース選定
4. それぞれ三連単予想を作成し、対応する Excel へ記入
5. 予想内容を分かりやすくチャット報告

内部コマンド:

```bash
python3 個人予想/tools/workflow.py predict-today
```

### 結果確認（results-yesterday）

1. 3区分それぞれに結果 JSON を作成
2. 各 Excel 集計へ反映
3. 復習・学習レポートを競技ごとに生成（混ぜない）
4. 原田さんへチャット報告

```bash
python3 個人予想/tools/workflow.py results-yesterday
```

## 自動取得に失敗した場合

```bash
python3 個人予想/tools/workflow.py save-races jra /path/to/races.json --date YYYY-MM-DD
python3 個人予想/tools/workflow.py save-races nar /path/to/races.json --date YYYY-MM-DD
python3 個人予想/tools/workflow.py save-races kyotei /path/to/races.json --date YYYY-MM-DD
```

## 禁止

- Chatwork・メール・Slack・SNS 送信
- `競輪予想/` の変更
- 個人競輪 Excel の使用
- 中央競馬と地方競馬の成績・学習データの混在

## Excel仕様

- ファイルは6つ（中央競馬・地方競馬・競艇 × 記入／集計）
- 1か月1シート（`202609`〜`202708`）
- 1日5行（予想番号1〜5）
- 集計シートの B〜O 列は数式（触らない）

## 学習

- 競技ごとに `data/{jra,nar,kyotei}/state.json` と `learning_report.json`
- `start_date`（既定 2026-09-03 JST）より前の記録は学習しない
- 100レース未満: 配点変更なし
- `recommended_weights` は提案のみ

## Google Drive / GitHub Actions

- 認証はサービスアカウント。秘密鍵は GitHub Secret `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` のみ
- 定期実行は Variable `PERSONAL_PREDICT_ENABLED=true` のときだけ
- `verify-drive` と `bootstrap-cloud` はスイッチがオフでもサービスアカウントを使う
- 既存6 Excel は ID指定で更新する。同名ファイルは新規作成しない
- 開始時に Drive から Excel と学習データを取得し、終了時に保存する
- Drive取得直後に3競技の正規state（開始日 2026-09-03 JST）を確認する。無ければ出走取得・Excel更新・Drive保存をしない
- 学習データは `data/jra`・`data/nar`・`data/kyotei` で分離する
- 日々のExcel更新では PR を作らない
- 最初の確認は `verify-drive`（読み取りのみ。失敗したら終了コード1）
- 初期移行は PC版 Cursor から行う。GitHub Actions に state が無ければ失敗終了する
- 初期移行は原田さんの許可があるまで実行しない
- 詳細は `個人予想/DRIVE_SYNC.md`
