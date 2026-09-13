#requires -Version 7.0
Set-StrictMode -Version Latest
if (-not ('CliBoundedTextReader' -as [type])) { Add-Type -Path (Join-Path $PSScriptRoot 'BoundedTextReader.cs') }

function Test-SensitiveText([string]$Text) {
    # A supplementary check, not a detector for all personal/confidential data.
    return $Text -match '(?im)(-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._-]{12,}|\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*["\x27]?[A-Za-z0-9_./+-]{8,}|\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)'
}

function Get-CliFailureReason([string]$Stderr) {
    # Return only a fixed category; never echo a raw error, token or account name.
    if ($Stderr -match '(?i)not logged in|not authenticated|authentication required|unauthorized|please.*log.?in') { return 'AUTH_REQUIRED' }
    if ($Stderr -match '(?i)trust required|not trusted|trust.*workspace|permission.*required|approval.*required') { return 'PERMISSION_REQUIRED' }
    if ($Stderr -match '(?i)rate.?limit|usage.?limit|quota|limit exceeded') { return 'USAGE_LIMIT' }
    if ($Stderr -match '(?i)ENOTFOUND|ECONNREFUSED|ECONNRESET|connection.*failed') { return 'CONNECTION_FAILED' }
    if ($Stderr -match '(?i)unknown option|invalid.*config|unsupported.*option') { return 'CLI_CONFIGURATION_ERROR' }
    return 'CLI_EXIT_NONZERO'
}

function Convert-CliResult([string]$Provider, [string]$Stdout, [int]$ExitCode, [bool]$TimedOut) {
    $result = [ordered]@{provider=$Provider; ok=$false; exit_code=$ExitCode; json_parsed=$false; error=$null; response=$null}
    if ($TimedOut) { $result.error='TIMEOUT'; return $result }
    if ($ExitCode -ne 0) { $result.error='CLI_EXIT_NONZERO'; return $result }
    if ([string]::IsNullOrWhiteSpace($Stdout)) { $result.error='EMPTY_OUTPUT'; return $result }
    try { $payload = ConvertFrom-Json -InputObject $Stdout -AsHashtable -ErrorAction Stop }
    catch { $result.error='INVALID_JSON'; return $result }
    $result.json_parsed=$true
    if ($payload -isnot [System.Collections.IDictionary]) { $result.error='INVALID_SCHEMA'; return $result }
    if ($Provider -ceq 'Gemini') {
        # Original Gemini adapter's success contract; do not apply Cursor's schema.
        $success = $payload['status'] -is [string] -and $payload['status'] -ceq 'SUCCESS'
        $response = $payload['response']
        if ($payload['status'] -is [string] -and -not $success) { $result.error='SERVICE_FAILURE'; return $result }
    } else {
        $success = $payload['type'] -is [string] -and $payload['subtype'] -is [string] -and
            $payload['type'] -ceq 'result' -and $payload['subtype'] -ceq 'success' -and
            $payload['is_error'] -is [bool] -and $payload['is_error'] -eq $false
        $response = $payload['result']
        if (($payload['is_error'] -is [bool] -and $payload['is_error']) -or
            ($payload['subtype'] -is [string] -and $payload['subtype'] -cne 'success')) { $result.error='SERVICE_FAILURE'; return $result }
    }
    if (-not $success -or $response -isnot [string]) {
        $result.error='INVALID_SCHEMA'; return $result
    }
    if ([string]::IsNullOrWhiteSpace($response)) { $result.error='EMPTY_RESPONSE'; return $result }
    if (Test-SensitiveText $response) { $result.error='SENSITIVE_OUTPUT'; return $result }
    $result.ok=$true
    $result.response=$response
    return $result
}

