param(
    [Parameter(Mandatory=$true)][string]$Compiler,
    [string]$Workspace = (Split-Path $PSScriptRoot -Parent)
)
$ErrorActionPreference = 'Stop'
$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$testRoot = Join-Path $workspacePath 'diagnostics\installer-smoke'
$installedPath = Join-Path $testRoot 'installed'
$stateRoot = Join-Path $testRoot 'localappdata'
$statePath = Join-Path $stateRoot 'MorphoLabel'
$legacyPath = Join-Path $stateRoot 'SIMM'
$outputPath = Join-Path $testRoot 'setup'
$projectPath = Join-Path $testRoot 'disposable-project'
foreach ($path in @($testRoot,$installedPath,$stateRoot,$statePath,$legacyPath,$outputPath,$projectPath)) {
    $resolved = [IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($workspacePath + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Test path escaped workspace: $resolved"
    }
}
if (Test-Path -LiteralPath $installedPath) { throw 'Smoke installation already exists; inspect it before retrying.' }
New-Item -ItemType Directory -Force $outputPath,$statePath,$legacyPath,$projectPath | Out-Null
# Compile the SAME installer code with disposable registry and cleanup destinations.
# A test uninstall must never remove an existing user's installation or state.
$version = & (Join-Path $workspacePath '.venv\Scripts\python.exe') -c 'from app.version import __version__; print(__version__)'
& $Compiler /Qp "/DMyAppVersion=$version" '/DMyAppId={{67D95BA8-9533-4C16-BA7D-FB80D82B3D64}' "/DMyStateDir=$statePath" "/DMyLegacyStateDir=$legacyPath" "/DMyOutputDir=$outputPath" (Join-Path $workspacePath 'packaging\windows\MorphoLabel.iss')
if ($LASTEXITCODE -ne 0) { throw 'Smoke installer compilation failed' }
$setup = Get-ChildItem -LiteralPath $outputPath -Filter '*Setup-x64.exe' | Select-Object -First 1
$savedLocalAppData = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = $stateRoot
    $process = Start-Process -FilePath $setup.FullName -WindowStyle Hidden -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS',"/DIR=$installedPath" -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Install failed: $($process.ExitCode)" }
    $exe = Join-Path $installedPath 'MorphoLabel.exe'
    $process = Start-Process -FilePath $exe -WindowStyle Hidden -ArgumentList '--self-test' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Core self-test failed: $($process.ExitCode)" }
    $gui = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 6
    if ($gui.HasExited) { throw "GUI exited during startup: $($gui.ExitCode)" }
    Stop-Process -Id $gui.Id -Force
    foreach ($folder in @('components','downloads','starters')) {
        if (Test-Path -LiteralPath (Join-Path $statePath $folder)) { throw "Silent smoke unexpectedly prepared AI: $folder" }
    }
    if (Test-Path -LiteralPath (Join-Path $statePath 'first_run_setup.json')) { throw 'Silent smoke unexpectedly started setup' }
    # Exercise owned-state deletion while proving scientific data is untouched.
    Set-Content -LiteralPath (Join-Path $statePath 'owned-test.txt') -Value 'owned'
    # Managed OpenMMLab caches can exceed MAX_PATH, especially under long usernames.
    $longCache = Join-Path $statePath ('components\ai\cache\' + ('nested-cache\' * 20) + 'checkpoint.pyc')
    New-Item -ItemType Directory -Force (Split-Path $longCache -Parent) | Out-Null
    Set-Content -LiteralPath $longCache -Value 'owned extended-path cache'
    if ($longCache.Length -le 260 -or -not (Test-Path -LiteralPath $longCache)) { throw 'Long-path cleanup fixture missing' }
    Set-Content -LiteralPath (Join-Path $projectPath 'project-test.txt') -Value 'scientific'
    $process = Start-Process -FilePath (Join-Path $installedPath 'unins000.exe') -WindowStyle Hidden -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Uninstall failed: $($process.ExitCode)" }
    Start-Sleep -Seconds 2
    if (Test-Path -LiteralPath $statePath) { throw 'Uninstall left owned state behind' }
    if (Test-Path -LiteralPath $exe) { throw 'Uninstall left application behind' }
    if ((Get-Content -LiteralPath (Join-Path $projectPath 'project-test.txt')) -ne 'scientific') { throw 'Uninstall changed scientific project' }
    'PASS: silent install -> core self-test -> GUI -> uninstall; no AI download/setup; extended-path owned cache removed; scientific project preserved'
} finally {
    $env:LOCALAPPDATA = $savedLocalAppData
}
