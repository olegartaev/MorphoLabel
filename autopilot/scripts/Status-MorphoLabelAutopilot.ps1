$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
python autopilot/scripts/morpholabel_autopilot.py --config autopilot/config/autopilot.config.json --status
