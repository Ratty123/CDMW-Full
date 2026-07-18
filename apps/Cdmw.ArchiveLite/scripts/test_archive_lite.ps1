param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$liteRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $liteRoot "..\.."))
$nativeRoot = Join-Path $repositoryRoot "native\cdmw_archive_core"
$nativeBuild = Join-Path $nativeRoot "build"
$solution = Join-Path $liteRoot "Cdmw.ArchiveLite.slnx"
$tests = Join-Path $liteRoot "tests\Cdmw.ArchiveLite.Tests\Cdmw.ArchiveLite.Tests.csproj"

function Assert-LastExitCode([string]$Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repositoryRoot
try {
    & (Join-Path $PSScriptRoot "verify_archive_lite_source.ps1")

    & cmake -S $nativeRoot -B $nativeBuild
    Assert-LastExitCode "Native archive-core configure"

    & cmake --build $nativeBuild --config $Configuration --parallel
    Assert-LastExitCode "Native archive-core build"

    & ctest --test-dir $nativeBuild -C $Configuration --output-on-failure
    Assert-LastExitCode "Native archive-core tests"

    & dotnet build $solution -c $Configuration --nologo --verbosity:minimal
    Assert-LastExitCode ".NET solution build"

    & dotnet run --project $tests -c $Configuration --no-build
    Assert-LastExitCode "Archive Lite focused tests"
}
finally {
    Pop-Location
}

Write-Host "CDMW Archive Lite validation passed ($Configuration)."
