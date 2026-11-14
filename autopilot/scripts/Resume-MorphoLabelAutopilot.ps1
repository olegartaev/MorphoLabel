$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$control = Join-Path $root 'autopilot\control'
Remove-Item -LiteralPath (Join-Path $control 'PAUSE') -Force -ErrorAction SilentlyContinue
'Pause cleared.'
