$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$env:PYINSTALLER_CONFIG_DIR = Join-Path $root ".tmp\pyinstaller"
$env:TEMP = Join-Path $root ".tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:PYINSTALLER_CONFIG_DIR | Out-Null

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "No venv found. Run .\setup_shotrack.ps1 first."
}

$version = & .\.venv\Scripts\python.exe -c "from shotrack import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) { throw "Could not read the ShotRack version." }
$packageName = "ShotRack-$version"
$versioned = Join-Path $root "dist\$packageName"
if (Test-Path -LiteralPath $versioned) {
    throw "Package already exists: $versioned. Choose a new version or move the existing package before rebuilding."
}

# Only the bootstrap is frozen. App source and runtime libraries stay in _internal.
$appSource = Join-Path $root "build\portable-source\shotrack"
New-Item -ItemType Directory -Force $appSource | Out-Null
Get-ChildItem -LiteralPath (Join-Path $root "shotrack") -Filter "*.py" -File |
    Copy-Item -Destination $appSource
.\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name $packageName `
    --distpath dist `
    --workpath build `
    --specpath build `
    --exclude-module shotrack `
    --add-data "$appSource;app\shotrack" `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --hidden-import PySide6.QtMultimedia `
    --hidden-import PySide6.QtMultimediaWidgets `
    --hidden-import PIL.Image `
    --hidden-import PIL.ImageDraw `
    --hidden-import sqlite3 `
    --hidden-import ctypes.wintypes `
    --hidden-import dataclasses `
    --hidden-import datetime `
    --hidden-import json `
    --hidden-import tempfile `
    --hidden-import shutil `
    --hidden-import subprocess `
    .\shotrack_launcher.py
if ($LASTEXITCODE -ne 0) { throw "Portable launcher build failed." }

# Qt uses the Windows ICU API. DLLs with the same names from unrelated SDKs
# on PATH can be picked up by the dependency scanner and shadow that API.
$sidecarRoot = Join-Path $versioned "_internal"
foreach ($dll in Get-ChildItem -LiteralPath $sidecarRoot -File) {
    if ($dll.Name -match '^(icuuc|icuin|icudt\d+)\.dll$') {
        $resolvedDll = (Resolve-Path -LiteralPath $dll.FullName).Path
        if (-not $resolvedDll.StartsWith($sidecarRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unexpected dependency path: $resolvedDll"
        }
        Remove-Item -LiteralPath $resolvedDll
    }
}

Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination $versioned
foreach ($sourceFile in Get-ChildItem -LiteralPath (Join-Path $root "shotrack") -Filter "*.py" -File) {
    $packagedFile = Join-Path $sidecarRoot ("app\shotrack\" + $sourceFile.Name)
    if ((Get-FileHash -LiteralPath $sourceFile.FullName).Hash -ne (Get-FileHash -LiteralPath $packagedFile).Hash) {
        throw "Packaged source does not match: $packagedFile"
    }
}
$zipPath = Join-Path $root "dist\$packageName-windows-portable.zip"
Compress-Archive -LiteralPath $versioned -DestinationPath $zipPath -Force

Write-Host "Portable build complete:"
Write-Host $versioned
Write-Host "Run this executable:"
Write-Host (Join-Path $versioned "$packageName.exe")
Write-Host "Keep the _internal sidecar folder beside the launcher."
Write-Host "Release archive: $zipPath"
