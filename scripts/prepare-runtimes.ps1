$ErrorActionPreference = "Stop"
$app = Split-Path $PSScriptRoot -Parent
$python = Join-Path $app ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    & py -3.12 -m venv (Join-Path $app ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 é necessário somente na máquina de build." }
}
& $python -m pip install -r (Join-Path $PSScriptRoot "runtime-requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Falha ao preparar dependências de build." }
& $python (Join-Path $PSScriptRoot "build-runtimes.py")
if ($LASTEXITCODE -ne 0) { throw "Falha ao empacotar os motores integrados." }
