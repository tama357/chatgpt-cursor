# ChatGPT競輪予想運用

Cursor側に実行コードが保存されていなかったため、ChatGPTから同じ案件を再現可能にするための正本と検証ツールをこのディレクトリへ集約した。

## ChatGPTへの依頼

### 当日予想をすべて実行

```text
今日の競輪予想を実行して
```

この依頼で、当日3レースの調査・予想、Drive上の内部state取得と上書き、Google Sheets記入、再読検証、Chatwork送信、送信確認まで行う。Drive取得または保存が失敗したらシート記入とChatwork送信はしない。

### 結果を記載

```text
昨日の競輪結果を記載して
```

この依頼で、公式結果確認、Drive上の内部state取得と結果追記・上書き、予想記入シートの結果欄、予想集計シートのP〜R列、集計値の確認まで行う。Drive取得または保存が失敗したらシート更新はしない。

### 外部更新なしで確認

```text
今日の競輪予想を下書きだけ作って。シート記入とChatwork送信はしないで
```

## 標準時刻

- 予想提出：毎朝6:00（日本時間）
- 結果記載：対象レース終了後、標準は翌朝4:00（日本時間）

ここでいう時刻は運用上の締切であり、このリポジトリだけでは自動スケジュールを起動しない。定期実行を有効化するときはChatGPTの自動化を別途作成する。

## ファイル

- `AGENTS.md`：ChatGPTが守る実行順序、シート範囲、送信ルール
- `current_rules.json`：機械可読な最新条件
- `examples/predictions.example.json`：Chatwork本文用の予想入力例（架空データ）
- `examples/day_predictions.example.json`：6:00のstate保存用入力例（スコア・候補付き、架空データ）
- `examples/results.example.json`：結果入力例（架空データ）
- `tools/keirin_workflow.py`：買い目検証、内部stateのupsert、Drive往復、本文生成、Chatwork送信
- `tools/keirin_drive_state.py`：既存DriveファイルIDの取得と上書き（新規作成しない）
- `tests/test_keirin_workflow.py`：点数計算・形式・的中判定・Chatwork回帰のテスト
- `tests/test_keirin_state_upsert.py`：state保存の単体テスト（一時ディレクトリのみ）
- `tests/test_keirin_state_drive.py`：6:00と4:00を別実行環境としてDrive経由でつなぐテスト
- `state/state.example.json`：内部学習データの形式例（架空データ）

## 予想適性スコアと内部学習

`prediction_score` はレースの予想しやすさ、`confidence` は作成した買い目への確信度として完全に分離する。締切18:00以降の全候補を100点満点で比較し、上位3レースを採用する。3位が70点未満でも3レースは作成し、内部stateへ `low_quality_day=true` を残す。

6:00は Drive pull → `record-predictions` → 同じDriveファイルIDへの上書きが成功してからSheets記入とChatwork送信へ進む。4:00は Drive pull → `record-results` → 同じDriveファイルIDへの上書きが成功してからSheets結果更新へ進む。`axis` は本線先頭から自動抽出し、`close_miss` は結果追記時に自動判定する。レポートは初期配点を変更せず、`recommended_weights` として提案だけを出す。

実データの `state/*.json` はGit管理対象外であり、Google SheetsとChatworkにも出力しない。ChatGPT Workの定期実行ではローカルstateが残らないため、既存のGoogle Drive JSON（`KEIRIN_STATE_DRIVE_FILE_ID`）を上書きして引き継ぐ。認証は `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`。ファイルIDと秘密情報はGitへ書かない。既存の鉄板／中穴／大穴、自信度、シート列、Chatwork本文は変更しない。

## ローカル検証

```bash
python3 競輪予想/tools/keirin_workflow.py validate-predictions 競輪予想/examples/predictions.example.json
python3 競輪予想/tools/keirin_workflow.py format-predictions 競輪予想/examples/predictions.example.json
python3 競輪予想/tools/keirin_workflow.py record-predictions 競輪予想/examples/day_predictions.example.json --state /tmp/keirin-state.json
python3 競輪予想/tools/keirin_workflow.py record-results 競輪予想/examples/results.example.json --state /tmp/keirin-state.json

定期実行（ChatGPT Work）は毎回空の実行環境なので、Drive往復付きで1コマンドにする。

```bash
python3 競輪予想/tools/keirin_workflow.py record-predictions 当日.json --drive
python3 競輪予想/tools/keirin_workflow.py record-results 結果.json --drive
```

`--drive` は開始時に既存ファイルを取得し、upsert成功後に同じIDを上書きする。`KEIRIN_STATE_DRIVE_FILE_ID` と `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` が必要。IDが無いときは失敗し、Sheets / Chatwork には進まない。
python3 競輪予想/tools/keirin_workflow.py validate-state 競輪予想/state/state.example.json
python3 競輪予想/tools/keirin_workflow.py build-learning-report 競輪予想/state/state.example.json
python3 -m unittest discover -s 競輪予想/tests -v
```

Chatwork実送信には環境変数が必要。トークンとRoom IDは公開リポジトリへ保存しない。

```bash
export CHATWORK_API_TOKEN='...'
export CHATWORK_ROOM_ID='...'
python3 競輪予想/tools/keirin_workflow.py send-predictions 競輪予想/examples/predictions.example.json --confirm-send
```

`--confirm-send` がない場合は送信しない。直近メッセージに同一本文がある場合も送信を止める。
