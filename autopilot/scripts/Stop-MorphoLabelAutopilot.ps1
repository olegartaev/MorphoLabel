param(
  [switch]$ForceKillCoordinator
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$control = Join-Path $root 'autopilot\control'
$runtime = Join-Path $root 'autopilot\runtime'
New-Item -ItemType Directory -Force -Path $control | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $control 'STOP') | Out-Null
'Stop requested. Codex tasks already queued are not killed; the coordinator stops at the next checkpoint.'
if ($ForceKillCoordinator) {
  $pidFile = Join-Path $runtime 'autopilot.pid'
  if (Test-Path $pidFile) {
    $pidValue = [int](Get-Content -LiteralPath $pidFile -Raw)
    $p = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($p) { Stop-Process -Id $pidValue -Force; "Coordinator PID $pidValue stopped." }
  }
}
