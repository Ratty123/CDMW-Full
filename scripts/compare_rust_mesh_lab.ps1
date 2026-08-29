[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExpectedManifest,
    [Parameter(Mandatory = $true)]
    [string]$ActualManifest,
    [switch]$Release
)

$ErrorActionPreference = 'Stop'
$workspace = Join-Path $PSScriptRoot '..\tools\rust_mesh_lab'
$profileName = if ($Release) { 'release' } else { 'debug' }
$binary = Join-Path $workspace "target\$profileName\cdmw_asset_probe.exe"
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    Push-Location -LiteralPath $workspace
    try {
        $profileArgs = if ($Release) { @('--release') } else { @() }
        & cargo build -p cdmw_asset_probe @profileArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

Write-Host "Comparing with: $binary"
& $binary compare `
    (Resolve-Path -LiteralPath $ExpectedManifest).Path `
    (Resolve-Path -LiteralPath $ActualManifest).Path
exit $LASTEXITCODE
