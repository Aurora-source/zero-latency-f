param(
    [switch]$ClearCache,
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($args -contains "--clear-cache") {
    $ClearCache = $true
}
if ($args -contains "--what-if") {
    $WhatIf = $true
}

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "[setup] $Message" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host "[info] $Message" -ForegroundColor Gray
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[ok] $Message" -ForegroundColor Green
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[warn] $Message" -ForegroundColor Yellow
}

function Fail-Script {
    param([string]$Message)
    Write-Host "[error] $Message" -ForegroundColor Red
    exit 1
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Ensure-Requirements {
    param(
        [string]$Name,
        [string]$RequirementsPath,
        [string]$PythonExe,
        [string]$StampDir
    )

    if (-not (Test-Path -LiteralPath $RequirementsPath)) {
        Write-WarnLine "Skipping $Name requirements; file missing at $RequirementsPath"
        return
    }

    Ensure-Directory $StampDir
    $hash = Get-FileSha256 $RequirementsPath
    $stampPath = Join-Path $StampDir "$Name.sha256"
    $currentHash = ""
    if (Test-Path -LiteralPath $stampPath) {
        $currentHash = (Get-Content -LiteralPath $stampPath -Raw).Trim()
    }

    if ($currentHash -eq $hash) {
        Write-Ok "$Name requirements already satisfied"
        return
    }

    Write-Info "Installing $Name requirements"
    & $PythonExe -m pip install -r $RequirementsPath
    Set-Content -LiteralPath $stampPath -Value $hash -NoNewline
    Write-Ok "$Name requirements installed"
}

function Ensure-FrontendDependencies {
    param(
        [string]$FrontendPath,
        [string]$NpmExe,
        [string]$StampDir
    )

    $packageJson = Join-Path $FrontendPath "package.json"
    $packageLock = Join-Path $FrontendPath "package-lock.json"
    $nodeModules = Join-Path $FrontendPath "node_modules"
    if (-not (Test-Path -LiteralPath $FrontendPath)) {
        Fail-Script "Frontend directory is missing at $FrontendPath"
    }
    if (-not (Test-Path -LiteralPath $packageJson)) {
        Fail-Script "Frontend package.json is missing at $packageJson"
    }

    $hashInputs = @($packageJson)
    if (Test-Path -LiteralPath $packageLock) {
        $hashInputs += $packageLock
    }
    $combinedHash = ($hashInputs | ForEach-Object { Get-FileSha256 $_ }) -join ":"
    $stampPath = Join-Path $StampDir "visualization.sha256"
    $currentHash = ""
    if (Test-Path -LiteralPath $stampPath) {
        $currentHash = (Get-Content -LiteralPath $stampPath -Raw).Trim()
    }

    if ((Test-Path -LiteralPath $nodeModules) -and $currentHash -eq $combinedHash) {
        Write-Ok "Frontend dependencies already satisfied"
        return
    }

    Write-Info "Installing frontend dependencies"
    Push-Location $FrontendPath
    try {
        & $NpmExe install --silent
        if ($LASTEXITCODE -ne 0) {
            Fail-Script "npm install failed in $FrontendPath"
        }
    }
    finally {
        Pop-Location
    }
    Ensure-Directory $StampDir
    Set-Content -LiteralPath $stampPath -Value $combinedHash -NoNewline
    Write-Ok "Frontend dependencies installed"
}

function Test-PortAvailable {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    }
    catch {
        return $false
    }
}

function Get-PortOwnerProcessId {
    param([int]$Port)
    try {
        return Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -First 1
    }
    catch {
        return $null
    }
}

function Ensure-PortAvailability {
    param([hashtable]$Ports)
    foreach ($port in $Ports.Keys) {
        if (Test-PortAvailable -Port ([int]$port)) {
            continue
        }

        Write-WarnLine "Port $port already in use for $($Ports[$port])"
        $kill = Read-Host "Kill process on port $port? (y/n)"
        if ($kill -ne "y") {
            Fail-Script "Port $port is required for $($Ports[$port])"
        }

        try {
            $proc = Get-NetTCPConnection -LocalPort ([int]$port) -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -First 1
            if ($proc) {
                Stop-Process -Id $proc -Force
                Write-Ok "Stopped PID $proc on port $port"
            }
        }
        catch {
            Fail-Script "Could not free port $port"
        }
    }
}

