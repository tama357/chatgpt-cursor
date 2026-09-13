#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PromptFile,
    [Parameter(Mandatory)][string]$TaskId,
    [switch]$ContentReviewed,
    [ValidateRange(1,600)][int]$TimeoutSeconds = 180
)
# Adapted from the user's verified agy-test/Invoke-Gemini.ps1 (2026-09-13).
# Reuses agy -p TEXT --output-format json and strict SUCCESS/response checks.
# The common runner adds file input, separate pipes, timeout and attempt limits.
& (Join-Path $PSScriptRoot 'Invoke-DelegatedTask.ps1') -Provider Gemini @PSBoundParameters
exit $LASTEXITCODE
