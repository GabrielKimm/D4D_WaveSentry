[CmdletBinding()]
param(
    [string]$Python,
    [switch]$Inference,
    [switch]$Dev,
    [switch]$Satellite,
    [switch]$OptimizeModel
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($OptimizeModel -and -not $Inference) {
    throw '-OptimizeModel requires -Inference and a separately supplied model.'
}
if (-not $Python) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $Python = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 or pass -Python <python.exe>.' }
    } else {
        $command = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $command) { throw 'Install Python 3.12 x64 or pass -Python <python.exe>.' }
        $Python = $command.Source
    }
}
& $Python -c 'import sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize("P") == 8 else 1)'
if ($LASTEXITCODE -ne 0) { throw 'WaveSentry requires Python 3.12 x64.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPython -c 'import sys, struct; sys.exit(0 if sys.version_info[:2] == (3, 12) and struct.calcsize("P") == 8 else 1)'
if ($LASTEXITCODE -ne 0) { throw 'The existing .venv must use Python 3.12 x64.' }
$requirements = if ($Inference) { 'requirements-inference.txt' } else { 'requirements.txt' }
& $venvPython -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if ($Dev) {
    & $venvPython -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Test dependency installation failed.' }
}
if ($Satellite) {
    & $venvPython tools\vendor_cesium.py
    if ($LASTEXITCODE -ne 0) { throw 'Satellite asset installation failed.' }
}
if ($OptimizeModel) {
    & $venvPython tools\optimize_model.py
    if ($LASTEXITCODE -ne 0) { throw 'Model export failed.' }
}
Write-Host 'Ready: Start WaveSentry.cmd or Start Demo.cmd. RF setup: docs/SETUP.md'
