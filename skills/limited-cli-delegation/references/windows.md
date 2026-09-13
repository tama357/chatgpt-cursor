# Windowsでの呼び出し・同期

## 起動

PowerShell 7が必要。インストール済みスキルの場所を実際の一覧から取得する。例の `$skillRoot` と `$requestPath` は確認済みの絶対パスに置き換える。

```powershell
$taskId = '現在の会話ID/今回の作業名' # 同じタスクの続きでは同じ値
& (Join-Path $skillRoot 'scripts/Invoke-Cursor.ps1') -PromptFile $requestPath -TaskId $taskId -ContentReviewed -TimeoutSeconds 180
$exitCode = $LASTEXITCODE
# 必要な場合だけ、Cursor終了・確認後に同じTaskIdでGeminiを呼ぶ。
& (Join-Path $skillRoot 'scripts/Invoke-Gemini.ps1') -PromptFile $requestPath -TaskId $taskId -ContentReviewed -TimeoutSeconds 180
```

実際には必要な1行だけ実行する。応答JSONを受け取るために同じスクリプトを再実行しない。実行ツールの継続IDが返ったら、そのIDで出力を待つ。

入力はUTF-8ファイルから読み取り、ネイティブプロセスへ `ProcessStartInfo.ArgumentList` で渡す。シェル文字列や `cmd /c` を組み立てない。日本語・改行・引用符・`$()`・バッククォートをコマンドとして解釈しない。最大12,000 UTF-16コード単位（通常の日本語約12,000字）。Windows引数長の保守的な上限も検査し、超過は切捨て・分割送信せず停止する。長文は親が必要範囲へ絞る。標準入力を閉じ、権限確認等で待ち続けた場合も期限で停止する。

## 確認するJSON

共通の `provider / ok / error / response` と、CLIを実行できた場合の `exit_code / json_parsed / stderr_present` を返す。元のJSON全体、アカウントID、セッションID、標準エラー本文は返さない。

| CLI | 成功判定 |
| --- | --- |
| Gemini（既存agy） | 終了0、`status` が文字列 `SUCCESS`、`response` が空でない文字列 |
| Cursor | 終了0、`type=result`、`subtype=success`、`is_error` がboolean false、`result` が空でない文字列 |

タイムアウトはプロセスツリーを停止して失敗扱い。Cursorの`--print`だけで安全とは判断せず、確認済み`--mode ask`、作業コピー内のShell/Read/Write/WebFetch/MCP拒否、子CLI向け禁止指示を組み合わせる。Geminiの既存プロンプトによるツール禁止を継承し、ローカルhelpで確認した`--mode plan`と`--disable-slash-commands`を追加する。双方の禁止指示と環境変数は再委任の防止策だが、任意の子ツールまでOSで完全に遮断したとの保証ではない。

## 失敗コード

| コード | 対応 |
| --- | --- |
| `NOT_CONFIGURED` / `CLI_NOT_FOUND` | 該当CLIだけ未設定として報告。導入・認証し直さない |
| `PROVIDER_DISABLED` | 安全性や往復の確認不足により無効。設定値だけを変えて迂回しない |
| `GLOBAL_STOPPED` | 以前の子プロセス停止が未確認。TaskIdを変えても委任しない |
| `CONTENT_REVIEW_REQUIRED` / `SENSITIVE_INPUT` | 親が原稿の情報制約を確認。検出器は個人情報全般を判定できない |
| `EMPTY_INPUT` / `INPUT_TOO_LONG` | 入力が空、12,000単位超、またはWindows引数上限。勝手に分割送信しない |
| `BUSY` / `RECURSION_BLOCKED` | 同時実行または子CLIからの呼出しを拒否。再試行しない |
| `ATTEMPT_LIMIT` / `TASK_STOPPED` / `INVALID_STATE` | 回数上限・失敗済み・記録不整合。記録やTaskIdを変えて迂回しない |
| `CLI_EXIT_NONZERO` | 認証・制限・権限などCLI側失敗。既存CLIの状態を必要範囲で読み取り確認し、理由不明なら不明と報告 |
| `AUTH_REQUIRED` / `PERMISSION_REQUIRED` / `USAGE_LIMIT` / `CONNECTION_FAILED` / `CLI_CONFIGURATION_ERROR` | 標準エラーを固定分類できた場合の理由。生ログは返さない。認証・権限・課金等を勝手に変えない |
| `INVALID_JSON` / `INVALID_SCHEMA` / `SENSITIVE_OUTPUT` | 応答を採用せず停止 |
| `EMPTY_OUTPUT` / `EMPTY_RESPONSE` / `SERVICE_FAILURE` | stdout空・回答空・CLIが返したサービス側失敗を区別して停止 |
| `TIMEOUT` / `PIPE_TIMEOUT` / `TERMINATION_FAILED` | 期限超過・出力管の終了不明・停止失敗。処理完了と扱わない |
| `LOCAL_FAILURE` / `START_FAILED` / `OUTPUT_TOO_LARGE` | ローカル起動・I/O等の異常。生ログや原稿を公開せず調べる |

