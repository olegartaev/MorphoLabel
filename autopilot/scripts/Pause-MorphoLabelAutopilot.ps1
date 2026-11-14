$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$control = Join-Path $root 'autopilot\control'
New-Item -ItemType Directory -Force -Path $control | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $control 'PAUSE') | Out-Null
'Pause requested. The autopilot will pause at the next safe checkpoint.'
