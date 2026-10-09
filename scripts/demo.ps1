# Start the whole AEGIS live demo in seven windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
#
# Stops anything left over from a previous run, then opens:
#   1 blockchain (anvil)   2 score service   3 oracle
#   4 HonestAgent          5 SloppyAgent     6 CONTROL -- where you type `honest` / `sloppy`
#   7 website (http://localhost:5173)
# The control window deploys, seeds, starts the two agents, and opens the dashboard.

$window = Join-Path $PSScriptRoot "demo_window.ps1"

Write-Host "Stopping anything left over from a previous run..."
Stop-Process -Name anvil -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*uvicorn*" -or $_.CommandLine -like "*watcher.py*" -or $_.CommandLine -like "*_agent.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -like "*vite*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*demo_window.ps1*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

foreach ($role in "chain", "score", "oracle", "web", "control") {
    Start-Process powershell -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$window`" -Role $role"
    Start-Sleep -Milliseconds 400
}

Write-Host "Opened the windows. Watch 'AEGIS 6 - CONTROL' until it says READY."
