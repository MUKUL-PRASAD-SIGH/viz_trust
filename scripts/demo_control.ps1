# The AEGIS control window: sets up the demo world, then gives you short commands.
# Loaded by scripts/demo_window.ps1 -Role control. Functions are global so they stay
# available at the prompt afterwards.

$global:AegisRoot = Split-Path $PSScriptRoot -Parent
$global:AegisWindow = Join-Path $PSScriptRoot "demo_window.ps1"

function global:Open-AegisWindow([string]$Role) {
    Start-Process powershell -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$global:AegisWindow`" -Role $Role"
}

function global:Wait-AegisPort([int]$Port, [string]$What) {
    Write-Host "Waiting for $What on port $Port..." -NoNewline
    for ($i = 0; $i -lt 120; $i++) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect("127.0.0.1", $Port); $client.Close()
            Write-Host " ready" -ForegroundColor Green
            return
        } catch { Start-Sleep -Milliseconds 500; Write-Host "." -NoNewline }
    }
    throw "$What did not come up on port $Port. Check its window."
}

function global:Stop-AegisAgents {
    # The agent processes, then the windows that hosted them.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*_agent.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*demo_window.ps1*-Role honest*" -or $_.CommandLine -like "*demo_window.ps1*-Role sloppy*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function global:Initialize-AegisWorld {
    Push-Location $global:AegisRoot
    try {
        Wait-AegisPort 8545 "the blockchain"
        Wait-AegisPort 8000 "the score service"

        Write-Host "`nDeploying contracts..." -ForegroundColor Cyan
        Push-Location contracts
        python script\deploy_local.py *> $null
        $deployed = $LASTEXITCODE
        Pop-Location
        if ($deployed -ne 0) { throw "Deploy failed. Run: cd contracts; python script\deploy_local.py" }
        Write-Host "Contracts deployed (real AegisEscrow + MockUSDC)." -ForegroundColor Green

        Write-Host "`nSeeding agent history (about 30 seconds)..." -ForegroundColor Cyan
        & .\agents\.venv\Scripts\python.exe agents\seed_demo.py
        if ($LASTEXITCODE -ne 0) { throw "Seeding failed; see above." }

        Write-Host "`nStarting HonestAgent and SloppyAgent windows..." -ForegroundColor Cyan
        Stop-AegisAgents
        Open-AegisWindow honest
        Open-AegisWindow sloppy
        Start-Sleep -Seconds 3
    } finally {
        Pop-Location
    }
}

function global:honest {
    Push-Location $global:AegisRoot
    & .\agents\.venv\Scripts\python.exe agents\demo_driver.py --worker HonestAgent
    Pop-Location
}

function global:sloppy {
    Push-Location $global:AegisRoot
    & .\agents\.venv\Scripts\python.exe agents\demo_driver.py --worker SloppyAgent
    Pop-Location
}

function global:multi {
    Push-Location $global:AegisRoot
    & .\agents\.venv\Scripts\python.exe agents\multi_driver.py parallel
    Pop-Location
}

function global:swarm {
    Push-Location $global:AegisRoot
    & .\agents\.venv\Scripts\python.exe agents\multi_driver.py swarm
    Pop-Location
}

function global:dashboard {
    Start-Process "http://localhost:5173/dashboard"
}

function global:reset {
    # Fresh chain + fresh seed. The score service and oracle keep running; the oracle
    # notices the new chain by itself.
    Write-Host "Resetting the demo world..." -ForegroundColor Yellow
    Stop-AegisAgents
    Stop-Process -Name anvil -Force -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*demo_window.ps1*-Role chain*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    Open-AegisWindow chain
    Initialize-AegisWorld
    menu
}

function global:menu {
    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Green
    Write-Host " AEGIS demo is READY. Type one of these and press Enter:" -ForegroundColor Green
    Write-Host "==============================================================" -ForegroundColor Green
    Write-Host "  honest      " -ForegroundColor Yellow -NoNewline; Write-Host "HonestAgent does a `$500 job   -> hirer posts 20%, score +7"
    Write-Host "  sloppy      " -ForegroundColor Yellow -NoNewline; Write-Host "SloppyAgent cheats, disputed   -> 613 to 382, 40% to 100%"
    Write-Host "  multi       " -ForegroundColor Yellow -NoNewline; Write-Host "Hirer opens 5 jobs at once with HonestAgent (after honest/sloppy)"
    Write-Host "  swarm       " -ForegroundColor Yellow -NoNewline; Write-Host "5 unknown hirers hire HonestAgent at once, 100% deposit"
    Write-Host "  dashboard   " -ForegroundColor Yellow -NoNewline; Write-Host "open the live dashboard again"
    Write-Host "  reset       " -ForegroundColor Yellow -NoNewline; Write-Host "fresh chain + fresh seed (before each full run-through)"
    Write-Host "  menu        " -ForegroundColor Yellow -NoNewline; Write-Host "show this list again"
    Write-Host ""
}

try {
    Initialize-AegisWorld
    Wait-AegisPort 5173 "the website"
    dashboard
    menu
} catch {
    Write-Host "`nSETUP FAILED: $_" -ForegroundColor Red
    Write-Host "Fix the problem shown above, then type:  reset" -ForegroundColor Red
}
