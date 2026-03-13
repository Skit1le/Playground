param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Background,
    [switch]$ForceRestart,
    [int]$WaitForHealthSeconds = 15
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $repoRoot "apps\api"
$venvSitePackages = Join-Path $apiRoot ".venv\Lib\site-packages"
$runRoot = Join-Path $apiRoot ".run"
$pidPath = Join-Path $runRoot "api.pid"
$healthUrl = "http://$HostAddress`:$Port/health"

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Resolve-PythonLauncher {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $pythonExecutable = & $pyCommand.Source -3 -c "import sys; print(sys.executable)"
        if ($LASTEXITCODE -eq 0 -and $pythonExecutable) {
            return @{
                FilePath = $pythonExecutable.Trim()
                PrefixArgs = @()
                Label = $pythonExecutable.Trim()
            }
        }

        return @{
            FilePath = $pyCommand.Source
            PrefixArgs = @("-3")
            Label = "py -3"
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @{
            FilePath = $pythonCommand.Source
            PrefixArgs = @()
            Label = "python"
        }
    }

    throw "Python launcher not found. Install Python 3 and ensure 'py' or 'python' is on PATH."
}

function Format-CommandArgument([string]$Value) {
    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $escaped = $Value.Replace('"', '\"')
    return '"' + $escaped + '"'
}

function Get-ListeningProcessId([int]$ListeningPort) {
    try {
        $connection = Get-NetTCPConnection -State Listen -LocalPort $ListeningPort -ErrorAction Stop | Select-Object -First 1
        if ($connection) {
            return [int]$connection.OwningProcess
        }
    } catch {
    }
    return $null
}

function Stop-ExistingApiProcess {
    $stopped = $false

    if (Test-Path $pidPath) {
        $pidValue = Get-Content -Path $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pidValue -and ($pidValue -as [int])) {
            $existingProcess = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
            if ($existingProcess) {
                Stop-Process -Id $existingProcess.Id -Force
                $stopped = $true
            }
        }
        Remove-Item -Path $pidPath -Force -ErrorAction SilentlyContinue
    }

    $listeningPid = Get-ListeningProcessId -ListeningPort $Port
    if ($listeningPid) {
        $existingProcess = Get-Process -Id $listeningPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Stop-Process -Id $existingProcess.Id -Force
            $stopped = $true
        }
    }

    if ($stopped) {
        Start-Sleep -Seconds 1
    }
}

function Wait-ForApiHealth([System.Diagnostics.Process]$Process) {
    $attemptCount = [Math]::Max(1, $WaitForHealthSeconds * 2)
    for ($attempt = 0; $attempt -lt $attemptCount; $attempt++) {
        if ($Process.HasExited) {
            throw "API process exited early with code $($Process.ExitCode). Re-run with -Foreground for console output."
        }

        try {
            $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
        }

        Start-Sleep -Milliseconds 500
    }

    throw "API did not become healthy within $WaitForHealthSeconds seconds. Re-run with -Foreground for console output."
}

if (-not (Test-Path $venvSitePackages)) {
    throw "Missing backend site-packages at $venvSitePackages. Install dependencies first."
}

Ensure-Directory -Path $runRoot
$launcher = Resolve-PythonLauncher
$pythonPathEntries = @($apiRoot, $venvSitePackages)
if ($env:PYTHONPATH) {
    $pythonPathEntries += $env:PYTHONPATH
}
$env:PYTHONPATH = $pythonPathEntries -join ";"

$uvicornArgs = @(
    "-m", "uvicorn",
    "app.main:app",
    "--host", $HostAddress,
    "--port", "$Port",
    "--app-dir", "apps/api"
)
$allArgs = @($launcher.PrefixArgs + $uvicornArgs)

if ($ForceRestart) {
    Stop-ExistingApiProcess
} else {
    $listeningPid = Get-ListeningProcessId -ListeningPort $Port
    if ($listeningPid) {
        $response = $null
        try {
            $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing
        } catch {
        }

        if ($response -and $response.StatusCode -eq 200) {
            Write-Host "API already running on $healthUrl (PID $listeningPid)."
            exit 0
        }

        throw "Port $Port is already in use by PID $listeningPid. Re-run with -ForceRestart to replace it."
    }
}

Write-Host "Starting API with $($launcher.Label) on http://$HostAddress`:$Port"

if (-not $Background) {
    Set-Location $repoRoot
    & $launcher.FilePath @allArgs
    exit $LASTEXITCODE
}

$formattedArgs = ($allArgs | ForEach-Object { Format-CommandArgument $_ }) -join " "

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $launcher.FilePath
$startInfo.Arguments = $formattedArgs
$startInfo.WorkingDirectory = $repoRoot
$startInfo.UseShellExecute = $true
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo

if (-not $process.Start()) {
    throw "Failed to start API process."
}

Set-Content -Path $pidPath -Value $process.Id

try {
    Wait-ForApiHealth -Process $process
} catch {
    Remove-Item -Path $pidPath -Force -ErrorAction SilentlyContinue
    throw
}

Write-Host "API started successfully."
Write-Host "  PID: $($process.Id)"
Write-Host "  Health: $healthUrl"
