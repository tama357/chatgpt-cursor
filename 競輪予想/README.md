# ChatGPT競輪予想運用

Cursor側に実行コードが保存されていなかったため、ChatGPTから同じ案件を再現可能にするための正本と検証ツールをこのディレクトリへ集約した。

## ChatGPTへの依頼

### 当日予想をすべて実行

```text
今日の競輪予想を実行して
```

この依頼で、当日3レースの調査・予想、Google Sheets記入、再読検証、Chatwork送信、送信確認まで行う。それらが完了したあと、当日分の予想JSONを Drive「マイドライブ / ChatGPT / 競輪学習 / inbox」へ `YYYY-MM-DD.predictions.json` として保存し、同じファイルを再読する。学習JSONの保存失敗はSheets記入とChatwork送信の成功を取り消さない。失敗時は完了報告に「学習JSON未保存」と書く。

### 結果を記載

```text
昨日の競輪結果を記載して
```

この依頼で、公式結果確認、予想記入シートの結果欄、予想集計シートのP〜R列、集計値の確認まで行う。それらが完了したあと、対象日の結果JSONを同じinboxへ `YYYY-MM-DD.results.json` として保存し、同じファイルを再読する。学習JSONの保存失敗はSheets更新の成功を取り消さない。失敗時は完了報告に「学習JSON未保存」と書く。

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
- `tools/keirin_drive_state.py`：既存DriveファイルIDの取得と上書き（新規作成しない）。ファイル名・MIMEタイプ・内容の事前検証、空上書き防止を含む
- `requirements.txt`：Drive state機能に必要な外部依存（PyJWT、cryptography）
- `tests/test_keirin_workflow.py`：点数計算・形式・的中判定・Chatwork回帰のテスト
- `tests/test_keirin_state_upsert.py`：state保存の単体テスト（一時ディレクトリのみ）
- `tests/test_keirin_state_drive.py`：6:00と4:00を別実行環境としてDrive経由でつなぐテスト
- `state/state.example.json`：内部学習データの形式例（架空データ）

## 予想適性スコアと内部学習

`prediction_score` はレースの予想しやすさ、`confidence` は作成した買い目への確信度として完全に分離する。締切18:00以降の全候補を100点満点で比較し、上位3レースを採用する。3位が70点未満でも3レースは作成し、内部stateへ `low_quality_day=true` を残す。

本番の6:00は、調査・予想・検証・Sheets記入・Chatwork送信のあと、接続済みDriveのinboxへ当日の `YYYY-MM-DD.predictions.json` を保存する。4:00はSheets結果更新のあと、`YYYY-MM-DD.results.json` を同じinboxへ保存する。`keirin_learning_state.json` はWorkから読まない・書かない。`--drive` は本番では使わない。

`axis` と `close_miss` は、Cursorがinboxを正規stateへ合成するときに既存の `record-predictions` / `record-results` が自動抽出・自動判定する。レポートは初期配点を変更せず、`recommended_weights` として提案だけを出す。

実データの学習JSONはGit管理対象外であり、Google SheetsとChatworkにも出力しない。WorkへサービスアカウントJSONやファイルIDは置かない。既存の鉄板／中穴／大穴、自信度、シート列、Chatwork本文は変更しない。

100R後または週次で、Cursorがinboxの日次JSONを日付順に `record-predictions` / `record-results` へ渡し、正規stateへ合成する。

## ローカル検証

Drive state機能を使う場合は依存関係を先に入れる。

```bash
pip install -r 競輪予想/requirements.txt
```

```bash
python3 競輪予想/tools/keirin_workflow.py validate-predictions 競輪予想/examples/predictions.example.json
python3 競輪予想/tools/keirin_workflow.py format-predictions 競輪予想/examples/predictions.example.json
python3 競輪予想/tools/keirin_workflow.py record-predictions 競輪予想/examples/day_predictions.example.json --state /tmp/keirin-state.json
python3 競輪予想/tools/keirin_workflow.py record-results 競輪予想/examples/results.example.json --state /tmp/keirin-state.json
python3 競輪予想/tools/keirin_workflow.py validate-state 競輪予想/state/state.example.json
python3 競輪予想/tools/keirin_workflow.py build-learning-report 競輪予想/state/state.example.json
python3 -m unittest discover -s 競輪予想/tests -v
```

本番のChatGPT Workでは `--drive` を使わない。inboxの日次JSONを正規stateへ合成するときだけ、Cursorが `--state` 付きの `record-predictions` / `record-results` を使う。

Chatwork実送信には環境変数が必要。トークンとRoom IDは公開リポジトリへ保存しない。

```bash
export CHATWORK_API_TOKEN='...'
export CHATWORK_ROOM_ID='...'
python3 競輪予想/tools/keirin_workflow.py send-predictions 競輪予想/examples/predictions.example.json --confirm-send
```

`--confirm-send` がない場合は送信しない。直近メッセージに同一本文がある場合も送信を止める。
