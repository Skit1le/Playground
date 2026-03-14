param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,
    [Parameter(Mandatory = $true)]
    [string]$PythonPathValue,
    [Parameter(Mandatory = $true)]
    [string]$HostAddress,
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [Parameter(Mandatory = $true)]
    [string]$PythonArgumentLine
)

$ErrorActionPreference = "Stop"

$env:PYTHONPATH = $PythonPathValue
Set-Location $RepoRoot

Write-Host "Starting API in dedicated window on http://$HostAddress`:$Port"
Write-Host "Python: $PythonExecutable"
Write-Host "PYTHONPATH: $PythonPathValue"
Write-Host "Args: $PythonArgumentLine"
Write-Host ""

$commandLine = '"' + $PythonExecutable + '" ' + $PythonArgumentLine
cmd.exe /c $commandLine
