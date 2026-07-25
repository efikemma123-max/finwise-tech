$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (-not (Test-Path "venv\Scripts\python.exe")) {
    throw "Python venv not found at venv\Scripts\python.exe"
}

& "venv\Scripts\python.exe" -m finwise_model.runtime_cli create finwise-scratch:0.1 -f finwise_model\FinwiseModelfile
& "venv\Scripts\python.exe" -m uvicorn finwise_model.local_runtime:app --host 127.0.0.1 --port 11435
