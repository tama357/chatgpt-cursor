# 競輪予想のJSON例

ChatGPTに渡してよいのは、完成済みの正式名だけです。

| 用途 | 正式名 | 作成途中 |
|------|--------|----------|
| ChatGPT入力 | `prediction_input_YYYY-MM-DD.json` | `prediction_input_YYYY-MM-DD.tmp.json` |
| ChatGPT最終予想 | `prediction_final_YYYY-MM-DD.json` | （最終予想に一時ファイルは使わない） |

- 入力例: `chatgpt_input.example.json`（`status=ready` かつ `data_complete=true`。候補全体と `cursor_first_prediction`）
- 最終予想例: `chatgpt_final.example.json`
- 収集テスト用: `races_collect.example.json`

`.tmp.json` だけがある日は未完成です。ChatGPTには渡さないでください。Driveにも置きません。

完成済みの正式名だけを `マイドライブ / ChatGPT / 競輪学習 / inbox` へ同期します。