function Resolve-FrontendPort {
    param([int]$PreferredPort = 5173)

    if (Test-PortAvailable -Port $PreferredPort) {
        return [pscustomobject]@{
            Port = $PreferredPort
            ReuseExisting = $false
        }
    }

    Write-WarnLine "Frontend port $PreferredPort is already in use"

    try {
        $existingResponse = Invoke-WebRequest -Uri "http://127.0.0.1:$PreferredPort" -UseBasicParsing -TimeoutSec 3
        if ($existingResponse.StatusCode -ge 200 -and $existingResponse.StatusCode -lt 500) {
            Write-Ok "Frontend is already responding on port $PreferredPort"
            return [pscustomobject]@{
                Port = $PreferredPort
                ReuseExisting = $true
            }
        }
    }
    catch {
    }

    $ownerPid = Get-PortOwnerProcessId -Port $PreferredPort
    if ($ownerPid) {
        Write-WarnLine "Stopping PID $ownerPid on frontend port $PreferredPort"
        try {
            Stop-Process -Id $ownerPid -Force -ErrorAction Stop
            Start-Sleep -Seconds 1
        }
        catch {
            Write-WarnLine "Could not stop PID $ownerPid; checking fallback ports"
        }
    }

    if (Test-PortAvailable -Port $PreferredPort) {
        return [pscustomobject]@{
            Port = $PreferredPort
            ReuseExisting = $false
        }
    }

    foreach ($candidate in 5174..5180) {
        if (Test-PortAvailable -Port $candidate) {
            Write-WarnLine "Using fallback frontend port $candidate"
            return [pscustomobject]@{
                Port = $candidate
                ReuseExisting = $false
            }
        }
    }

    Fail-Script "No frontend port is available between 5173 and 5180"
}

function Start-ServiceWindow {
    param(
        [string]$Name,
        [string]$ServicePath,
        [int]$Port,
        [string]$PythonExe,
        [string]$VenvActivate,
        [string[]]$EnvAssignments,
        [switch]$DisableReload,
        [int]$Workers = 1
    )

    if (-not (Test-Path -LiteralPath $ServicePath)) {
        Write-WarnLine "Skipping missing service $Name"
        return $false
    }

    $envLines = foreach ($assignment in $EnvAssignments) {
        if ($assignment) {
            "`$env:$assignment"
        }
    }
    $envBlock = if ($envLines.Count -gt 0) { ($envLines -join "`r`n") + "`r`n" } else { "" }
    $uvicornArgs = "--host 0.0.0.0 --port $Port"
    if ($Workers -gt 1) {
        $uvicornArgs += " --workers $Workers"
    }
    elseif (-not $DisableReload) {
        $uvicornArgs += " --reload"
    }

    $command = @"
Set-Location '$ServicePath'
if (Test-Path '$VenvActivate') { . '$VenvActivate' }
$envBlock& '$PythonExe' -m uvicorn main:app $uvicornArgs
"@

    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $command
    ) -WorkingDirectory $ServicePath | Out-Null

    Write-Ok "Started $Name on port $Port"
    return $true
}

function Wait-ForHttpJson {
    param(
        [string]$Name,
        [string]$Url,
        [scriptblock]$Validator,
        [int]$TimeoutSeconds = 240
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 5
            if (& $Validator $response) {
                Write-Ok "$Name is ready"
                return
            }
        }
        catch {
        }
        Start-Sleep -Seconds 2
    }

    Fail-Script "$Name did not become ready within $TimeoutSeconds seconds"
}

function Wait-ForHttpPage {
    param(
        [string]$Name,
        [string]$Url,
        [System.Diagnostics.Process]$Process,
        [string]$LogPath,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Ok "$Name is ready at $Url"
                return
            }
        }
        catch {
        }

        if ($Process -and $Process.HasExited) {
            $logTail = ""
            if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
                $logTail = (Get-Content -LiteralPath $LogPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            }
            if ([string]::IsNullOrWhiteSpace($logTail)) {
                Fail-Script "$Name failed to start"
            }
            Fail-Script "$Name failed to start. Recent log output:`n$logTail"
        }

        Start-Sleep -Seconds 2
    }

    $timeoutLog = ""
    if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
        $timeoutLog = (Get-Content -LiteralPath $LogPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    }
    if ([string]::IsNullOrWhiteSpace($timeoutLog)) {
        Fail-Script "$Name did not become ready within $TimeoutSeconds seconds"
    }
    Fail-Script "$Name did not become ready within $TimeoutSeconds seconds. Recent log output:`n$timeoutLog"
}

