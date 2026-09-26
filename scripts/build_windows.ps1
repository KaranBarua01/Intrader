$ErrorActionPreference = "Stop"

Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Create the Python 3.11 virtual environment first."
}

.\.venv\Scripts\python.exe -m pip install -e ".[ui,build]"

if (Test-Path ".\build") { Remove-Item ".\build" -Recurse -Force }
if (Test-Path ".\dist\Intrader") { Remove-Item ".\dist\Intrader" -Recurse -Force }

.\.venv\Scripts\python.exe -m PyInstaller .\Intrader.spec --noconfirm

Write-Host ""
Write-Host "Intrader executable build complete:"
Write-Host "  dist\Intrader\Intrader.exe"
