# 競輪予想：ChatGPT実行ルール

このディレクトリでは、原田真羽さんの競輪予想案件をChatGPTから実行する。

## 正本の優先順位

1. 原田さんまたはクライアントからの最新メッセージ
2. Google Sheets上の現行テンプレート・記入指示
3. このファイルと `current_rules.json`

矛盾を黙って混ぜない。結果に影響する未解決の矛盾があれば実行前に1問だけ確認する。

## 実行トリガー

- 「今日の競輪予想を実行して」：予想作成、予想記入シート更新、再読検証、Chatwork送信、送信結果確認まで行う。それらが完了したあと、当日分の予想JSONをDriveの学習inboxへ保存し、同じファイルを再読する。inbox保存の成否はSheets記入とChatwork送信の成功を取り消さない。
- 「昨日の競輪結果を記載して」：公式結果を確認し、予想記入シートと予想集計シートを更新、再読検証する。それらが完了したあと、対象日の結果JSONをDriveの学習inboxへ保存し、同じファイルを再読する。inbox保存の成否はSheets更新の成功を取り消さない。
- 「準備して」「確認して」だけでは、予想作成、シート更新、Chatwork送信、学習JSON保存を行わない。

Chatwork送信は上記の明示トリガーがある場合に限り、同一本文を1回だけ送る。車券は購入しない。

本番のWork実行では `record-predictions --drive` / `record-results --drive` / `pull-state` / `push-state` を使わない。`keirin_learning_state.json` はWorkから読まない・書かない。

## 毎朝6:00の予想フロー

1. 日本時間の対象日を確定する。
2. 最新の開催、発走・締切時刻、出走表、並び、選手状態、直近成績、競走得点、脚質、当地適性、天候・風・バンク要因を現在の情報源で確認する。
3. 締切が18:00以降で、展開と軸が比較的読みやすい3レースを選ぶ。
4. 三連単を1レース10点以内で作る。買い目を展開して実数を数える。
5. `tools/keirin_workflow.py validate-predictions` 相当の検査を行う。
6. Google Sheetsの当日タブへ記入する。タブがなければ「テンプレ」を複製し、`YYYY/MM/DD` に改名してから記入する。
7. 書き込んだセルと自動生成されたChatwork本文を再読し、3レース、18:00以降、重複なし、各10点以内、表記、選手番号、合計点数を確認する。
8. L2、L17、L32の完成本文を順番に結合し、Chatworkへ1回送信する。Chatwork本文に内部学習項目（prediction_score、score_breakdown、penalties、axis、close_miss 等）を混ぜない。
9. APIの成功応答と `message_id` を確認する。失敗時は成功扱いにせず、同じ本文を無条件に再送しない。
10. 既存の調査・予想・検証・Sheets記入・Chatwork送信はここまでで完了とする。その後に限り、当日分の予想JSONを接続済みGoogle Driveの学習inboxへ保存する。形式は `examples/day_predictions.example.json` に合わせる。ファイル名は `YYYY-MM-DD.predictions.json`。保存先は「マイドライブ / ChatGPT / 競輪学習 / inbox」。接続済みDriveをフォルダ名とファイル名で検索する。ファイルIDはGitへ書かない。同名ファイルがあるときは新規重複作成せず、そのファイルを更新する。
11. 保存後に同じファイルを再読し、日付、3レース、買い目、各レースの `prediction_score`、本線買い目からaxisを算出できる情報（`tickets` に本線があること）が残っていることを確認する。
12. inbox保存または再読に失敗しても、すでに完了したSheets記入とChatwork送信は取り消さない。完了報告に「学習JSON未保存」と明記する。成功した場合は保存したファイル名を報告する。

## 予想ルール

- 1日3レース
- 対象は締切18:00以降
- 三連単
- 1レース10点以内
- 的中率を最優先し、回収率100%以上も目標
- 荒れやすく軸が不明確なレースをなるべく避ける
- 表記例：`4-2-1357`。カッコ、カンマ、全角数字は使わない
- 狙い：`鉄板` / `中穴` / `大穴`
- 自信度：`A` / `B` / `C`
- 「確実」「絶対」など保証表現を使わない
- 解説は数値・並び・直近内容を根拠に簡潔に書く。ライブ情報を推測で埋めない

## 予想記入シート

- ファイル名：`原田さん｜予想記入シート`
- 接続済みGoogle Driveから上記の正確なファイル名で検索し、メタデータで対象を確定する。ファイルIDは公開リポジトリへ記録しない
- 予想1：2〜16行（主行2）
- 予想2：17〜31行（主行17）
- 予想3：32〜46行（主行32）
- 入力：A〜I列とK列
- 自動式を保持：J列（合計点数）、L列（Chatwork本文）
- 結果記入：各主行のM列（三連単結果）、N列（払戻金）、O列（的中／ハズレ）

