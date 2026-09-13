# Cursor / Gemini CLI限定委任の登録・検証

更新：2026-09-13。対象はWindowsのローカルCLIへアクセスでき、このユーザー共通スキルを読み込むCodex環境。他の端末・クラウド・すべてのChatGPT会話への適用を意味しない。

## 現在の状態

方針・呼び出し入口・同期方法は実装した。**自動委任は双方無効**。Cursorは今回の試行が失敗し、Geminiは文章の往復に成功したが、追加指示が求める不要なシェル実行・フック等の十分な制限は未確認。制限を確認できないCLIを有効化しないという指示を優先する。

| 項目 | 状態・根拠 |
| --- | --- |
| リポジトリ保存 | 新規 `feat/limited-cli-delegation-20260913` ブランチ。保存コミット・PRはGitの履歴で確認する |
| PCへの配置 | `%USERPROFILE%/.agents/skills/limited-cli-delegation` へコピー。共通AGENTSへ管理区間だけ追加 |
| ルールの読み込み | Codexの `skills/list` がリポジトリ内外の2か所でuserスコープ・enabled trueのスキルを1件検出、読み込みエラー0。新しい会話の実適用は未確認。CLIの有効フラグとは別 |
| Cursor往復 | 確認1回、終了1・JSON未取得・回答なし。成功往復と品質確認は未完了 |
| Gemini往復 | 確認1回、終了0・JSON成功・回答取得・親側の文章照合に成功。自動委任の安全条件確認とは別 |
| mainへの反映 | 未実施。mainへ直接pushせず、対象PRの承認後にのみマージ |

## 対象の特定と保護

実際のWindows上のファイルを読み、CLIを実行した。元のGitルートは `%USERPROFILE%/chatgpt-cursor`、remoteは `https://github.com/tama357/chatgpt-cursor.git`。元はmainで、未追跡のルール・原稿関連ファイル等があった。別の保存場所へ推測で変更したり、代わりのcloneを作成したりしていない。

確認済みorigin/main `8770c686d0240f145b0113e0df207bee37358f0d` から独立したGit worktreeと新規ブランチを作成。元のmain作業コピーと既存の別worktreeには変更を適用していない。個人予想・競輪予想・関連Workflowは変更・実行していない。

実行ユーザーのUserProfileとWindowsが返すホームが一致することを確認した。Codex CLIは `0.154.0-alpha.6.2`。今回のシェルで `CODEX_HOME` 環境変数は未設定だったため、実際に既存共通AGENTS・スキルが存在した `%USERPROFILE%/.codex` と、Codex自身による探索結果を確認して配置した。共通スキルの配置先は公式のユーザースコープ `~/.agents/skills`。

## 再利用元と互換性

既存の `%USERPROFILE%/agy-test/Invoke-Gemini.ps1` と `README-Gemini.md` を実際に読み、保持した。別製品の `gemini` コマンドへ置き換えていない。

| 元ファイル | SHA-256 |
| --- | --- |
| Invoke-Gemini.ps1 | `BF7F60A07551E22B7AA30713F5BB570AEE368C4354187CD36B4944E0960C057E` |
| README-Gemini.md | `8652554483BC926F841D592B516E5EF4EFE30A1994805F6BFEC23EC7B2AB67AA` |

引き継いだ実装は、既存agyへの `-p TEXT --output-format json`、ツールを使わず文章だけ返す指示、終了0・`status=SUCCESS`・空でない文字列`response`の成功条件、生のアカウント情報を返さない出力選別。新しい入口では `-Prompt` を直接渡す方法をUTF-8の `-PromptFile` に置き換え、共通の回数記録・直列ロック・期限・独立したstdout/stderr・出力上限を追加した。元ファイルの `-Prompt` 利用は変更していない。

PC固有の実体パスは配置先の `runtime.local.json` に分離。Cursorは実機の `agent.ps1` を読み、実体が `cursor-agent/versions/2026.09.10-fd3934a/node.exe` と同ディレクトリの `index.js` であると確認した。versionは `2026.09.10-fd3934a`、helpでprint/json/ask/workspaceを確認し、推論を行わないstatusは終了0・ログイン済み（アカウント情報は出力していない）。認証ファイルは読み取り・コピーしていない。

## 実サービスの確認（今回全体で2回）

同じTaskIdでGemini、終了を確認した後にCursorを直列実行した。help/version/status/MCP一覧とオフラインテストは推論回数に含めない。以後、サービスは再実行していない。

Geminiへは「本機能を活用することにより、作業時間を短縮することが可能です。」という架空の短文だけを送った。返答は「この機能を使えば、作業時間を短縮できます。」。終了0、成功JSON、回答取得を確認し、親が手段・時間短縮・可能表現の意味を原文と照合した。stderrは存在したが、生内容は保存・公開していない。過去の既存経路の成功とは別に、今回の共通入口経由で確認した結果である。

