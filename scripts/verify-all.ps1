$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
python scripts/generate_inventory.py
python scripts/verify_repo.py
Write-Host "Floodman source verification completed."
