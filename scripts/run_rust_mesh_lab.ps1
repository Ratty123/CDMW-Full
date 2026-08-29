[CmdletBinding()]
param(
    [string]$ArchiveRoot,
    [string]$MeshPath,
    [switch]$Release
)

$ErrorActionPreference = 'Stop'
if ($ArchiveRoot -and $MeshPath) {
    throw 'Choose ArchiveRoot or MeshPath, not both.'
}

$workspace = Join-Path $PSScriptRoot '..\tools\rust_mesh_lab'
$profileName = if ($Release) { 'release' } else { 'debug' }
$binary = Join-Path $workspace "target\$profileName\cdmw_mesh_lab.exe"
if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
    & (Join-Path $PSScriptRoot 'build_rust_mesh_lab.ps1') -Release:$Release
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$arguments = @()
if ($ArchiveRoot) {
    $arguments += @('--archive-root', (Resolve-Path -LiteralPath $ArchiveRoot).Path)
}
if ($MeshPath) {
    $arguments += @('--mesh', (Resolve-Path -LiteralPath $MeshPath).Path)
}

Write-Host "Launching CDMW Rust Mesh Lab: $binary"
& $binary @arguments
exit $LASTEXITCODE
