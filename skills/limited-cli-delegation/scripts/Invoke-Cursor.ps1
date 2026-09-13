#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PromptFile,
    [Parameter(Mandatory)][string]$TaskId,
    [switch]$ContentReviewed,
    [ValidateRange(1,600)][int]$TimeoutSeconds = 180
)
& (Join-Path $PSScriptRoot 'Invoke-DelegatedTask.ps1') -Provider Cursor @PSBoundParameters
exit $LASTEXITCODE