function Clear-ProjectCache {
    param(
        [string]$RootPath,
        [string]$CachePath
    )

    $resolvedRoot = [System.IO.Path]::GetFullPath($RootPath)
    $resolvedCache = [System.IO.Path]::GetFullPath($CachePath)
    if (-not $resolvedCache.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        Fail-Script "Refusing to clear cache outside the project root"
    }

    if (Test-Path -LiteralPath $resolvedCache) {
        Remove-Item -LiteralPath $resolvedCache -Recurse -Force
        Write-Ok "Cleared cache at $resolvedCache"
    }
}

Write-Section "Preparing run-local.ps1"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$root = (Resolve-Path $root).Path
Write-Info "Project root: $root"

function Load-EnvFile {
    param ([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    Get-Content -LiteralPath $Path | ForEach-Object {
        if ($_ -match "^\s*([^#].+?)\s*=\s*(.+)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim("'").Trim('"')
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$envFile = Join-Path $root "services\data-service\.env"
if (Test-Path -LiteralPath $envFile) {
    Write-Info "[verify] .env found"
    Load-EnvFile "$root/services/data-service/.env"
    Write-Host "[startup] Loaded .env variables" -ForegroundColor Cyan
    if (-not [string]::IsNullOrWhiteSpace($env:OPENCELLID_KEYS)) {
        Write-Info "[verify] OPENCELLID_KEYS detected"
    }
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvActivate = Join-Path $root ".venv\Scripts\Activate.ps1"
$createdVenv = $false

if (Test-Path -LiteralPath $venvPython) {
    $pythonExe = $venvPython
    Write-Ok "Using root virtual environment"
}
else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
    }
    if (-not $pythonCommand) {
        Fail-Script "Python was not found. Install Python 3.11+ and rerun run-local.ps1"
    }

    $pythonExe = $pythonCommand.Source
    Write-Info "Creating root virtual environment"
    & $pythonExe -m venv (Join-Path $root ".venv")
    $pythonExe = $venvPython
    $createdVenv = $true
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    Fail-Script "Virtual environment Python is missing at $pythonExe"
}

if ($createdVenv) {
    Write-Info "Upgrading pip in the new virtual environment"
    & $pythonExe -m pip install --upgrade pip
}

$logicalThreads = [Environment]::ProcessorCount
$env:OMP_NUM_THREADS = "$logicalThreads"
$env:MKL_NUM_THREADS = "$logicalThreads"
$env:OPENBLAS_NUM_THREADS = "$logicalThreads"
$env:NUMEXPR_NUM_THREADS = "$logicalThreads"
$env:PYTHONUNBUFFERED = "1"
Write-Ok "Configured CPU thread environment for $logicalThreads logical cores"

$cacheRoot = if ($env:APP_CACHE_DIR) { $env:APP_CACHE_DIR } else { Join-Path $root "cache" }
$cacheRoot = [System.IO.Path]::GetFullPath($cacheRoot)
$graphCacheDir = Join-Path $cacheRoot "graphs"
$stampDir = Join-Path $root ".venv\.deps"
$hotspotCachePath = Join-Path $cacheRoot "hotspots.json"
$routeCachePath = Join-Path $cacheRoot "route_cache.json"

if ($ClearCache) {
    Write-Section "Clearing cache"
    Clear-ProjectCache -RootPath $root -CachePath $cacheRoot
}

Write-Section "Initializing cache"
Ensure-Directory $cacheRoot
Ensure-Directory $graphCacheDir
Ensure-Directory $stampDir
Write-Ok "Cache ready at $cacheRoot"

$env:SUPPORTED_CITIES = "bangalore"
$env:DEFAULT_CITY = "bangalore"
$env:APP_CACHE_DIR = $cacheRoot
$env:GRAPH_CACHE_DIR = $graphCacheDir
$env:HOTSPOT_CACHE_PATH = $hotspotCachePath
$env:ROUTE_CACHE_PATH = $routeCachePath
$env:ROUTING_MODES = "fastest,balanced,connected"
$env:HEATMAP_VIEWPORT_ONLY = "1"
$env:OPENCELLID_TOKEN = if ($env:OPENCELLID_TOKEN) { $env:OPENCELLID_TOKEN } else { "pk.37dddd741049308fd26c175be7a5aea0" }
Write-Ok "Bangalore-only and cache environment configured"

if ($WhatIf) {
    Write-Info "WhatIf mode enabled; exiting after configuration"
    exit 0
}

Write-Section "Checking dependencies"
$pythonServices = @("prediction-service", "data-service", "routing-engine")
foreach ($svc in $pythonServices) {
    $req = Join-Path $root "services\$svc\requirements.txt"
    Ensure-Requirements -Name $svc -RequirementsPath $req -PythonExe $pythonExe -StampDir $stampDir
}

$telemetryReq = Join-Path $root "services\telemetry-service\requirements.txt"
if (Test-Path -LiteralPath $telemetryReq) {
    Ensure-Requirements -Name "telemetry-service" -RequirementsPath $telemetryReq -PythonExe $pythonExe -StampDir $stampDir
}
else {
    Write-WarnLine "telemetry-service requirements not found; service will be skipped"
}

$npmCommand = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    Fail-Script "npm was not found. Install Node.js and rerun run-local.ps1"
}
$npmExe = $npmCommand.Source
$vizPath = Join-Path $root "services\visualization"
Ensure-FrontendDependencies -FrontendPath $vizPath -NpmExe $npmExe -StampDir $stampDir

Write-Section "Checking local services"
try {
    $gpuInfo = & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null
    if ($gpuInfo) {
        Write-Ok "GPU detected: $gpuInfo"
    }
    else {
        Write-WarnLine "No GPU detected; services will fall back to CPU"
    }
}
catch {
    Write-WarnLine "No GPU detected; services will fall back to CPU"
}

$cudaBase = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
if (Test-Path -LiteralPath $cudaBase) {
    $latestCuda = Get-ChildItem $cudaBase | Sort-Object Name -Descending | Select-Object -First 1
    if ($latestCuda) {
        $env:PATH += ";$($latestCuda.FullName)\bin;$($latestCuda.FullName)\lib\x64"
        Write-Ok "CUDA detected: $($latestCuda.Name)"
    }
}
else {
    Write-WarnLine "CUDA toolkit not found on the default path"
}

try {
    $conn = New-Object System.Net.Sockets.TcpClient
    $conn.Connect("127.0.0.1", 6379)
    $conn.Close()
    Write-Ok "Redis detected on port 6379"
}
catch {
    Write-WarnLine "Redis not detected; streaming-only features stay disabled"
}

$ports = @{
    8001 = "data-service"
    8002 = "routing-engine"
    8003 = "prediction-service"
    8004 = "telemetry-service"
}
Ensure-PortAvailability -Ports $ports

Write-Section "Validating docker-compose.yml"
$composePath = Join-Path $root "docker-compose.yml"
if (Test-Path -LiteralPath $composePath) {
    $composeContent = Get-Content -LiteralPath $composePath -Raw
    if ($composeContent -match "SUPPORTED_CITIES=bangalore" -and $composeContent -match "APP_CACHE_DIR") {
        Write-Ok "docker-compose.yml is aligned with Bangalore-only caching"
    }
    else {
        Write-WarnLine "docker-compose.yml does not yet advertise Bangalore-only cache settings"
    }
}

Write-Section "Starting backend services"
$commonEnv = @(
    "SUPPORTED_CITIES='bangalore'",
    "DEFAULT_CITY='bangalore'",
    "APP_CACHE_DIR='$cacheRoot'",
    "GRAPH_CACHE_DIR='$graphCacheDir'",
    "HOTSPOT_CACHE_PATH='$hotspotCachePath'",
    "ROUTE_CACHE_PATH='$routeCachePath'",
    "ROUTING_MODES='fastest,balanced,connected'",
    "HEATMAP_VIEWPORT_ONLY='1'",
    "OPENCELLID_TOKEN='pk.37dddd741049308fd26c175be7a5aea0'"
)

$predictionPath = Join-Path $root "services\prediction-service"
Start-ServiceWindow -Name "prediction-service" -ServicePath $predictionPath -Port 8003 -PythonExe $pythonExe -VenvActivate $venvActivate -EnvAssignments ($commonEnv + @("MAX_RAM_MB='1024'")) | Out-Null
Wait-ForHttpJson -Name "prediction-service" -Url "http://127.0.0.1:8003/health" -Validator { param($json) $json.status -eq "ok" }

$dataPath = Join-Path $root "services\data-service"
Start-ServiceWindow -Name "data-service" -ServicePath $dataPath -Port 8001 -PythonExe $pythonExe -VenvActivate $venvActivate -EnvAssignments ($commonEnv + @("PREDICTION_SERVICE_URL='http://127.0.0.1:8003'", "MAX_RAM_MB='1536'")) | Out-Null
Wait-ForHttpJson -Name "data-service" -Url "http://127.0.0.1:8001/health" -Validator {
    param($json)
    $json.status -eq "ok" -and $json.graph_ready -eq $true
}

$routingPath = Join-Path $root "services\routing-engine"
$routingWorkers = if ($env:OS -eq "Windows_NT") { 1 } else { 4 }
Start-ServiceWindow -Name "routing-engine" -ServicePath $routingPath -Port 8002 -PythonExe $pythonExe -VenvActivate $venvActivate -EnvAssignments ($commonEnv + @("DATA_SERVICE_URL='http://127.0.0.1:8001'", "MAX_RAM_MB='2048'")) -DisableReload -Workers $routingWorkers | Out-Null
Wait-ForHttpJson -Name "routing-engine" -Url "http://127.0.0.1:8002/health" -Validator {
    param($json)
    $json.status -eq "ok" -and $json.graph_ready -eq $true
}

$telemetryPath = Join-Path $root "services\telemetry-service"
if (Test-Path -LiteralPath $telemetryPath) {
    Start-ServiceWindow -Name "telemetry-service" -ServicePath $telemetryPath -Port 8004 -PythonExe $pythonExe -VenvActivate $venvActivate -EnvAssignments ($commonEnv + @("MAX_RAM_MB='256'")) | Out-Null
}
else {
    Write-WarnLine "telemetry-service directory not found; skipping"
}

Write-Section "Starting frontend"
Write-Info "Local mode uses the Vite proxy instead of the nginx gateway"
$frontendPortInfo = Resolve-FrontendPort -PreferredPort 5173
$frontendPort = [int]$frontendPortInfo.Port
$frontendLogPath = Join-Path $cacheRoot "frontend-dev.log"
if (Test-Path -LiteralPath $frontendLogPath) {
    Remove-Item -LiteralPath $frontendLogPath -Force -ErrorAction SilentlyContinue
}
$frontendDisplayUrl = "http://localhost:$frontendPort"
if ($frontendPortInfo.ReuseExisting) {
    Write-Ok "Reusing existing frontend on port $frontendPort"
}
else {
    Write-Host "[frontend] Starting dev server on port $frontendPort..." -ForegroundColor Cyan
    $frontendCommand = @"
Set-Location '$vizPath'
Write-Host '[frontend] Starting dev server on port $frontendPort...' -ForegroundColor Cyan
& '$npmExe' run dev -- --host 0.0.0.0 --port $frontendPort --configLoader native 2>&1 | Tee-Object -FilePath '$frontendLogPath'
exit `$LASTEXITCODE
"@
    $frontendProcess = Start-Process powershell.exe -ArgumentList @(
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        $frontendCommand
    ) -WorkingDirectory $vizPath -PassThru
    Wait-ForHttpPage -Name "frontend" -Url $frontendDisplayUrl -Process $frontendProcess -LogPath $frontendLogPath
    Write-Ok "Started visualization on port $frontendPort"
}

Write-Section "run-local.ps1 complete"
Write-Host "Frontend:   $frontendDisplayUrl" -ForegroundColor White
Write-Host "Data:       http://localhost:8001/docs" -ForegroundColor White
Write-Host "Routing:    http://localhost:8002/docs" -ForegroundColor White
Write-Host "Prediction: http://localhost:8003/docs" -ForegroundColor White
if (Test-Path -LiteralPath $telemetryPath) {
    Write-Host "Telemetry:  http://localhost:8004/docs" -ForegroundColor White
}
Write-Host ""
Write-Info "Bangalore is the only supported city in this startup flow"
Write-Info "Cache is reused from $cacheRoot"