既存履歴、数式、入力規則、書式は上書きしない。学習項目をシートへ追加しない。列・数式・書式・構造は変更しない。

## 翌朝4:00の結果記載フロー

1. 公式結果で対象3レースの三連単着順と払戻金を確認する。
2. 予想記入シートの当日タブで、M・N・O列へ結果を記載する。
3. 予想集計シートの対象月・対象日のP〜R列だけを更新する。
4. 結果行へ `的中` / `ハズレ`、次行へ的中額（外れは0）、次行へ購入点数を入れる。
5. 累計・当日の的中率、回収率、予想数、的中数、購入点数、的中額を再読し、式の範囲を変更していないことを確認する。
6. 既存の結果確認・Sheets記入はここまでで完了とする。その後に限り、対象日の結果JSONを接続済みGoogle Driveの学習inboxへ保存する。形式は `examples/results.example.json` に合わせる。ファイル名は `YYYY-MM-DD.results.json`。保存先は6:00と同じ「マイドライブ / ChatGPT / 競輪学習 / inbox」。同名ファイルがあるときは新規重複作成せず、そのファイルを更新する。
7. 保存後に同じファイルを再読し、対象日、3レース、三連単結果、的中／ハズレ、払戻、`primary_miss_reason` / `secondary_miss_reasons`（ハズレ時）が残っていることを確認する。
8. inbox保存または再読に失敗しても、すでに完了したSheets更新は取り消さない。完了報告に「学習JSON未保存」と明記する。成功した場合は保存したファイル名を報告する。

## 予想集計シート

- ファイル名：`原田さん｜予想集計シート`
- 接続済みGoogle Driveから上記の正確なファイル名で検索し、メタデータで対象を確定する。ファイルIDは公開リポジトリへ記録しない
- 月別タブ：`YYYY/MM`
- 手入力可能範囲：P〜R列（今回の3レース分）
- B〜O列は計算式のため編集しない
- 1日につき3行。対象日の先頭行が結果、次行が的中額、3行目が購入点数

## 学習用日次JSON（本番で使う保存）

ChatGPT Workの定期実行は毎回ローカルが空になる。学習データは正規stateではなく、日次JSONとしてDrive inboxへ残す。

- 保存先：マイドライブ / ChatGPT / 競輪学習 / inbox
- 6:00：`YYYY-MM-DD.predictions.json`
- 4:00：`YYYY-MM-DD.results.json`
- 認証は接続済みGoogle Drive。サービスアカウントJSON、`KEIRIN_STATE_DRIVE_FILE_ID`、GitHubトークンはWorkへ置かない
- 競輪スプレッドシートとは別ファイル。シートの列・数式・書式・構造は変更しない
- 学習JSONはSheetsとChatworkに出さない
- 日次JSON保存の失敗は、既存のSheets記入・Chatwork成功を取り消さない。失敗時は完了報告に「学習JSON未保存」と書く

## 正規state（Workからは触らない）

`keirin_learning_state.json` はWorkから読まない・書かない。本番では `--drive` も使わない。

コード上の `record-predictions` / `record-results` / Drive安全策は残してよい。100R後または週次で、Cursorがinboxの日次JSONを既存コマンドで正規stateへ合成する。

```bash
python3 競輪予想/tools/keirin_workflow.py record-predictions <YYYY-MM-DD.predictions.json> --state <正規state.json>
python3 競輪予想/tools/keirin_workflow.py record-results <YYYY-MM-DD.results.json> --state <正規state.json>
```

ローカル検証だけするときは `--state` で一時ファイルを指定し、Driveフラグは付けない。

### コードに残している --drive の注意（本番Workでは使わない）

`pull-state` / `push-state` / `record-* --drive` は、サービスアカウントと `KEIRIN_STATE_DRIVE_FILE_ID` を使う実装である。本番のChatGPT Workでは呼び出さない。誤って使うと、正規stateや別ファイルを対象にする危険がある。

この実装を将来使う場合の検証内容（コード側。Workの日次JSON保存とは別）：

1. ファイル名が `keirin_learning_state.json` であること
2. MIMEタイプが `application/json` または `text/plain`
3. 内容が `version: 1` と配列の `days` を持つ正規stateであること
4. 空のローカルstateで既存Drive履歴を消さないこと

## Chatwork

- 宛先IDとAPIトークンはGitへ保存せず、`CHATWORK_ROOM_ID` と `CHATWORK_API_TOKEN` を実行環境で使う。
- 送信前に宛先、対象日、3レース分の本文を確認する。
- 同一本文が直近メッセージにあれば重複送信しない。
- 送信後はHTTP 200と `message_id` を確認する。
