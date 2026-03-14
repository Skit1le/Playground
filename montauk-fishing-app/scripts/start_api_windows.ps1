param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$Background,
    [switch]$NewWindow,
    [switch]$ForceRestart,
    [int]$WaitForHealthSeconds = 15
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $repoRoot "apps\api"
$venvSitePackages = Join-Path $apiRoot ".venv\Lib\site-packages"
$runRoot = Join-Path $apiRoot ".run"
$pidPath = Join-Path $runRoot "api.pid"
$stdoutLogPath = Join-Path $runRoot "api.stdout.log"
$stderrLogPath = Join-Path $runRoot "api.stderr.log"
$windowCommandPath = Join-Path $runRoot "api_window.cmd"
$backgroundCommandPath = Join-Path $runRoot "api_background.cmd"
$windowRunnerPath = Join-Path $repoRoot "scripts\run_api_window.ps1"
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

function Format-PowerShellSingleQuoted([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Get-ListeningProcessId([int]$ListeningPort) {
    try {
        $connection = Get-NetTCPConnection -State Listen -LocalPort $ListeningPort -ErrorAction Stop | Select-Object -First 1
        if ($connection) {
            return [int]$connection.OwningProcess
        }
    } catch {
    }

    try {
        $netstatLine = cmd /c "netstat -ano | findstr LISTENING | findstr :$ListeningPort" | Select-Object -First 1
        if ($netstatLine) {
            $parts = ($netstatLine -split "\s+") | Where-Object { $_ }
            $pidCandidate = $parts[-1]
            if ($pidCandidate -as [int]) {
                return [int]$pidCandidate
            }
        }
    } catch {
    }

    return $null
}

function Wait-ForPortToClear([int]$ListeningPort, [int]$TimeoutSeconds = 10) {
    $attemptCount = [Math]::Max(1, $TimeoutSeconds * 2)
    for ($attempt = 0; $attempt -lt $attemptCount; $attempt++) {
        if (-not (Get-ListeningProcessId -ListeningPort $ListeningPort)) {
            return
        }
        Start-Sleep -Milliseconds 500
    }

    $remainingPid = Get-ListeningProcessId -ListeningPort $ListeningPort
    if ($remainingPid) {
        throw "Port $ListeningPort is still owned by PID $remainingPid after waiting for shutdown."
    }
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
        Wait-ForPortToClear -ListeningPort $Port
    }
}

function Wait-ForApiHealth([System.Diagnostics.Process]$Process) {
    $attemptCount = [Math]::Max(1, $WaitForHealthSeconds * 2)
    for ($attempt = 0; $attempt -lt $attemptCount; $attempt++) {
        if ($Process.HasExited) {
            $stdoutTail = ""
            $stderrTail = ""
            if (Test-Path $stdoutLogPath) {
                $stdoutTail = (Get-Content -Path $stdoutLogPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            }
            if (Test-Path $stderrLogPath) {
                $stderrTail = (Get-Content -Path $stderrLogPath -Tail 40 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
            }
            throw "API process exited early with code $($Process.ExitCode). Stdout:`n$stdoutTail`nStderr:`n$stderrTail"
        }

        try {
            $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                $listeningPid = Get-ListeningProcessId -ListeningPort $Port
                if ($listeningPid -eq $Process.Id) {
                    return
                }
            }
        } catch {
        }

        Start-Sleep -Milliseconds 500
    }

    $listeningPid = Get-ListeningProcessId -ListeningPort $Port
    if ($listeningPid -and $listeningPid -ne $Process.Id) {
        throw "Health check passed for a different process (PID $listeningPid) while started process PID $($Process.Id) never claimed port $Port."
    }

    throw "API did not become healthy within $WaitForHealthSeconds seconds. Re-run with -Foreground for console output."
}

if (-not (Test-Path $venvSitePackages)) {
    throw "Missing backend site-packages at $venvSitePackages. Install dependencies first."
}

if ($NewWindow -and -not (Test-Path $windowRunnerPath)) {
    throw "Missing helper script at $windowRunnerPath."
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
$formattedArgs = ($allArgs | ForEach-Object { Format-CommandArgument $_ }) -join " "

if (-not $Background) {
    if ($NewWindow) {
        $windowScript = @"
@echo off
set "PYTHONPATH=$($env:PYTHONPATH)"
cd /d "$repoRoot"
"$($launcher.FilePath)" $formattedArgs
"@
        Set-Content -Path $windowCommandPath -Value $windowScript -Encoding ASCII

        $process = Start-Process `
            -FilePath "cmd.exe" `
            -ArgumentList @("/k", $windowCommandPath) `
            -WorkingDirectory $repoRoot `
            -PassThru

        Set-Content -Path $pidPath -Value $process.Id
        Write-Host "API launched in a dedicated command window."
        Write-Host "  PID: $($process.Id)"
        Write-Host "  Health: $healthUrl"
        exit 0
    }

    Set-Location $repoRoot
    & $launcher.FilePath @allArgs
    exit $LASTEXITCODE
}

Remove-Item -Path $stdoutLogPath -Force -ErrorAction SilentlyContinue
Remove-Item -Path $stderrLogPath -Force -ErrorAction SilentlyContinue

$pythonPathValue = $env:PYTHONPATH
$backgroundScript = @"
@echo off
set "PYTHONPATH=$pythonPathValue"
cd /d "$repoRoot"
"$($launcher.FilePath)" $formattedArgs 1>> "$stdoutLogPath" 2>> "$stderrLogPath"
"@
Set-Content -Path $backgroundCommandPath -Value $backgroundScript -Encoding ASCII

$process = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/c", $backgroundCommandPath) `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -PassThru

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
