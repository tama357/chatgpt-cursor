# 競輪予想：ChatGPT実行ルール

このディレクトリでは、原田真羽さんの競輪予想案件をChatGPTから実行する。

## 正本の優先順位

1. 原田さんまたはクライアントからの最新メッセージ
2. Google Sheets上の現行テンプレート・記入指示
3. このファイルと `current_rules.json`

矛盾を黙って混ぜない。結果に影響する未解決の矛盾があれば実行前に1問だけ確認する。

## 実行トリガー

- 「今日の競輪予想を実行して」：予想作成、Driveから内部state取得、内部state保存、Driveへ同じファイルIDを上書き、予想記入シート更新、再読検証、Chatwork送信、送信結果確認まで行う。Drive取得・保存または `record-predictions` が失敗したらシート記入とChatwork送信には進まない。
- 「昨日の競輪結果を記載して」：公式結果を確認し、Driveから内部state取得、内部stateへ結果追記、Driveへ同じファイルIDを上書き、予想記入シートと予想集計シートを更新、再読検証する。Drive取得・保存または `record-results` が失敗したらシート更新には進まない。
- 「準備して」「確認して」だけでは、予想作成、シート更新、Chatwork送信を行わない。

Chatwork送信は上記の明示トリガーがある場合に限り、同一本文を1回だけ送る。車券は購入しない。

## 毎朝6:00の予想フロー

1. 日本時間の対象日を確定する。
2. 最新の開催、発走・締切時刻、出走表、並び、選手状態、直近成績、競走得点、脚質、当地適性、天候・風・バンク要因を現在の情報源で確認する。
3. 締切が18:00以降で、展開と軸が比較的読みやすい3レースを選ぶ。
4. 三連単を1レース10点以内で作る。買い目を展開して実数を数える。
5. `tools/keirin_workflow.py validate-predictions` 相当の検査を行う。
6. 内部stateを既存Google Drive JSON（`KEIRIN_STATE_DRIVE_FILE_ID`）から取得し、予想をupsertし、同じファイルIDを上書きする。ChatGPT Workの定期実行は毎回空の実行環境なので、このDrive往復が必須。終了コード0を確認する。失敗したらここで終了し、Sheets記入とChatwork送信はしない。

```bash
python3 競輪予想/tools/keirin_workflow.py record-predictions <当日JSON> --drive
```

`--drive` は `--from-drive` と `--to-drive` の両方。順序は Drive pull → ローカルupsert → 同じDriveファイルIDへの上書き。Driveの取得または保存が失敗したら後続に進まない。新規Driveファイルは作らない。ファイルIDが未設定なら失敗する。
7. Google Sheetsの当日タブへ記入する。タブがなければ「テンプレ」を複製し、`YYYY/MM/DD` に改名してから記入する。
8. 書き込んだセルと自動生成されたChatwork本文を再読し、3レース、18:00以降、重複なし、各10点以内、表記、選手番号、合計点数を確認する。
9. L2、L17、L32の完成本文を順番に結合し、Chatworkへ1回送信する。Chatwork本文に内部学習項目（prediction_score、score_breakdown、penalties、axis、close_miss 等）を混ぜない。
10. APIの成功応答と `message_id` を確認して完了報告する。失敗時は成功扱いにせず、同じ本文を無条件に再送しない。

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

既存履歴、数式、入力規則、書式は上書きしない。

## 翌朝4:00の結果記載フロー

1. 公式結果で対象3レースの三連単着順と払戻金を確認する。
2. 内部stateを既存Google Drive JSON（`KEIRIN_STATE_DRIVE_FILE_ID`）から取得し、結果をupsertし、同じファイルIDを上書きする。終了コード0を確認する。失敗したらここで終了し、Sheets更新はしない。

```bash
python3 競輪予想/tools/keirin_workflow.py record-results <結果JSON> --drive
```

順序は Drive pull → ローカルupsert → 同じDriveファイルIDへの上書き。Driveの取得または保存が失敗したら後続に進まない。新規Driveファイルは作らない。
3. 予想記入シートの当日タブで、M・N・O列へ結果を記載する。
4. 予想集計シートの対象月・対象日のP〜R列だけを更新する。
5. 結果行へ `的中` / `ハズレ`、次行へ的中額（外れは0）、次行へ購入点数を入れる。
6. 累計・当日の的中率、回収率、予想数、的中数、購入点数、的中額を再読し、式の範囲を変更していないことを確認する。

## 予想集計シート

- ファイル名：`原田さん｜予想集計シート`
- 接続済みGoogle Driveから上記の正確なファイル名で検索し、メタデータで対象を確定する。ファイルIDは公開リポジトリへ記録しない
- 月別タブ：`YYYY/MM`
- 手入力可能範囲：P〜R列（今回の3レース分）
- B〜O列は計算式のため編集しない
- 1日につき3行。対象日の先頭行が結果、次行が的中額、3行目が購入点数

## 内部stateのDrive永続化

ChatGPT Workの定期実行は毎回ローカル `state/state.json` が空になる。前日のstateは既存のGoogle Drive JSONファイルにだけ残す。

- ファイルIDは環境変数 `KEIRIN_STATE_DRIVE_FILE_ID` のみ。Gitへ書かない
- 認証は `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`（個人予想のDrive同期と同じ秘密情報）
- 既存ファイルを `files.update`（uploadType=media の PATCH）で上書きする。毎回新規作成しない
- ファイルIDが無い、取得に失敗、壊れたJSON、保存失敗のいずれかなら終了する。Sheets更新とChatwork送信には進まない
- ローカル検証だけするときは `--state /tmp/keirin-state.json` を使い、Driveフラグは付けない

分割して実行する場合も、失敗したら次へ進まない。

```bash
python3 競輪予想/tools/keirin_workflow.py pull-state --state state/state.json
python3 競輪予想/tools/keirin_workflow.py record-predictions <当日JSON> --state state/state.json
python3 競輪予想/tools/keirin_workflow.py push-state --state state/state.json
```

## Chatwork

- 宛先IDとAPIトークンはGitへ保存せず、`CHATWORK_ROOM_ID` と `CHATWORK_API_TOKEN` を実行環境で使う。
- 送信前に宛先、対象日、3レース分の本文を確認する。
- 同一本文が直近メッセージにあれば重複送信しない。
- 送信後はHTTP 200と `message_id` を確認する。
