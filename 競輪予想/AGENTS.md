# 競輪予想：役割分担

Cursorはデータ収集・整理・記録・集計・検証だけを行う。
最終3レースの選定、狙い、買い目、解説は **ChatGPTだけ** が行う。

## 原田さんの操作（Cursorチャットだけ）

| やりたいこと | 伝える文言 |
|--------------|------------|
| 当日データを集める | **「今日の競輪データを集めて」** |
| ChatGPTの最終予想を提出する | **「ChatGPTの最終予想を取り込んで」** |
| 昨日の結果 | **「昨日の競輪結果を記載して」** |

JSON作成とコマンド実行は Cursor が行う。原田さんにコマンド入力はさせない。

1. Cursorが候補5〜10Rの入力JSONを作る
2. そのJSONを ChatGPT に渡す
3. ChatGPTが最終予想JSONを返す
4. そのJSONを Cursor に渡し、「取り込んで」と伝える
5. 最終予想が揃って初めて、既存シートへ転記する

## 正本の優先順位

1. 原田さんまたはクライアントからの最新メッセージ
2. Google Sheets上の現行テンプレート・記入指示
3. このファイルと `current_rules.json`

矛盾を黙って混ぜない。結果に影響する未解決の矛盾があれば実行前に1問だけ確認する。

## 役割

| 担当 | やってよいこと | やってはいけないこと |
|------|----------------|----------------------|
| Cursor | 開催データ収集、prediction_scoreによる候補5〜10R抽出、ChatGPT入力JSON作成、最終予想の転記、再読検証、必要なときだけChatwork、公式結果の結果欄・集計欄更新、学習JSON保存 | 最終3Rの決定、買い目作成、ChatGPT最終予想の独自修正、既存シートの列・行・見出し・数式・書式変更 |
| ChatGPT | 候補JSONだけを見て最終3R・狙い・confidence・本線・抑え・合計点数・解説を決める | シート構造の変更、学習項目のシート追加 |

`prediction_score` は候補を絞るためだけに使う。最終3Rや買い目には使わない。

## 実行トリガー

- 「今日の競輪データを集めて」：収集、候補抽出、ChatGPT入力JSON作成まで。最終予想が無ければここで停止する。
- 「今日の競輪予想を実行して」：上と同じ。最終予想JSONが無い限り、シート転記もChatworkも行わない。Cursorが代わりに予想しない。
- 「ChatGPTの最終予想を取り込んで」：必須項目が揃っているときだけ、既存シートの指定セルへ転記、再読検証、必要ならChatwork、学習用 `YYYY-MM-DD.predictions.json` 保存。
- 「昨日の競輪結果を記載して」：公式結果を確認し、予想記入シートの結果欄と予想集計シートのP〜Rだけを更新。学習JSONへ検証データを保存。
- 「準備して」「確認して」だけでは、シート更新、Chatwork送信、学習JSON保存を行わない。

最終予想に次が欠けている場合は処理を停止する。Cursorは穴埋めしない。

- 選定3レース
- 狙い（鉄板・中穴・大穴）
- confidence（A / B / C）
- 本線
- 抑え
- 合計点数
- 解説

Chatwork送信は明示トリガーと `--confirm-send` がある場合に限り、同一本文を1回だけ送る。車券は購入しない。

本番のWork実行では `record-predictions --drive` / `record-results --drive` / `pull-state` / `push-state` を使わない。`keirin_learning_state.json` はWorkから読まない・書かない。

## 当日のデータ準備（Cursor）

1. 日本時間の対象日を確定する。
2. keirin.jp から開催場、レース番号、締切時刻、出走選手、脚質、級班、直近成績、今場所・前場所、欠場フラグ、オッズ（取れる場合）を集める。取れない項目は null と risk_factors に残す。
3. 締切18:00以降を `prediction_score` で並べ、5〜10レースを候補にする。最終3Rは決めない。
4. `data/inbox/YYYY-MM-DD.chatgpt_input.json` を保存する。形式は `examples/chatgpt_input.example.json`。
5. ここで停止する。買い目もシートもChatworkも触らない。

```bash
python3 競輪予想/tools/keirin_workflow.py prepare-today
```

ネットが使えない検証は `--races-file 競輪予想/examples/races_collect.example.json`。

## ChatGPTへ渡す入力JSON

候補レースごとに、取れた範囲で次を入れる。ChatGPTがこのファイルだけで判断できるようにする。

- race, venue, race_number, deadline, prediction_score
- riders, score, recent_results, line, winning_style, B_count
- current_meeting_results, previous_meeting_results
- odds, risk_factors, source

原田さんが ChatGPT に渡すとき:

