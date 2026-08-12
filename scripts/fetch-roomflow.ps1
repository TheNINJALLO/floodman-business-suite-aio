$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Repository = (Get-Content (Join-Path $Root "vendor/roomflow/REPOSITORY") -Raw).Trim()
$Commit = (Get-Content (Join-Path $Root "vendor/roomflow/PINNED_COMMIT") -Raw).Trim()
$DestinationInput = if ($args.Count -gt 0) { $args[0] } else { Join-Path $Root "vendor/roomflow/source" }
$Destination = [IO.Path]::GetFullPath($DestinationInput)

function Invoke-GitChecked {
    param([Parameter(Mandatory = $true)][string[]] $GitArguments)
    $Output = & git @GitArguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $Output
}

$RepositoryGitArguments = @("-c", "safe.directory=$Destination", "-C", $Destination, "-c", "core.longpaths=true")

if (Test-Path (Join-Path $Destination ".git")) {
    $Dirty = (Invoke-GitChecked -GitArguments ($RepositoryGitArguments + @("status", "--porcelain"))) -join "`n"
    if (-not [string]::IsNullOrWhiteSpace($Dirty)) {
        throw "RoomFlow source has uncommitted work; refusing to overwrite $Destination"
    }
    Invoke-GitChecked -GitArguments ($RepositoryGitArguments + @("fetch", "--depth", "1", "origin", $Commit))
} else {
    if (Test-Path $Destination) {
        throw "Destination exists but is not a Git checkout; refusing to remove $Destination"
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Invoke-GitChecked -GitArguments @("-c", "core.longpaths=true", "clone", "--filter=blob:none", "--no-checkout", $Repository, $Destination)
    Invoke-GitChecked -GitArguments ($RepositoryGitArguments + @("fetch", "--depth", "1", "origin", $Commit))
}
Invoke-GitChecked -GitArguments ($RepositoryGitArguments + @("checkout", "--detach", $Commit))
$Actual = ((Invoke-GitChecked -GitArguments ($RepositoryGitArguments + @("rev-parse", "HEAD"))) -join "").Trim()
if ($Actual -ne $Commit) { throw "Expected $Commit but checked out $Actual" }
$Missing = (Invoke-GitChecked -GitArguments ($RepositoryGitArguments + @("ls-files", "--deleted"))) -join "`n"
if (-not [string]::IsNullOrWhiteSpace($Missing)) { throw "Pinned checkout is missing tracked files" }
Write-Host "RoomFlow ready at $Destination ($Actual)"
