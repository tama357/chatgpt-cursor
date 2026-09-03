# 競輪予想（Cursor＝第一予想まで、ChatGPT＝最終確認と送信）

Cursorは開催データの収集・候補抽出・第一予想・記録・検証を行う。
最終確認・最終修正・個人運用シートへの転記は ChatGPT が行う。
Chatworkへの予想提出と結果報告は停止する。
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

自動実行は GitHub Actions です。`keirin-submit` が JST 4:00 結果と JST 6:00 データ収集＋第一予想。完成inputは Artifact `keirin-prediction-input-YYYY-MM-DD` でChatGPTへ渡す。`keirin-ingest` が 7:30〜11:30 に Drive の final を確認し、あれば個人運用シートへ取り込む。Chatworkは送らない。6:00 は最終確定・シート転記・Chatwork を行いません。

## 既存シート

触ってよいのは値の転記だけ。

- 予想記入：A〜I、K（予想）と M〜O（結果）
- 書いてはいけない：J（合計点数の式）、L（Chatwork本文の式）
- 予想集計：P〜R だけ。B〜O は計算式

学習用の項目はシートに足さない。JSONだけに残す。

Chatwork実送信は停止中。`--confirm-send` があっても `CHATWORK_ENABLED=true` が無い限り送らない。
