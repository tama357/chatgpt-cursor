# 個人予想：Cursor実行ルール

## 原田さんの操作（これだけ）

| やりたいこと | Cursor チャットで伝える文言 |
|--------------|----------------------------|
| 今日の予想 | **「今日の中央競馬と地方競馬と競艇を予想して」** |
| 昨日の結果 | **「昨日の結果を確認して」** |

JSON 作成、コマンド入力、Excel 操作は **すべて Cursor が実行**する。原田さんに技術作業をさせない。

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
- 100レース未満: 配点変更なし
- `recommended_weights` は提案のみ

## Google Drive

- 今回の修正では Drive へアップロードしない
- ローカルの6ファイルへ接続・記入する
- 認証未設定時は「ローカルのみ」と報告する
