#requires -Version 7.0
# Entirely offline. Never starts Cursor, agy, an LLM, or a repository workflow.
[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$source=Join-Path $repo 'skills/limited-cli-delegation'
. (Join-Path $source 'scripts/Delegation.Core.ps1')
$scratch=Join-Path $repo ('.cli-delegation/tests/'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($scratch)
$script:passed=0
function Assert([bool]$Condition,[string]$Name) {
    if (-not $Condition) { throw "FAIL: $Name" }
    $script:passed++
}
foreach ($file in @(Get-ChildItem (Join-Path $source 'scripts') -Filter '*.ps1') + @((Get-Item (Join-Path $repo 'scripts/Sync-CliDelegation.ps1')),(Get-Item $PSCommandPath))) {
    $parseErrors=$null; $tokens=$null
    [void][Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$parseErrors)
    Assert ($parseErrors.Count -eq 0) "syntax: $($file.Name)"
}
$gemini='{"status":"SUCCESS","response":"この機能で作業が楽になります。"}'
$cursor='{"type":"result","subtype":"success","is_error":false,"result":"return a + b;"}'
Assert ((Convert-CliResult Gemini $gemini 0 $false).ok) 'Gemini schema'
Assert ((Convert-CliResult Cursor $cursor 0 $false).ok) 'Cursor schema'
Assert (-not (Convert-CliResult Cursor $gemini 0 $false).ok) 'Gemini schema is not Cursor'
Assert (-not (Convert-CliResult Gemini $cursor 0 $false).ok) 'Cursor schema is not Gemini'
foreach ($bad in @('bad json','[]','{}','null','{"status":"SUCCESS","response":" "}','{"status":"FAILED","response":"text"}','{"status":"SUCCESS","response":123}','{"status":["SUCCESS"],"response":"x"}')) {
    Assert (-not (Convert-CliResult Gemini $bad 0 $false).ok) 'reject malformed/failed/empty response'
}
Assert (-not (Convert-CliResult Cursor '{"type":"result","subtype":"success","is_error":"false","result":"x"}' 0 $false).ok) 'boolean must be boolean'
Assert ((Convert-CliResult Cursor $cursor 3 $false).error -eq 'CLI_EXIT_NONZERO') 'native exit takes precedence'
Assert ((Convert-CliResult Gemini $gemini 0 $true).error -eq 'TIMEOUT') 'timeout takes precedence'
Assert (Test-SensitiveText 'password=FAKE_TEST_VALUE') 'obvious secret detection using dummy only'
Assert ((Convert-CliResult Gemini '{"status":"SUCCESS","response":"tester@example.invalid"}' 0 $false).error -eq 'SENSITIVE_OUTPUT') 'sensitive output suppressed'
Assert ((Get-CliFailureReason 'Please log in: tester@example.invalid') -eq 'AUTH_REQUIRED') 'redacted authentication reason'
Assert ((Get-CliFailureReason 'Workspace Trust Required') -eq 'PERMISSION_REQUIRED') 'permission reason'
Assert ((Get-CliFailureReason 'Usage limit exceeded') -eq 'USAGE_LIMIT') 'limit reason'
Assert ((Convert-CliResult Gemini '' 0 $false).error -eq 'EMPTY_OUTPUT') 'empty stdout distinct'
Assert ((Convert-CliResult Gemini '{"status":"SUCCESS","response":" "}' 0 $false).error -eq 'EMPTY_RESPONSE') 'empty answer distinct'
Assert ((Convert-CliResult Gemini '{"status":"FAILED","response":"x"}' 0 $false).error -eq 'SERVICE_FAILURE') 'service failure distinct'

$echo=Join-Path $scratch 'echo.ps1'
@'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::Write($args[0])
[Console]::Error.Write('x' * 100000)
'@ | Set-Content -LiteralPath $echo -Encoding utf8NoBOM
$literal='日本語の長文「引用」' + "`r`n第二行`n" + ('あ' * 11950) + ' " $() ` & ; \ 😀'
$native=Invoke-CliProcess (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile','-File',$echo,$literal) $scratch 20
Assert ($native.stdout -ceq $literal -and $native.exit_code -eq 0 -and $native.stderr_present) '12000 Japanese characters/literal arguments/separate pipes'
$sleep=Join-Path $scratch 'sleep.ps1'
'Start-Sleep -Seconds 30' | Set-Content -LiteralPath $sleep -Encoding utf8NoBOM
$timer=[Diagnostics.Stopwatch]::StartNew()
$native=Invoke-CliProcess (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile','-File',$sleep) $scratch 1
Assert ($native.timed_out -and $timer.Elapsed.TotalSeconds -lt 10) 'native timeout terminates'
$flood=Join-Path $scratch 'flood.ps1'
"[Console]::Write('x' * 2100000)" | Set-Content -LiteralPath $flood -Encoding utf8NoBOM
try { $null=Invoke-CliProcess (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile','-File',$flood) $scratch 15; throw 'unexpected' }
catch { Assert ($_.Exception.Message -eq 'OUTPUT_TOO_LARGE') 'bounded oversized output rejected' }
$statePath=Join-Path $scratch 'task.json'
$state=Reserve-CliAttempt $statePath Cursor
Assert ($state.blocked -and $state.attempts.Count -eq 1) 'reserve before launch'
try { Reserve-CliAttempt $statePath Gemini; throw 'unexpected' } catch { Assert ($_.Exception.Message -eq 'TASK_STOPPED') 'crash stops task' }
$state.blocked=$false
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath
try { Reserve-CliAttempt $statePath Cursor; throw 'unexpected' } catch { Assert ($_.Exception.Message -eq 'ATTEMPT_LIMIT') 'one per provider' }
$state=Reserve-CliAttempt $statePath Gemini
Assert ($state.attempts.Count -eq 2) 'two serial providers'
$state.blocked=$false
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath
try { Reserve-CliAttempt $statePath Gemini; throw 'unexpected' } catch { Assert ($_.Exception.Message -eq 'ATTEMPT_LIMIT') 'total limit' }
$lockPath=Join-Path $scratch 'serial.lock'
$lock=[IO.File]::Open($lockPath,'OpenOrCreate','ReadWrite','None')
try {
    try { $second=[IO.File]::Open($lockPath,'OpenOrCreate','ReadWrite','None'); $second.Dispose(); throw 'unexpected' }
    catch { Assert ($_.Exception.Message -ne 'unexpected') 'concurrent lock refused' }
} finally { $lock.Dispose() }
$guardOutput=Invoke-CliProcess (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile','-File',(Join-Path $source 'scripts/Invoke-Cursor.ps1'),'-PromptFile',$echo,'-TaskId','offline-recursion','-ContentReviewed') $scratch 20
$guard=$guardOutput.stdout | ConvertFrom-Json
Assert ($guard.error -eq 'RECURSION_BLOCKED' -and $guardOutput.exit_code -ne 0) 'child cannot call wrapper again'

# Sync twice into a fake user directory, with unrelated content and config preserved.
$fakeUser=Join-Path $scratch 'user'
$fakeCodex=Join-Path $fakeUser '.codex'
[void][IO.Directory]::CreateDirectory($fakeCodex)
$original="# Existing instructions`nUnrelated setting stays.`n"
[IO.File]::WriteAllText((Join-Path $fakeCodex 'AGENTS.md'),$original)
[IO.File]::WriteAllText((Join-Path $fakeCodex 'config.toml'),'unrelated = true')
$sync=Join-Path $repo 'scripts/Sync-CliDelegation.ps1'
$syncParams=@{RepositoryRoot=$repo; UserRoot=$fakeUser; CodexDirectory=$fakeCodex}
$null=& $sync @syncParams
$first=[IO.File]::ReadAllText((Join-Path $fakeCodex 'AGENTS.md'))
$null=& $sync @syncParams
$second=[IO.File]::ReadAllText((Join-Path $fakeCodex 'AGENTS.md'))
Assert ($first -ceq $second -and $first.StartsWith($original.TrimEnd())) 'idempotent sync preserves existing rules'
Assert ([IO.File]::ReadAllText((Join-Path $fakeCodex 'config.toml')) -ceq 'unrelated = true') 'config untouched'
$installedSkill=Join-Path $fakeUser '.agents/skills/limited-cli-delegation/SKILL.md'
Add-Content -LiteralPath $installedSkill 'External local edit'
try { $null=& $sync @syncParams; throw 'unexpected' } catch { Assert ($_.Exception.Message -match 'edited outside') 'refuse overwriting manual edits' }

# End-to-end wrapper with a fake local provider and a separate child environment.
$mockRoot=Join-Path $scratch 'mock-skill'
Copy-Item -LiteralPath $source -Destination $mockRoot -Recurse
$mock=Join-Path $scratch 'mock-provider.ps1'
@'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$counter=Join-Path $env:LOCALAPPDATA 'mock-count.txt'
Add-Content -LiteralPath $counter 'called'
if ($args[-1] -match 'offline-failure') { [Console]::Error.Write('Please log in'); exit 3 }
@{type='result';subtype='success';is_error=$false;result='架空の回答です。'} | ConvertTo-Json -Compress
'@ | Set-Content -LiteralPath $mock -Encoding utf8NoBOM
@{cursor_node=(Join-Path $PSHOME 'pwsh.exe');cursor_entry=$mock;gemini_exe='';cursor_enabled=$true;gemini_enabled=$false} | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $mockRoot 'runtime.local.json') -Encoding utf8NoBOM
$mockData=Join-Path $scratch 'mock-data'
[void][IO.Directory]::CreateDirectory($mockData)
$inputFile=Join-Path $scratch 'mock-input.txt'
'短い架空の原稿です。' | Set-Content -LiteralPath $inputFile -Encoding utf8NoBOM
function Run-Mock([string]$TaskName) {
    $info=[Diagnostics.ProcessStartInfo]::new((Join-Path $PSHOME 'pwsh.exe'))
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
    $info.Environment['LOCALAPPDATA']=$mockData
    [void]$info.Environment.Remove('CODEX_CLI_DELEGATION_CHILD')
    foreach ($a in @('-NoProfile','-File',(Join-Path $mockRoot 'scripts/Invoke-Cursor.ps1'),'-PromptFile',$inputFile,'-TaskId',$TaskName,'-ContentReviewed','-TimeoutSeconds','15')) { $info.ArgumentList.Add($a) }
    $p=[Diagnostics.Process]::Start($info)
    try {
        $out=$p.StandardOutput.ReadToEndAsync(); $err=$p.StandardError.ReadToEndAsync()
        if (-not $p.WaitForExit(20000)) { $p.Kill($true); throw 'mock wrapper timeout' }
        [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($out,$err))
        return ($out.Result | ConvertFrom-Json)
    } finally { $p.Dispose() }
}
$answer=Run-Mock 'success'
if (-not ($answer.ok -and $answer.response -ceq '架空の回答です。')) { $answer | ConvertTo-Json -Depth 5 | Write-Output }
Assert ($answer.ok -and $answer.response -ceq '架空の回答です。') 'wrapper end-to-end success'
Assert ((Run-Mock 'success').error -eq 'ATTEMPT_LIMIT') 'wrapper does not call twice'
'offline-failure' | Set-Content -LiteralPath $inputFile -Encoding utf8NoBOM
Assert ((Run-Mock 'failure').error -eq 'AUTH_REQUIRED') 'wrapper failure classifies without account text'
Assert ((Run-Mock 'failure').error -eq 'TASK_STOPPED') 'wrapper stops after failure'
Assert (@(Get-Content -LiteralPath (Join-Path $mockData 'mock-count.txt')).Count -eq 2) 'only two actual mock invocations'
$mockConfig=Join-Path $mockRoot 'runtime.local.json'
$settings=Get-Content -LiteralPath $mockConfig -Raw | ConvertFrom-Json -AsHashtable
$settings.cursor_enabled=$false
$settings | ConvertTo-Json | Set-Content -LiteralPath $mockConfig
Assert ((Run-Mock 'disabled').error -eq 'PROVIDER_DISABLED') 'disabled provider never launched'
Assert (@(Get-Content -LiteralPath (Join-Path $mockData 'mock-count.txt')).Count -eq 2) 'disabled provider consumes no service call'
$settings.cursor_enabled=$true
$settings | ConvertTo-Json | Set-Content -LiteralPath $mockConfig
'{"stopped":true}' | Set-Content -LiteralPath (Join-Path $mockData 'CodexCliDelegation/halted.json')
Assert ((Run-Mock 'different-task-after-halt').error -eq 'GLOBAL_STOPPED') 'unconfirmed termination stops all tasks'
[pscustomobject]@{offline=$true; passed=$script:passed; service_calls=0} | ConvertTo-Json