Cursorへは架空の `function add(a, b) { return a - b; }` の修正案だけを依頼。元の作業ツリーではなく必要なテキストと禁止指示だけのコピーで、`--print --mode ask --output-format json --workspace ...` を使用した。終了1、stderrあり、JSON・回答なし。実際の原因は未特定。試行時のstderr本文を保存しなかったため、認証・信頼確認・接続等のいずれかと断定していない。後のローカル修正では固定エラー分類を追加したが、実サービスの再確認はしていない。

Cursorの作業コピーにはShell/Read/Write/WebFetch/MCPの拒否設定を置いた。グローバル設定はallowlistだった。Cursorの共通フォルダーには通常のhooks.json / mcp.jsonは見つからなかったが、PluginやCLI内部を含むすべての起動経路を遮断できたとの保証ではない。Geminiの `mcp list` は終了0で設定なし。planモードとslash展開停止、禁止プロンプト、再帰ガードも使用したが、これだけで不要なシェル・フック等を十分に制限できたとは確認できない。両CLIとも新しい安全条件に従い無効で保存する。

## ローカル検証

`tests/Test-CliDelegation.ps1` の50項目が成功。実サービス・予想処理を使わず、構文、日本語長文・改行・引用符等の引数受け渡し、CLIごとに異なるJSON、非0終了・サービス失敗・空回答、期限と過大出力、回数記録、同時実行拒否、再帰拒否、無効フラグ、同期の重複防止・手編集保護を確認した。

別PowerShellから共通入口を呼ぶテストで、外側の出力がWindows既定エンコーディングになる問題を検出し、JSON出力もUTF-8に固定して修正した。最終スクリプトはローカルテストで確認し、不要な実サービス再テストはしていない。

skill-creatorのquick_validateは同梱PythonにPyYAMLがなく実行できなかった。依存を新規導入せず、Codex自身のスキル探索・パースがエラー0で通ることを確認した。新しい会話の動作や利用量・費用の改善を測定したものではない。

## 配置・更新

正本は `skills/limited-cli-delegation`。リポジトリの自動探索対象 `.agents/skills` には同名登録を置かない。共通側はコピーなので、Gitのブランチを切り替えるだけではPCに配置済みの内容は変わらない。

```powershell
# RepositoryRootはremote・ブランチ・差分を確認した正本の絶対パス。
# CLI実体は実機の確認済みパスを指定する。更新時は省略すると既存設定を保持する。
& ./scripts/Sync-CliDelegation.ps1 -RepositoryRoot $verifiedRepositoryRoot `
  -CursorNode $verifiedCursorNode -CursorEntry $verifiedCursorEntry -GeminiExe $verifiedAgyExe
```

インストール先の `sync-manifest.local.json` に配置元のコミット・正本パス・管理ファイルのSHA-256と `source_dirty` を保存する。正式な配置ではコミット後に同期し `source_dirty=false` を確認する。未マージの作業ブランチからPCへ先行配置したことと、main未反映を区別する。更新前に正本のremoteとレビュー済みコミットを確認し、同期後に記録とハッシュを照合する。手編集された共通ファイルや同名の二重登録は上書きせず停止する。

通常の実行、無効化、元に戻す方法は [Windowsの操作](../skills/limited-cli-delegation/references/windows.md) を参照。共通 `config.toml`、他のスキル、認証、モデル、契約・課金設定は変更していない。常駐サービス・タスクスケジューラ・Workflowは追加していない。

## PR #26との関係

[PR #26](https://github.com/tama357/chatgpt-cursor/pull/26) は確認時open・未マージ、head `15d7cbbe85f218e8aa9b781dacde8a54b6d8709a`。PRの変更・マージはしていない。

同PRの一般ルールは「当該作業でのみ明示許可」「別作業へ許可を引き継がない」「スクリプトや外部ワーカーで迂回しない」。今回のユーザーの新しい明示指示はCursorと既存agyへの継続許可を明確に認めた限定例外であり、一般ルールを撤回するものではない。

将来の統合時は、AGENTSの一般ルールと今回の例外を双方残す。PR #26の `docs/USAGE_POLICY.md` と `session-handoff` の一般的な引き継ぎ禁止には、この明示された継続許可の参照を必要最小限で加える。一般のサブエージェント・並列・子CLIからの再委任は許可しない。重なる `PROJECTS.md` / `TODAY.md` は双方の記録を保持し、PR #26の未マージ内容を取り込み済みと扱わない。

## 新しい会話での確認文

新しいCodex会話を、このPC上の任意の作業フォルダーで開始する。スキルが表示されなければCodexを再起動する。次の文ならCLIへの推論を追加せず確認できる。

> 今回使えるスキル一覧にlimited-cli-delegationがあるか、共通AGENTSの限定許可、回数上限、runtime.local.jsonの有効・無効状態を確認してください。CLIへの推論依頼や別エージェントの起動は行わないでください。

新しい会話や別Codexエージェントは今回起動していない。スキル検出は既存Codex実行ファイルの推論しない `skills/list` だけで確認した。
