param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $repoRoot "apps\api"
$venvSitePackages = Join-Path $apiRoot ".venv\Lib\site-packages"

if (-not (Test-Path $venvSitePackages)) {
    throw "Missing backend site-packages at $venvSitePackages. Install dependencies first."
}

$pythonLauncher = if (Get-Command py -ErrorAction SilentlyContinue) {
    @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    @("python")
} else {
    throw "Python launcher not found. Install Python 3 and ensure 'py' or 'python' is on PATH."
}

$existingPythonPath = $env:PYTHONPATH
$pythonPathEntries = @($apiRoot, $venvSitePackages)
if ($existingPythonPath) {
    $pythonPathEntries += $existingPythonPath
}
$env:PYTHONPATH = $pythonPathEntries -join ";"

Write-Host "Starting API with $($pythonLauncher -join ' ') on http://$HostAddress`:$Port"
$pythonLauncherArgs = @()
if ($pythonLauncher.Length -gt 1) {
    $pythonLauncherArgs = $pythonLauncher[1..($pythonLauncher.Length - 1)]
}

& $pythonLauncher[0] @pythonLauncherArgs `
    -m uvicorn app.main:app --host $HostAddress --port $Port --app-dir apps/api
