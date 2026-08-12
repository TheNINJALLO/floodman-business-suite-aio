$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Repository = (Get-Content (Join-Path $Root "vendor/roomflow/REPOSITORY") -Raw).Trim()
$Commit = (Get-Content (Join-Path $Root "vendor/roomflow/PINNED_COMMIT") -Raw).Trim()
$Destination = if ($args.Count -gt 0) { $args[0] } else { Join-Path $Root "vendor/roomflow/source" }

if (Test-Path (Join-Path $Destination ".git")) {
    git -C $Destination fetch --depth 1 origin $Commit
} else {
    if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
    git clone --filter=blob:none --no-checkout $Repository $Destination
    git -C $Destination fetch --depth 1 origin $Commit
}
git -C $Destination checkout --detach $Commit
$Actual = (git -C $Destination rev-parse HEAD).Trim()
if ($Actual -ne $Commit) { throw "Expected $Commit but checked out $Actual" }
Write-Host "RoomFlow ready at $Destination ($Actual)"
