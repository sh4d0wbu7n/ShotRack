$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python was not found on PATH. Run this script from a terminal where Python 3.13 is available, or edit the script to use the full python.exe path."
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$env:TEMP = Join-Path $root ".tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r requirements.txt

Write-Host "ShotRack setup complete."
Write-Host "Run with: .\.venv\Scripts\python.exe -m shotrack"
