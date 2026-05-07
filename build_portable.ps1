$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$env:PYINSTALLER_CONFIG_DIR = Join-Path $root ".tmp\pyinstaller"
New-Item -ItemType Directory -Force $env:PYINSTALLER_CONFIG_DIR | Out-Null

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "No venv found. Run .\setup_shotrack.ps1 first."
}

.\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name ShotRack `
    --distpath dist `
    --workpath build `
    --collect-all PySide6 `
    --collect-all shiboken6 `
    .\shotrack_launcher.py

$versioned = Join-Path $root "dist\ShotRack-0.0.2"
if (Test-Path $versioned) {
    Remove-Item -LiteralPath $versioned -Recurse -Force
}
Rename-Item -LiteralPath (Join-Path $root "dist\ShotRack") -NewName "ShotRack-0.0.2"

Write-Host "Portable build complete:"
Write-Host $versioned
Write-Host "Run this executable:"
Write-Host (Join-Path $versioned "ShotRack.exe")
Write-Host "Do not run ShotRack.exe from the build folder; that is PyInstaller temporary output."
