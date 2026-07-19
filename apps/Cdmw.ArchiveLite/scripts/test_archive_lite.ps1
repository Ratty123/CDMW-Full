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
$previewRoot = Join-Path $repositoryRoot "native\cdmw_preview_core"
$previewBuild = Join-Path $previewRoot "build"
$acceleratorRoot = Join-Path $repositoryRoot "native\cdmw_archive_accelerator"
$acceleratorBuild = Join-Path $acceleratorRoot "build"
$meshCoreRoot = Join-Path $repositoryRoot "native\cdmw_mesh_core"
$meshCoreBuild = Join-Path $meshCoreRoot "build"
$textureRoot = Join-Path $repositoryRoot "native\cd_texture_dx"
$textureBuild = Join-Path $textureRoot "build"
$rendererProject = Join-Path $repositoryRoot "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
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

    & cmake -S $previewRoot -B $previewBuild
    Assert-LastExitCode "Native preview-core configure"

    & cmake --build $previewBuild --config $Configuration --parallel
    Assert-LastExitCode "Native preview-core build"

    & (Join-Path $previewBuild "$Configuration\cdmw-preview-core.exe") self-test
    Assert-LastExitCode "Native preview-core self-test"

    & cmake -S $acceleratorRoot -B $acceleratorBuild
    Assert-LastExitCode "Native archive-accelerator configure"

    & cmake --build $acceleratorBuild --config $Configuration --parallel
    Assert-LastExitCode "Native archive-accelerator build"
    $acceleratorExecutable = Join-Path $acceleratorBuild "$Configuration\cdmw-archive-accelerator.exe"
    & $acceleratorExecutable --version
    Assert-LastExitCode "Native archive-accelerator version check"

    & cmake -S $meshCoreRoot -B $meshCoreBuild
    Assert-LastExitCode "Native mesh-core configure"

    & cmake --build $meshCoreBuild --config $Configuration --parallel
    Assert-LastExitCode "Native mesh-core build"
    $meshCoreExecutable = Join-Path $meshCoreBuild "$Configuration\cdmw-mesh-core.exe"

    & cmake -S $textureRoot -B $textureBuild
    Assert-LastExitCode "Native DirectXTex configure"

    & cmake --build $textureBuild --config $Configuration --parallel
    Assert-LastExitCode "Native DirectXTex build"
    $textureExecutable = Join-Path $textureBuild "$Configuration\cd-texture-dx.exe"
    & $textureExecutable self-test
    Assert-LastExitCode "Native DirectXTex self-test"

    & dotnet build $solution -c $Configuration --nologo --verbosity:minimal
    Assert-LastExitCode ".NET solution build"

    & dotnet build $rendererProject -c $Configuration --nologo --verbosity:minimal
    Assert-LastExitCode ".NET/Vortice preview renderer build"
    $rendererExecutable = Join-Path (Split-Path -Parent $rendererProject) "bin\$Configuration\net8.0-windows\cdmw-mesh-dotnet-editor.exe"
    $previewExecutable = Join-Path $previewBuild "$Configuration\cdmw-preview-core.exe"
    $previousRendererPath = $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH
    $previousPreviewPath = $env:CDMW_ARCHIVE_LITE_PREVIEW_CORE_PATH
    $previousItemIndexPath = $env:CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH
    $previousMeshCorePath = $env:CDMW_ARCHIVE_LITE_MESH_CORE_PATH
    $previousTextureHelperPath = $env:CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH
    try {
        $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH = $rendererExecutable
        $env:CDMW_ARCHIVE_LITE_PREVIEW_CORE_PATH = $previewExecutable
        $env:CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH = $acceleratorExecutable
        $env:CDMW_ARCHIVE_LITE_MESH_CORE_PATH = $meshCoreExecutable
        $env:CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH = $textureExecutable
        & dotnet run --project $tests -c $Configuration --no-build
        Assert-LastExitCode "Archive Lite focused tests"
    }
    finally {
        $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH = $previousRendererPath
        $env:CDMW_ARCHIVE_LITE_PREVIEW_CORE_PATH = $previousPreviewPath
        $env:CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH = $previousItemIndexPath
        $env:CDMW_ARCHIVE_LITE_MESH_CORE_PATH = $previousMeshCorePath
        $env:CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH = $previousTextureHelperPath
    }
}
finally {
    Pop-Location
}

Write-Host "CDMW Archive Lite validation passed ($Configuration)."
