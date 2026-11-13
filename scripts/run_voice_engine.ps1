$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = if ($env:SILFY_PYTHON) { $env:SILFY_PYTHON } else { Join-Path $Root 'python\.venv\Scripts\python.exe' }
$env:PYTHONPATH = Join-Path $Root 'python'
$env:SILFY_ROOT = $Root
$env:SILFY_CONFIG = Join-Path $Root 'config\voice.json'
& $Python -m voice_engine
