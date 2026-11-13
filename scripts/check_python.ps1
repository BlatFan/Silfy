$ErrorActionPreference = 'Stop'
$Python = if ($env:SILFY_PYTHON) { $env:SILFY_PYTHON } else { 'py -3.15' }
Write-Host "Python command: $Python"
if ($env:SILFY_PYTHON) {
    & $env:SILFY_PYTHON --version
} else {
    py -3.15 --version
}
