[CmdletBinding()]
param(
    [switch]$Release
)

$ErrorActionPreference = 'Stop'
$workspace = Join-Path $PSScriptRoot '..\tools\rust_mesh_lab'
$profileArgs = if ($Release) { @('--release') } else { @() }
$profileName = if ($Release) { 'release' } else { 'debug' }

Push-Location -LiteralPath $workspace
try {
    & cargo build --workspace @profileArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    $binary = Join-Path $workspace "target\$profileName\cdmw_mesh_lab.exe"
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
        throw "Rust Mesh Lab binary was not produced: $binary"
    }
    Write-Host "Built CDMW Rust Mesh Lab: $binary"
} finally {
    Pop-Location
}
