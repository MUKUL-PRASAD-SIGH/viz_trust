# One AEGIS demo window. Started by scripts/demo.ps1 -- you don't run this yourself.
param([Parameter(Mandatory = $true)][ValidateSet("chain", "score", "oracle", "honest", "sloppy", "control", "web")][string]$Role)

$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$env:PYTHONIOENCODING = "utf-8"

$titles = @{
    chain   = "AEGIS 1 - blockchain (anvil)"
    score   = "AEGIS 2 - score service"
    oracle  = "AEGIS 3 - oracle"
    honest  = "AEGIS 4 - HonestAgent"
    sloppy  = "AEGIS 5 - SloppyAgent"
    control = "AEGIS 6 - CONTROL (type here)"
    web     = "AEGIS 7 - website (localhost:5173)"
}
$Host.UI.RawUI.WindowTitle = $titles[$Role]
Write-Host "== $($titles[$Role]) ==" -ForegroundColor Cyan

switch ($Role) {
    "chain"   { anvil }
    "score"   { Set-Location score; & .\.venv\Scripts\python.exe -m uvicorn app:app --port 8000 }
    "oracle"  { & .\oracle\.venv\Scripts\python.exe oracle\watcher.py }
    "honest"  { & .\agents\.venv\Scripts\python.exe agents\honest_agent.py }
    "sloppy"  { & .\agents\.venv\Scripts\python.exe agents\sloppy_agent.py }
    "control" { . (Join-Path $PSScriptRoot "demo_control.ps1") }
    "web"     {
        Set-Location web
        if (-not (Test-Path node_modules)) { npm install }
        npm run build
        npm run preview
    }
}
