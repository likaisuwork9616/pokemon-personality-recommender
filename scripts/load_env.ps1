# Dot-source this file: . .\scripts\load_env.ps1
$taskEnvPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
foreach ($taskEnvLine in Get-Content -LiteralPath $taskEnvPath) {
    if ($taskEnvLine -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
    }
}
