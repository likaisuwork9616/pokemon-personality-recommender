param([ValidateSet('initialize','start','stop','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'load_env.ps1')
$taskPortableBin = Join-Path $taskRoot '.local\pgsql\bin'
$taskPortableData = Join-Path $taskRoot '.local\postgres\data'
if (Test-Path -LiteralPath $taskPortableBin) {
    # PostgreSQL on Windows requires an ASCII executable path during initdb.
    # The junction keeps all database files physically inside this project.
    $taskHasher = [Security.Cryptography.SHA256]::Create()
    try { $taskHash = [BitConverter]::ToString($taskHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskRoot))).Replace('-', '').Substring(0, 12) } finally { $taskHasher.Dispose() }
    $taskRuntimeLink = Join-Path ([IO.Path]::GetTempPath()) "pokemon-runtime-$taskHash"
    $taskLocalRoot = Join-Path $taskRoot '.local'
    if (Test-Path -LiteralPath $taskRuntimeLink) {
        if ((Get-Item -LiteralPath $taskRuntimeLink).Target -ne $taskLocalRoot) { throw 'Runtime junction points to another project.' }
    } else {
        New-Item -ItemType Junction -Path $taskRuntimeLink -Target $taskLocalRoot | Out-Null
    }
    $taskPortableBin = Join-Path $taskRuntimeLink 'pgsql\bin'
    $taskPortableData = Join-Path $taskRuntimeLink 'postgres\data'
}
$taskPgBin = if ($env:LOCAL_POSTGRES_BIN) { $env:LOCAL_POSTGRES_BIN } elseif (Test-Path -LiteralPath $taskPortableBin) { $taskPortableBin } else { 'C:\Program Files\PostgreSQL\17\bin' }
$taskData = if ($env:LOCAL_POSTGRES_DATA) { $env:LOCAL_POSTGRES_DATA } elseif ((Test-Path -LiteralPath $taskPortableBin) -and ($Action -eq 'initialize' -or (Test-Path -LiteralPath $taskPortableData))) { $taskPortableData } else { Join-Path $taskRoot '.local\mbti-test\data' }
$taskPort = if ($env:POSTGRES_PORT) { [int]$env:POSTGRES_PORT } else { 55432 }
if (-not (Test-Path -LiteralPath (Join-Path $taskPgBin 'postgres.exe'))) { throw 'PostgreSQL binaries are missing. Set LOCAL_POSTGRES_BIN in .env.' }
if ($Action -eq 'initialize') {
    if (Test-Path -LiteralPath $taskData) { throw 'Database directory already exists; initialization will not overwrite it.' }
    if (-not $env:POSTGRES_PASSWORD) { throw 'Set POSTGRES_PASSWORD in .env before initialization.' }
    $taskDatabaseRoot = Split-Path $taskData -Parent
    New-Item -ItemType Directory -Force -Path $taskDatabaseRoot | Out-Null
    $taskPasswordFile = Join-Path $taskDatabaseRoot 'init-password.txt'
    [IO.File]::WriteAllText($taskPasswordFile, $env:POSTGRES_PASSWORD, [Text.Encoding]::UTF8)
    try {
        & (Join-Path $taskPgBin 'initdb.exe') -D $taskData -U $env:POSTGRES_USER --encoding=UTF8 --locale=C --auth=scram-sha-256 "--pwfile=$taskPasswordFile"
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL initialization failed.' }
    } finally { Remove-Item -LiteralPath $taskPasswordFile -ErrorAction SilentlyContinue }
    Add-Content -LiteralPath (Join-Path $taskData 'postgresql.conf') -Encoding UTF8 -Value "`nlisten_addresses = '127.0.0.1'`nport = $taskPort`n"
    Write-Output 'Local database initialized. Run local_database.ps1 start next.'
    exit 0
}
if (-not (Test-Path -LiteralPath $taskData)) { throw 'Local database cluster is missing. Follow docs/windows-local.md or docs/mbti-database.md.' }
if ($Action -eq 'start') {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskData status *> $null
    if ($LASTEXITCODE -eq 0) { Write-Output 'Local PostgreSQL is already running.'; exit 0 }
    $taskArgs = '-D "' + $taskData + '" -p ' + $taskPort + ' -h 127.0.0.1'
    Start-Process -FilePath (Join-Path $taskPgBin 'postgres.exe') -ArgumentList $taskArgs -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path (Split-Path $taskData -Parent) 'stdout.log') `
        -RedirectStandardError (Join-Path (Split-Path $taskData -Parent) 'stderr.log')
    for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
        & (Join-Path $taskPgBin 'pg_isready.exe') -h 127.0.0.1 -p $taskPort *> $null
        if ($LASTEXITCODE -eq 0) { Write-Output "Local PostgreSQL is ready on 127.0.0.1:$taskPort."; exit 0 }
        Start-Sleep -Milliseconds 250
    }
    throw "Database did not become ready; check $(Split-Path $taskData -Parent)\stderr.log."
} elseif ($Action -eq 'stop') {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskData -m fast stop
} else {
    & (Join-Path $taskPgBin 'pg_ctl.exe') -D $taskData status
}