function Get-CliCommand([string]$Provider, [hashtable]$Config, [string]$Request, [string]$Workspace, [int]$TimeoutSeconds) {
    if ($Provider -ceq 'Cursor') {
        return @{file=$Config.cursor_node; args=@($Config.cursor_entry,'--print','--mode','ask','--output-format','json','--workspace',$Workspace,$Request)}
    }
    # The existing, verified Gemini call is preserved. Extra flags are from local help.
    return @{file=$Config.gemini_exe; args=@('-p',$Request,'--output-format','json','--disable-slash-commands','--mode','plan','--print-timeout',"$($TimeoutSeconds)s")}
}

function Invoke-CliProcess([string]$File, [string[]]$Arguments, [string]$Workspace, [int]$TimeoutSeconds) {
    # Conservative Windows command-line bound, including escaping and executable.
    $length = 2 * $File.Length + 4
    foreach ($arg in $Arguments) { $length += 2 * $arg.Length + 4 }
    if ($length -gt 30000) { throw 'INPUT_TOO_LONG' }
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$File
    $info.WorkingDirectory=$Workspace
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    $info.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
    $info.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
    $info.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
    foreach ($arg in $Arguments) { $info.ArgumentList.Add($arg) }
    foreach ($key in @($info.Environment.Keys)) {
        if ($key -match '(?i)(API_?KEY|TOKEN|SECRET|PASSWORD)|^NODE_OPTIONS$|^CURSOR_API_ENDPOINT$') {
            [void]$info.Environment.Remove($key)
        }
    }
    $info.Environment['CODEX_CLI_DELEGATION_CHILD']='1'
    $info.Environment['NO_COLOR']='1'
    $process=[Diagnostics.Process]::new()
    $process.StartInfo=$info
    $started=$false
    try {
        if (-not $process.Start()) { throw 'START_FAILED' }
        $started=$true
        $stdoutTask=[CliBoundedTextReader]::ReadAsync($process.StandardOutput,2000000)
        $stderrTask=[CliBoundedTextReader]::ReadAsync($process.StandardError,2000000)
        $process.StandardInput.Close()
        $timedOut=-not $process.WaitForExit($TimeoutSeconds * 1000)
        if ($timedOut) {
            try { $process.Kill($true) } catch { throw 'TERMINATION_FAILED' }
            if (-not $process.WaitForExit(5000)) { throw 'TERMINATION_FAILED' }
        }
        # Bound pipe drain too: a detached descendant can hold a pipe open.
        if (-not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdoutTask,$stderrTask),5000)) {
            throw 'PIPE_TIMEOUT'
        }
        $stdout=$stdoutTask.Result.Text
        $stderr=$stderrTask.Result.Text
        if ($stdoutTask.Result.ExceededLimit -or $stderrTask.Result.ExceededLimit) { throw 'OUTPUT_TOO_LARGE' }
        return @{stdout=$stdout; exit_code=$process.ExitCode; timed_out=$timedOut; stderr_present=($stderr.Length -gt 0); failure_reason=(Get-CliFailureReason $stderr)}
    } finally {
        if ($started -and -not $process.HasExited) {
            try { $process.Kill($true); if (-not $process.WaitForExit(5000)) { throw 'TERMINATION_FAILED' } }
            catch { throw 'TERMINATION_FAILED' }
        }
        $process.Dispose()
    }
}

function Reserve-CliAttempt([string]$StatePath, [string]$Provider) {
    $state=@{schema=1; attempts=@(); blocked=$false}
    if (Test-Path -LiteralPath $StatePath) {
        try { $state=Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json -AsHashtable -ErrorAction Stop }
        catch { throw 'INVALID_STATE' }
        if ($state.schema -ne 1 -or $state.attempts -isnot [array] -or $state.blocked -isnot [bool]) { throw 'INVALID_STATE' }
    }
    if ($state.blocked) { throw 'TASK_STOPPED' }
    if ($state.attempts.Count -ge 2 -or $state.attempts -contains $Provider) { throw 'ATTEMPT_LIMIT' }
    # Written before launch. Crash/interruption stays blocked rather than resuming.
    $state.attempts=@($state.attempts) + $Provider
    $state.blocked=$true
    [IO.File]::WriteAllText($StatePath,($state | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    return $state
}
