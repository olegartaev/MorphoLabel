param(
    [ValidateSet("start", "finish", "status")]
    [string]$Mode = "status"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ExpectedRepo = "olegartaev/MorphoLabel"
$ExpectedBranch = "main"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    # Windows PowerShell 5 surfaces Git's informational stderr output as an
    # error record when $ErrorActionPreference is Stop. Capture it as text and
    # use Git's exit code as the authoritative success signal.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& git @Args 2>&1 | ForEach-Object { $_.ToString() })
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed:`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Get-SyncState {
    $status = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "git status failed" }

    $countsRaw = (Invoke-Git rev-list --left-right --count "origin/$ExpectedBranch...HEAD") -join ""
    $counts = $countsRaw.Trim() -split '\s+'
    if ($counts.Count -lt 2) { throw "Cannot parse git ahead/behind state: $countsRaw" }

    return [pscustomobject]@{
        Dirty  = ($status.Count -gt 0)
        Behind = [int]$counts[0]
        Ahead  = [int]$counts[1]
        Status = $status
    }
}

Push-Location $RepoRoot
try {
    $root = ((Invoke-Git rev-parse --show-toplevel) -join "").Trim()
    if ([IO.Path]::GetFullPath($root).TrimEnd('\') -ne [IO.Path]::GetFullPath($RepoRoot).TrimEnd('\')) {
        throw "Wrong git root: $root. Expected: $RepoRoot"
    }

    $branch = ((Invoke-Git branch --show-current) -join "").Trim()
    if ($branch -ne $ExpectedBranch) {
        throw "Wrong branch: $branch. Expected: $ExpectedBranch"
    }

    $remote = ((Invoke-Git remote get-url origin) -join "").Trim()
    if ($remote -notmatch 'olegartaev[/:]MorphoLabel(?:\.git)?$') {
        throw "Wrong origin remote: $remote. Expected repository: $ExpectedRepo"
    }

    Invoke-Git fetch --prune origin $ExpectedBranch | Out-Null
    $state = Get-SyncState

    if ($Mode -eq "status") {
        Write-Host "MorphoLabel sync status: dirty=$($state.Dirty), ahead=$($state.Ahead), behind=$($state.Behind)"
        if ($state.Dirty) { $state.Status | ForEach-Object { Write-Host $_ } }
        exit 0
    }

    if ($state.Dirty) {
        throw "Working tree has uncommitted changes. Automatic synchronization will not overwrite, stash, commit, or discard them. Codex must inspect and preserve them first."
    }

    if ($state.Ahead -gt 0 -and $state.Behind -gt 0) {
        throw "Local main and origin/main have diverged. Resolve non-destructively, rerun focused tests, then rerun synchronization."
    }

    if ($state.Behind -gt 0) {
        Invoke-Git pull --ff-only origin $ExpectedBranch | Out-Null
    }

    $state = Get-SyncState
    if ($state.Ahead -gt 0) {
        Invoke-Git push origin $ExpectedBranch | Out-Null
    }

    Invoke-Git fetch origin $ExpectedBranch | Out-Null
    $localHead = ((Invoke-Git rev-parse HEAD) -join "").Trim()
    $remoteHead = ((Invoke-Git rev-parse "origin/$ExpectedBranch") -join "").Trim()
    if ($localHead -ne $remoteHead) {
        throw "Synchronization incomplete: local HEAD $localHead != origin/$ExpectedBranch $remoteHead"
    }

    Write-Host "MorphoLabel synchronized: $localHead"
}
finally {
    Pop-Location
}
