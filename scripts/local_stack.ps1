param([ValidateSet('start','stop','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'load_env.ps1')
$taskRuntime = Join-Path $taskRoot '.local\services'
New-Item -ItemType Directory -Force -Path $taskRuntime | Out-Null
$taskStatePath = Join-Path $taskRuntime 'processes.json'
$taskState = if (Test-Path -LiteralPath $taskStatePath) { @(Get-Content -Raw -LiteralPath $taskStatePath -Encoding UTF8 | ConvertFrom-Json) } else { @() }

function Get-TaskProcess($Record) {
    $taskProcess = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if ($taskProcess -and $taskProcess.StartTime.ToUniversalTime().Ticks -eq ([datetime]$Record.started).ToUniversalTime().Ticks -and $taskProcess.Path -eq $Record.executable) { return $taskProcess }
    return $null
}

if ($Action -eq 'stop') {
    foreach ($taskRecord in @($taskState | Sort-Object name -Descending)) {
        $taskProcess = Get-TaskProcess $taskRecord
        if ($taskProcess) {
            & taskkill.exe /PID $taskProcess.Id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not stop $($taskRecord.name)." }
            Write-Output "Stopped $($taskRecord.name)."
        }
    }
    [IO.File]::WriteAllText($taskStatePath, '[]')
    & (Join-Path $PSScriptRoot 'local_database.ps1') stop
    exit $LASTEXITCODE
}
if ($Action -eq 'status') {
    $taskRows = @(foreach ($taskRecord in $taskState) {
        $taskRunning = [bool](Get-TaskProcess $taskRecord)
        [pscustomobject]@{ Service = $taskRecord.name; Running = $taskRunning; PID = $taskRecord.pid }
    })
    $taskRows | Format-Table -AutoSize
    & (Join-Path $PSScriptRoot 'local_database.ps1') status
    exit $LASTEXITCODE
}

& (Join-Path $PSScriptRoot 'local_database.ps1') start
if ($LASTEXITCODE -ne 0) { throw 'Database failed to start.' }

# Adapt the checked-in Docker monitoring configuration for native loopback ports.
$taskMonitoring = Join-Path $taskRoot '.local\monitoring'
$taskProvisioning = Join-Path $taskMonitoring 'provisioning'
New-Item -ItemType Directory -Force -Path (Join-Path $taskProvisioning 'datasources'), (Join-Path $taskProvisioning 'dashboards') | Out-Null
$taskApiPort = if ($env:API_PORT) { $env:API_PORT } else { '8000' }
$taskPromPort = if ($env:PROMETHEUS_PORT) { $env:PROMETHEUS_PORT } else { '9090' }
$taskAlertPort = if ($env:ALERTMANAGER_PORT) { $env:ALERTMANAGER_PORT } else { '9093' }
$taskGrafanaPort = if ($env:GRAFANA_PORT) { $env:GRAFANA_PORT } else { '3000' }
$taskAlertsPath = (Join-Path $taskRoot 'ops\prometheus\alerts.yml').Replace('\', '/')
$taskPromConfig = [IO.File]::ReadAllText((Join-Path $taskRoot 'ops\prometheus\prometheus.yml')).Replace('/etc/prometheus/alerts.yml', $taskAlertsPath).Replace('api:8000', "127.0.0.1:$taskApiPort").Replace('alertmanager:9093', "127.0.0.1:$taskAlertPort")
[IO.File]::WriteAllText((Join-Path $taskMonitoring 'prometheus.yml'), $taskPromConfig)
$taskDatasource = [IO.File]::ReadAllText((Join-Path $taskRoot 'ops\grafana\provisioning\datasources\prometheus.yml')).Replace('http://prometheus:9090', "http://127.0.0.1:$taskPromPort")
[IO.File]::WriteAllText((Join-Path $taskProvisioning 'datasources\prometheus.yml'), $taskDatasource)
$taskDashboardPath = (Join-Path $taskRoot 'ops\grafana\dashboards').Replace('\', '/')
$taskDashboard = [IO.File]::ReadAllText((Join-Path $taskRoot 'ops\grafana\provisioning\dashboards\dashboards.yml')).Replace('/var/lib/grafana/dashboards', $taskDashboardPath)
[IO.File]::WriteAllText((Join-Path $taskProvisioning 'dashboards\dashboards.yml'), $taskDashboard)

$env:GF_PATHS_DATA = Join-Path $taskMonitoring 'grafana-data'
$env:GF_PATHS_LOGS = Join-Path $taskMonitoring 'grafana-logs'
$env:GF_PATHS_PLUGINS = Join-Path $taskMonitoring 'grafana-plugins'
$env:GF_PATHS_PROVISIONING = $taskProvisioning
New-Item -ItemType Directory -Force -Path $env:GF_PATHS_DATA, $env:GF_PATHS_LOGS, $env:GF_PATHS_PLUGINS | Out-Null
$env:GF_SERVER_HTTP_ADDR = '127.0.0.1'
$env:GF_SERVER_HTTP_PORT = $taskGrafanaPort
$env:GF_SECURITY_ADMIN_USER = $env:GRAFANA_ADMIN_USER
$env:GF_SECURITY_ADMIN_PASSWORD = $env:GRAFANA_ADMIN_PASSWORD
$env:GF_USERS_ALLOW_SIGN_UP = 'false'
$env:GF_AUTH_ANONYMOUS_ENABLED = 'false'
$env:GF_ANALYTICS_REPORTING_ENABLED = 'false'
$env:GF_ANALYTICS_CHECK_FOR_UPDATES = 'false'
$env:GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES = 'false'
$env:GF_PLUGINS_PREINSTALL_DISABLED = 'true'

$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskPrometheus = Join-Path $taskRoot '.local\tools\prometheus-3.14.0.windows-amd64\prometheus.exe'
$taskAlertmanager = Join-Path $taskRoot '.local\tools\alertmanager-0.28.1.windows-amd64\alertmanager.exe'
$taskGrafanaHome = (Get-ChildItem -LiteralPath (Join-Path $taskRoot '.local\tools') -Directory | Where-Object { $_.Name -like 'grafana*' } | Select-Object -First 1).FullName
if (-not $taskGrafanaHome) { throw 'Grafana binaries are missing from .local/tools.' }
$taskGrafana = Join-Path $taskGrafanaHome 'bin\grafana.exe'
if (-not (Test-Path -LiteralPath $taskGrafana)) { throw 'Grafana executable is missing.' }
$taskServices = @(
    @{ name = 'api'; executable = $taskPython; arguments = @('-X', 'utf8', '-u', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', $taskApiPort) },
    @{ name = 'worker'; executable = $taskPython; arguments = @('-X', 'utf8', '-u', (Join-Path $taskRoot 'scripts\reindex_worker.py')) },
    @{ name = 'alertmanager'; executable = $taskAlertmanager; arguments = @("--config.file=$(Join-Path $taskRoot 'ops\alertmanager\alertmanager.local.yml')", "--storage.path=$(Join-Path $taskMonitoring 'alertmanager-data')", "--web.listen-address=127.0.0.1:$taskAlertPort", '--cluster.listen-address=') },
    @{ name = 'prometheus'; executable = $taskPrometheus; arguments = @("--config.file=$(Join-Path $taskMonitoring 'prometheus.yml')", "--storage.tsdb.path=$(Join-Path $taskMonitoring 'prometheus-data')", "--web.listen-address=127.0.0.1:$taskPromPort", "--storage.tsdb.retention.time=$env:PROMETHEUS_RETENTION") },
    @{ name = 'grafana'; executable = $taskGrafana; arguments = @('server', '--homepath', $taskGrafanaHome) }
)
# Validate all files before starting any application process.
foreach ($taskService in $taskServices) {
    if (-not (Test-Path -LiteralPath $taskService.executable)) { throw "Missing executable for $($taskService.name)." }
}
foreach ($taskService in $taskServices) {
    $taskPrevious = $taskState | Where-Object { $_.name -eq $taskService.name } | Select-Object -First 1
    if ($taskPrevious -and (Get-TaskProcess $taskPrevious)) { Write-Output "$($taskService.name) is already running."; continue }
    $taskArguments = ($taskService.arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }) -join ' '
    $taskProcess = Start-Process -FilePath $taskService.executable -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $taskRuntime "$($taskService.name).stdout.log") `
        -RedirectStandardError (Join-Path $taskRuntime "$($taskService.name).stderr.log")
    $taskStarted = $taskProcess.StartTime.ToUniversalTime().ToString('o')
    Start-Sleep -Milliseconds 500
    if ($taskProcess.HasExited) { throw "$($taskService.name) exited; check .local/services/$($taskService.name).stderr.log." }
    $taskState = @($taskState | Where-Object { $_.name -ne $taskService.name }) + @([pscustomobject]@{ name = $taskService.name; pid = $taskProcess.Id; started = $taskStarted; executable = $taskService.executable })
    [IO.File]::WriteAllText($taskStatePath, (ConvertTo-Json -InputObject @($taskState)))
    Write-Output "Started $($taskService.name) (PID $($taskProcess.Id))."
}
for ($taskAttempt = 0; $taskAttempt -lt 60; $taskAttempt++) {
    try {
        $taskHealth = Invoke-RestMethod "http://127.0.0.1:$taskApiPort/health/ready" -TimeoutSec 2
        Write-Output "API ready: http://127.0.0.1:$taskApiPort/"
        exit 0
    } catch { Start-Sleep -Milliseconds 500 }
}
throw 'API did not become ready; check .local/services/api.stderr.log.'
