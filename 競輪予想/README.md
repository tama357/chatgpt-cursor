# 競輪予想（Cursor＝第一予想まで、ChatGPT＝最終確認と送信）

Cursorは開催データの収集・候補抽出・第一予想・記録・検証を行う。
最終確認・最終修正・シート転記・Chatwork送信は ChatGPT が行う。
既存のGoogleスプレッドシートの構造は変えない。

## 原田さんの使い方（チャットのみ）

| やりたいこと | Cursor チャット |
|--------------|-----------------|
| 当日データを集める | **「今日の競輪データを集めて」** |
| 最終予想を提出する | ChatGPTのJSONを渡して **「ChatGPTの最終予想を取り込んで」** |
| 昨日の結果 | **「昨日の競輪結果を記載して」** |

### ChatGPTに渡す手順

1. Cursorが完成したら `prediction_input_YYYY-MM-DD.json` を作る（候補全体＋第一予想。途中は `.tmp.json`）
2. 完成済み（`status=ready` かつ `data_complete=true`）だけを GitHub Actions Artifact `keirin-prediction-input-YYYY-MM-DD` へ保存する。中身は正式名のJSONだけ。`.tmp.json` は入れない
3. ChatGPTはArtifact上の正式名を読み、第一予想を最終確認・修正する。Driveへのinput新規作成は当面使わない
4. ChatGPTの完成版 `prediction_final_YYYY-MM-DD.json` を同じinboxへ置く。Cursorは内容を補正しない
5. 必須項目（選定3レース・狙い・confidence・本線・抑え・合計点数・解説）が揃い、機械的検証を通ったときだけ転記する。検証エラーは直さず停止し、Driveにも出さない

入力例: `examples/chatgpt_input.example.json`  
最終予想例: `examples/chatgpt_final.example.json`

6:00のCursorは第一予想までで止める。最終予想が無いとき、シート転記もChatworkも行わない。

## 標準時刻

- データ準備：毎朝6:00（日本時間）
- 結果記載：対象レース終了後、標準は翌朝4:00（日本時間）

自動実行は GitHub Actions です。`keirin-submit` が JST 4:00 結果と JST 6:00 データ収集＋第一予想。完成inputは Artifact `keirin-prediction-input-YYYY-MM-DD` でChatGPTへ渡す。`keirin-ingest` が 7:30〜11:30 に Drive の final を確認し、あれば取込とChatwork送信。6:00 は最終確定・シート転記・Chatwork を行いません。

## ファイル

- `AGENTS.md`：役割分担、シート範囲、送信ルール
- `current_rules.json`：機械可読な最新条件。`prediction_score` は候補抽出の参考。第一予想でも上位3Rへ機械固定しない
- `examples/chatgpt_input.example.json`：ChatGPTへ渡す候補全体＋第一予想（`status=ready`）
- `tools/keirin_first_prediction.py`：Cursor第一予想。最終ではない
- `examples/chatgpt_final.example.json`：ChatGPTから受け取る最終予想（スコア4位を選ぶ例を含む）
- `examples/README.md`：正式名と一時ファイルの見分け方
- `examples/races_collect.example.json`：ネット無しの収集テスト用
- `examples/predictions.example.json`：Chatwork本文用
- `examples/day_predictions.example.json`：学習inbox用
- `examples/results.example.json`：結果入力例
- `tools/keirin_workflow.py`：検証、state、Chatwork、当日フローの入口
- `tools/keirin_cursor_flow.py`：収集・候補抽出・第一予想・最終予想取り込み・結果
- `tools/keirin_sheets.py`：指定セルへの値転記と再読。列追加はしない
- `tools/keirin_drive_inbox.py`：完成済み当日JSONだけを競輪学習inboxへ同期。tmpと学習stateは出さない
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

`predict-today` は互換用。中身は収集・候補抽出・第一予想であり、最終予想が無ければ停止する。

Chatwork実送信には `--confirm-send` と環境変数が必要。トークンは公開リポジトリへ保存しない。