1. Cursorが作った `YYYY-MM-DD.chatgpt_input.json` を添付する
2. 「この候補データだけで、今日の最終3レースと買い目をJSONで返して」と伝える
3. 返ってきたJSONを Cursor に渡す

受け取り形式は `examples/chatgpt_final.example.json`。

## 最終予想の取り込み（Cursor）

```bash
python3 競輪予想/tools/keirin_workflow.py ingest-final 競輪予想/data/inbox/YYYY-MM-DD.final.json
```

1. 必須項目を確認する。欠けていれば停止する。
2. 既存の予想記入シートへ、A〜I列とK列の値だけを転記する。J列（合計点数）とL列（Chatwork本文）は自動式なので書かない。
3. 書き込んだセルを再読し、ChatGPTの最終予想と完全一致しているか確認する。一致しなければChatworkしない。
4. 従来どおり必要な場合のみ Chatwork へ送る。本文に内部学習項目は混ぜない。
5. 学習用 `YYYY-MM-DD.predictions.json` を保存し再読する。inbox保存失敗はSheets成功を取り消さない。

タブがなければ「テンプレ」を複製し `YYYY/MM/DD` に改名してから記入する。列・行・見出し・数式・書式は変えない。

## 既存シートを触らない（絶対）

- ファイル名：`原田さん｜予想記入シート` / `原田さん｜予想集計シート`
- 接続済みGoogle Driveから正確なファイル名で探す。ファイルIDはGitへ書かない
- 予想1：2〜16行（主行2）／予想2：17〜31行（主行17）／予想3：32〜46行（主行32）
- 入力：A〜I列とK列
- 自動式を保持：J列、L列
- 結果記入：各主行のM列（三連単結果）、N列（払戻金）、O列（的中／ハズレ）
- 集計の手入力：P〜R列だけ。B〜O列は計算式のため編集しない
- 1日につき3行。先頭行が結果、次行が的中額、3行目が購入点数
- 学習用項目を既存シートに追加しない
- 新しい列追加、列/行削除、見出し変更、数式変更、書式変更は禁止

## 翌朝の結果（Cursor）

```bash
python3 競輪予想/tools/keirin_workflow.py results-yesterday
```

1. 公式結果で対象3レースの三連単着順と払戻金を確認する。取れなければ推測しない。
2. 予想記入シートの当日タブで、M・N・O列へ結果を記載する。
3. 予想集計シートの対象月・対象日のP〜R列だけを更新する。
4. 再読して式の範囲を変えていないことを確認する。
5. 学習用 `YYYY-MM-DD.results.json` と `YYYY-MM-DD.learning.json` を既存の競輪学習inboxへ保存する。シートには書かない。

学習JSONに残す項目:

- prediction_score, confidence, 実際の着順, 的中・不的中, 払戻, 回収率
- 軸の着順, primary_miss_reason, secondary_miss_reasons
- close_miss, scenario_materialized, low_quality_day

## 予想ルール（ChatGPTが守る。Cursorは検証だけ）

- 1日3レース
- 対象は締切18:00以降
- 三連単
- 1レース10点以内
- 的中率を最優先し、回収率100%以上も目標
- 表記例：`4-2-1357`
- 狙い：`鉄板` / `中穴` / `大穴`
- 自信度：`A` / `B` / `C`
- 「確実」「絶対」など保証表現を使わない

## 学習用日次JSON

保存先：マイドライブ / ChatGPT / 競輪学習 / inbox

- 候補入力：`YYYY-MM-DD.chatgpt_input.json`
- 最終予想：`YYYY-MM-DD.final.json`
- 6:00相当：`YYYY-MM-DD.predictions.json`
- 4:00相当：`YYYY-MM-DD.results.json` / `YYYY-MM-DD.learning.json`

競輪スプレッドシートとは別ファイル。シートの列・数式・書式・構造は変更しない。学習JSONはSheetsとChatworkに出さない。

## 正規state（Workからは触らない）

`keirin_learning_state.json` はWorkから読まない・書かない。本番では `--drive` も使わない。

```bash
python3 競輪予想/tools/keirin_workflow.py record-predictions <YYYY-MM-DD.predictions.json> --state <正規state.json>
python3 競輪予想/tools/keirin_workflow.py record-results <YYYY-MM-DD.results.json> --state <正規state.json>
```

selected / selection_rank は ChatGPT が選んだ3レースを表す。スコア上位3件への自動固定はしない。

## Chatwork

- 宛先IDとAPIトークンはGitへ保存せず、`CHATWORK_ROOM_ID` と `CHATWORK_API_TOKEN` を実行環境で使う。
- 送信前に宛先、対象日、3レース分の本文を確認する。
- 同一本文が直近メッセージにあれば重複送信しない。
- 送信後はHTTP 200と `message_id` を確認する。
