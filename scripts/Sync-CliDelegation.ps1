#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [string]$UserRoot=[Environment]::GetFolderPath('UserProfile'),
    [string]$CodexDirectory=$(if ($env:CODEX_HOME) {$env:CODEX_HOME} else {Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex'}),
    [string]$CursorNode,
    [string]$CursorEntry,
    [string]$GeminiExe
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$repo=(Resolve-Path -LiteralPath $RepositoryRoot).Path
$remote=(& git -C $repo remote get-url origin | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $remote -notmatch '^(https://github\.com/|git@github\.com:)tama357/chatgpt-cursor(?:\.git)?$') {
    throw 'Repository origin does not match tama357/chatgpt-cursor.'
}
$name='limited-cli-delegation'
$source=Join-Path $repo "skills/$name"
$target=Join-Path $UserRoot ".agents/skills/$name"
$manifestPath=Join-Path $target 'sync-manifest.local.json'
$configPath=Join-Path $target 'runtime.local.json'
if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md'))) { throw 'Source skill is missing.' }
foreach ($duplicate in @((Join-Path $CodexDirectory "skills/$name"),(Join-Path $repo ".agents/skills/$name"))) {
    if (Test-Path -LiteralPath $duplicate) { throw 'Duplicate skill registration detected; nothing changed.' }
}
$manifest=$null
if (Test-Path -LiteralPath $target) {
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw 'Unmanaged destination exists; nothing changed.' }
    $manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json -AsHashtable
    if ($manifest.repository -cne 'tama357/chatgpt-cursor') { throw 'Destination belongs to another source.' }
}
$files=@(Get-ChildItem -LiteralPath $source -File -Recurse | Where-Object { $_.Name -notlike '*.local.json' })
$hashes=@{}
foreach ($file in $files) {
    $relative=[IO.Path]::GetRelativePath($source,$file.FullName)
    $dest=Join-Path $target $relative
    $hashes[$relative]=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    if (Test-Path -LiteralPath $dest) {
        if ($null -eq $manifest -or -not $manifest.files.Contains($relative) -or
            (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -ne $manifest.files[$relative]) {
            throw 'Destination was edited outside synchronization; nothing changed.'
        }
    }
}
if ($null -ne $manifest) {
    foreach ($old in $manifest.files.Keys) {
        if (-not $hashes.Contains($old)) { throw 'Source removed a managed file; review explicitly before removing it.' }
    }
}
$config=@{}
if (Test-Path -LiteralPath $configPath) { $config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json -AsHashtable }
foreach ($entry in @(@('cursor_node',$CursorNode),@('cursor_entry',$CursorEntry),@('gemini_exe',$GeminiExe))) {
    if ($entry[1]) {
        $resolved=(Resolve-Path -LiteralPath $entry[1]).Path
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw 'CLI path is not a file.' }
        $config[$entry[0]]=$resolved
    }
}
# Missing CLI settings are allowed; the other provider can still be installed.
foreach ($key in @('cursor_node','cursor_entry','gemini_exe')) { if (-not $config.Contains($key)) { $config[$key]='' } }
foreach ($key in @('cursor_enabled','gemini_enabled')) { if (-not $config.Contains($key)) { $config[$key]=$false } }
$agentsPath=Join-Path $CodexDirectory 'AGENTS.md'
$previous=if (Test-Path -LiteralPath $agentsPath) {[IO.File]::ReadAllText($agentsPath)} else {''}
$start='<!-- limited-cli-delegation:start -->'
$end='<!-- limited-cli-delegation:end -->'
$block=@"
$start
## Cursor / Geminiへの限定的な継続許可

一般のサブエージェントは当該作業への明示許可時のみ。作業量・複雑さだけでは許可しない。例外として、2026-09-13の明示承認によりCursor CLI（実装・コード修正案・レビュー）とGemini CLI（指定原稿の日本語修正・レビュー）だけは必要に応じて継続利用できる。他エージェント・並列実行・子CLIからの再委任は許可しない。詳細はユーザー共通スキル limited-cli-delegation（$target\SKILL.md）を必要時に読む。各プロジェクト固有の禁止事項・機密情報制約を優先する。
$end
"@
$pattern='(?s)'+[regex]::Escape($start)+'.*?'+[regex]::Escape($end)
if ($previous.Contains($start) -xor $previous.Contains($end)) { throw 'Broken managed AGENTS block; nothing changed.' }
if ([regex]::Matches($previous,[regex]::Escape($start)).Count -gt 1) { throw 'Duplicate AGENTS blocks; nothing changed.' }
$updated=if ($previous.Contains($start)) {[regex]::Replace($previous,$pattern,[Text.RegularExpressions.MatchEvaluator]{param($m) $block})} else {$previous.TrimEnd()+"`n`n"+$block+"`n"}
# No writes until all collision checks pass. Preserve a first-install AGENTS backup.
[void][IO.Directory]::CreateDirectory($target)
[void][IO.Directory]::CreateDirectory($CodexDirectory)
if ($previous -and -not (Test-Path -LiteralPath (Join-Path $target 'AGENTS.before-install.local.txt'))) {
    [IO.File]::WriteAllText((Join-Path $target 'AGENTS.before-install.local.txt'),$previous,[Text.UTF8Encoding]::new($false))
}
foreach ($file in $files) {
    $relative=[IO.Path]::GetRelativePath($source,$file.FullName)
    $dest=Join-Path $target $relative
    [void][IO.Directory]::CreateDirectory((Split-Path $dest -Parent))
    Copy-Item -LiteralPath $file.FullName -Destination $dest
}
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding utf8NoBOM
[IO.File]::WriteAllText($agentsPath,$updated,[Text.UTF8Encoding]::new($false))
$commit=(& git -C $repo rev-parse HEAD | Out-String).Trim()
$dirty=@(& git -C $repo status --porcelain -- 'skills/limited-cli-delegation').Count -gt 0
@{repository='tama357/chatgpt-cursor'; source=$source; commit=$commit; source_dirty=$dirty; files=$hashes} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8NoBOM
[pscustomobject]@{installed=$true; source=$source; target=$target; files=$files.Count; agents_entry=$true} | ConvertTo-Json