状態は `%LOCALAPPDATA%/CodexCliDelegation` に保存。全CLI共通ファイルロックを保持し、プロセス起動前にTaskIdのSHA-256と回数だけを記録する。失敗・クラッシュは停止状態を維持する。原稿はGit外の一意な作業コピーに置く。CLI自身の履歴・ログ保存もあり得るため、保存を避ける必要のある情報は入力しない。APIキー類の環境変数は子プロセスに渡さず、既存ログインを使う。

標準出力・標準エラーは各200万文字までメモリへ保持し、それを超えた分は読み捨てる。超過した回答を採用せず `OUTPUT_TOO_LARGE` を返す。期限とプロセスツリー停止は別に適用する。停止未確認時は全タスク共通の停止記録を残す。

## 配置・更新・新しい会話

正本は `tama357/chatgpt-cursor` の `skills/limited-cli-delegation/`。自動探索対象の `.agents/skills` には正本を置かず、ユーザーの `~/.agents/skills/limited-cli-delegation` へ1か所だけコピーする。`.codex/skills`等の同名登録を見つけたら止め、重複を作らない。

リポジトリの `scripts/Sync-CliDelegation.ps1` に確認済みRepositoryRootとCLI実体を指定する。同期元・ファイルハッシュの記録で管理下ファイルのみ更新し、手編集・別登録の衝突を検出する。ユーザー共通 `~/.codex/AGENTS.md` は管理マーカー内の入口だけ更新し、他の本文・config.toml・既存スキル・認証設定を保持する。

初期設定の `cursor_enabled` / `gemini_enabled` はfalse。2026-09-13の登録では、Cursorは試行が終了1で失敗、Geminiは文章往復成功だが不要なシェル・フック等の十分な制限が未確認のため、双方無効で配置する。GeminiのMCP一覧は設定なしだったが、これだけでツール全般の制限を確認したとは扱わない。解除には不足する制限・往復を確認し、今回の上限後に追加の推論テストをする場合は新たな明示許可を得る。生ログを出さず固定エラー分類で原因を調べる。

同期後、新しいCodexの会話を任意の作業フォルダーで開始する。スキル一覧の `limited-cli-delegation` と共通AGENTSの入口が読み込まれる。表示されない場合はCodexを再起動する。確認には「今回使えるスキル一覧にlimited-cli-delegationがあるかと、委任上限を確認して。CLIは呼ばない」を使える。スキルの自動選択が可能でも毎回委任することはない。

main未マージの間は、同期に使用した作業ブランチ・コミットがPC配置の正本。元のmain作業コピーを同期元に変えるとファイルが存在しない場合がある。対象PRが承認・マージされた後、正しいremoteと未コミット変更を確認してmainを更新し、同スクリプトへ更新後のRepositoryRootを指定して再同期する。マージは自動実行しない。

## 無効化・元に戻す

CLIのみ止める場合は、インストール先のGit追跡外 `runtime.local.json` の該当 `*_enabled` をfalseにする。同期はこの設定値を保持する。スキルの自動選択も止める場合は、Codex公式の `[[skills.config]]` にインストール済みSKILL.mdの絶対パスと `enabled = false` を追加し、Codexを再起動する。既存config全体を置き換えない。

入口を戻す場合は共通AGENTS内の `limited-cli-delegation:start/end` の管理区間だけを除く。今回の保存前本文はインストール先 `AGENTS.before-install.local.txt` にあるが、後から追加された無関係な指示を消さないよう、ファイル全体を戻さない。削除や設定変更を実行するときは対象の明示承認に従う。失敗回数・停止記録を消して呼出し上限をリセットしない。今回、無効化用のconfig.toml変更や削除は実行していない。

参照： [Codexのスキル配置](https://learn.chatgpt.com/docs/build-skills)、[Cursor JSON](https://cursor.com/docs/cli/reference/output-format)、[Cursor権限](https://cursor.com/docs/cli/reference/permissions)。起動オプションは一般例より実機のhelpを優先する。
