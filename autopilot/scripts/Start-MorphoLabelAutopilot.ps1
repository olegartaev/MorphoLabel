param(
  [switch]$Foreground,
  [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$control = Join-Path $root 'autopilot\control'
$runtime = Join-Path $root 'autopilot\runtime'
New-Item -ItemType Directory -Force -Path $control, $runtime | Out-Null
Remove-Item -LiteralPath (Join-Path $control 'STOP') -Force -ErrorAction SilentlyContinue
$pidFile = Join-Path $runtime 'autopilot.pid'
if (Test-Path $pidFile) {
  $existingPid = [int](Get-Content -LiteralPath $pidFile -Raw)
  $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
  if ($existing) { throw "Autopilot already running, PID $existingPid" }
}
$args = @('autopilot/scripts/morpholabel_autopilot.py', '--config', 'autopilot/config/autopilot.config.json', '--once')
if ($DryRun) { $args += '--dry-run' }
if ($Foreground) {
  python @args
  exit $LASTEXITCODE
}
$p = Start-Process -FilePath 'python' -ArgumentList $args -WorkingDirectory $root -WindowStyle Hidden -PassThru
$p.Id | Set-Content -LiteralPath $pidFile -Encoding ascii
"Started MorphoLabel autopilot PID $($p.Id). Stop with AUTOPILOT_STOP.cmd; pause with AUTOPILOT_PAUSE.cmd."
