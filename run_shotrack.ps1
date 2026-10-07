$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "No venv found. Run .\setup_shotrack.ps1 first."
}

.\.venv\Scripts\python.exe -m shotrack
exit $LASTEXITCODE
