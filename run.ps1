param([Parameter(ValueFromRemainingArguments=$true)][string[]]$ToolArgs)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not $ToolArgs) { $ToolArgs = @('--help') }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m tricolumn @ToolArgs
    } else {
        & python -m tricolumn @ToolArgs
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
