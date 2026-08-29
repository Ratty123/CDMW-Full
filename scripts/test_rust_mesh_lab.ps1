[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = Join-Path $PSScriptRoot '..\tools\rust_mesh_lab'

Push-Location -LiteralPath $workspace
try {
    $commands = @(
        @('fmt', '--all', '--check'),
        @('clippy', '--workspace', '--all-targets', '--all-features', '--', '-D', 'warnings'),
        @('test', '--workspace', '--all-features'),
        @('build', '--workspace', '--release')
    )
    foreach ($arguments in $commands) {
        Write-Host "cargo $($arguments -join ' ')"
        & cargo @arguments
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
} finally {
    Pop-Location
}
