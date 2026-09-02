# 競輪予想（Cursor＝データ、ChatGPT＝最終予想）

Cursorは開催データの収集・候補抽出・記録・検証だけを行う。
最終3レースと買い目は ChatGPT が決める。既存のGoogleスプレッドシートの構造は変えない。

## 原田さんの使い方（チャットのみ）

| やりたいこと | Cursor チャット |
|--------------|-----------------|
| 当日データを集める | **「今日の競輪データを集めて」** |
| 最終予想を提出する | ChatGPTのJSONを渡して **「ChatGPTの最終予想を取り込んで」** |
| 昨日の結果 | **「昨日の競輪結果を記載して」** |

### ChatGPTに渡す手順

1. Cursorが完成したら `競輪予想/data/inbox/prediction_input_YYYY-MM-DD.json` を作る（途中は `.tmp.json`）
2. **正式名だけ**を ChatGPT に添付する。`.tmp.json` は渡さない
3. 「この候補データだけで、今日の最終3レースと買い目をJSONで返して」と伝える
4. 返ってきたJSONを `prediction_final_YYYY-MM-DD.json` として Cursor に渡す
5. 必須項目（選定3レース・狙い・confidence・本線・抑え・合計点数・解説）が揃い、機械的検証を通ったときだけ転記する。検証エラーは直さず停止する

入力例: `examples/chatgpt_input.example.json`  
最終予想例: `examples/chatgpt_final.example.json`

最終予想が無いとき、Cursorは予想も買い目も作らず停止する。

## 標準時刻

- データ準備：毎朝6:00（日本時間）
- 結果記載：対象レース終了後、標準は翌朝4:00（日本時間）

このリポジトリだけでは自動スケジュールを起動しない。

## ファイル

- `AGENTS.md`：役割分担、シート範囲、送信ルール
- `current_rules.json`：機械可読な最新条件。`prediction_score` は候補抽出専用
- `examples/chatgpt_input.example.json`：ChatGPTへ渡す候補データ（`status=ready`）
- `examples/chatgpt_final.example.json`：ChatGPTから受け取る最終予想（スコア4位を選ぶ例を含む）
- `examples/README.md`：正式名と一時ファイルの見分け方
- `examples/races_collect.example.json`：ネット無しの収集テスト用
- `examples/predictions.example.json`：Chatwork本文用
- `examples/day_predictions.example.json`：学習inbox用
- `examples/results.example.json`：結果入力例
- `tools/keirin_workflow.py`：検証、state、Chatwork、当日フローの入口
- `tools/keirin_cursor_flow.py`：収集・候補抽出・最終予想取り込み・結果
- `tools/keirin_sheets.py`：指定セルへの値転記と再読。列追加はしない
- `tests/test_keirin_role_split.py`：役割分担とガードのテスト

## 既存シート

触ってよいのは値の転記だけ。

- 予想記入：A〜I、K（予想）と M〜O（結果）
- 書いてはいけない：J（合計点数の式）、L（Chatwork本文の式）
- 予想集計：P〜R だけ。B〜O は計算式

学習用の項目はシートに足さない。JSONだけに残す。

## ローカル検証

```bash
python3 競輪予想/tools/keirin_workflow.py prepare-today --date 2099-01-01 --races-file 競輪予想/examples/races_collect.example.json
python3 競輪予想/tools/keirin_workflow.py ingest-final 競輪予想/examples/chatgpt_final.example.json --date 2099-01-01 --skip-sheets
# 完成済み入力は prediction_input_日付.json 。tmp は未完成。
python3 競輪予想/tools/keirin_workflow.py results-yesterday --date 2099-01-01 --results-file 競輪予想/examples/results.example.json --skip-sheets
python3 競輪予想/tools/keirin_workflow.py validate-predictions 競輪予想/examples/predictions.example.json
python3 -m unittest discover -s 競輪予想/tests -v
```

`predict-today` は互換用。中身は収集と候補抽出であり、最終予想が無ければ停止する。

Chatwork実送信には `--confirm-send` と環境変数が必要。トークンは公開リポジトリへ保存しない。
