param([ValidateSet('start','stop','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskData = Join-Path $taskRoot '.local\mbti-test\data'
$taskPgBin = 'C:\Program Files\PostgreSQL\17\bin'
if (-not (Test-Path -LiteralPath $taskData)) { throw 'Local database cluster is missing. Follow docs/mbti-database.md.' }
if ($Action -eq 'start') {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskData status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output 'Local PostgreSQL is already running.'; exit 0 }
    $taskArgs = '-D "' + $taskData + '" -p 55432 -h 127.0.0.1'
    Start-Process -FilePath (Join-Path $taskPgBin 'postgres.exe') -ArgumentList $taskArgs -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $taskRoot '.local\mbti-test\stdout.log') `
        -RedirectStandardError (Join-Path $taskRoot '.local\mbti-test\stderr.log')
    for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
        & (Join-Path $taskPgBin 'pg_isready.exe') -h 127.0.0.1 -p 55432 *> $null
        if ($LASTEXITCODE -eq 0) { Write-Output 'Local PostgreSQL is ready on 127.0.0.1:55432.'; exit 0 }
        Start-Sleep -Milliseconds 250
    }
    throw 'Database did not become ready; check .local/mbti-test/stderr.log.'
} elseif ($Action -eq 'stop') {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskData -m fast stop
} else {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskData status
}
