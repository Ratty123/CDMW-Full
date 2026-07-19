param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$backendRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $backendRoot "..\.."))
$nativeRoot = Join-Path $repositoryRoot "native\cdmw_full_archive_core"
$nativeBuild = Join-Path $nativeRoot "build"
$solution = Join-Path $backendRoot "Cdmw.FullArchive.slnx"
$tests = Join-Path $backendRoot "tests\Cdmw.FullArchive.Tests\Cdmw.FullArchive.Tests.csproj"

function Assert-LastExitCode([string]$Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

Push-Location $repositoryRoot
try {
    & cmake -S $nativeRoot -B $nativeBuild
    Assert-LastExitCode "Full archive native configure"
    & cmake --build $nativeBuild --config $Configuration --parallel
    Assert-LastExitCode "Full archive native build"
    & ctest --test-dir $nativeBuild -C $Configuration --output-on-failure
    Assert-LastExitCode "Full archive native tests"
    & dotnet build $solution -c $Configuration --nologo --verbosity:minimal
    Assert-LastExitCode "Full archive worker build"
    & dotnet run --project $tests -c $Configuration --no-build
    Assert-LastExitCode "Full archive focused tests"
}
finally {
    Pop-Location
}

Write-Host "CDMW full archive backend validation passed ($Configuration)."
