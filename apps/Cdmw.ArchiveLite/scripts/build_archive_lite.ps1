param(
    [ValidateSet("Release")]
    [string]$Configuration = "Release",
    [string]$OutputRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$liteRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $liteRoot "..\.."))
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $liteRoot "artifacts"
}
$resolvedOutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$driveRoot = [IO.Path]::GetPathRoot($resolvedOutputRoot)
if ($resolvedOutputRoot.Equals($driveRoot, [StringComparison]::OrdinalIgnoreCase) -or
    $resolvedOutputRoot.Equals($repositoryRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a broad output root: $resolvedOutputRoot"
}

$version = "0.6.1"
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
$vgmstreamRoot = Join-Path $repositoryRoot ".tools\vgmstream"
$vgmstreamManifestPath = Join-Path $vgmstreamRoot ".cdmw-dependency.json"
$rendererProject = Join-Path $repositoryRoot "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
$appProject = Join-Path $liteRoot "src\Cdmw.ArchiveLite.App\Cdmw.ArchiveLite.App.csproj"
$workerProject = Join-Path $liteRoot "src\Cdmw.ArchiveLite.Worker\Cdmw.ArchiveLite.Worker.csproj"
$standaloneProject = Join-Path $liteRoot "src\Cdmw.ArchiveLite.Standalone\Cdmw.ArchiveLite.Standalone.csproj"
$stage = Join-Path $resolvedOutputRoot "CDMW-Archive-Lite-win-x64"
$workerStage = Join-Path $resolvedOutputRoot ".worker-publish"
$rendererStage = Join-Path $resolvedOutputRoot ".renderer-publish"
$standaloneStage = Join-Path $resolvedOutputRoot ".standalone-publish"
$zipStaging = Join-Path $resolvedOutputRoot ".CDMW-Archive-Lite-$version-win-x64.tmp.zip"
$zipPath = Join-Path $resolvedOutputRoot "CDMW-Archive-Lite-$version-win-x64.zip"
$standaloneStaging = Join-Path $resolvedOutputRoot ".CDMW-Archive-Lite-$version-Standalone-win-x64.tmp.exe"
$standalonePath = Join-Path $resolvedOutputRoot "CDMW-Archive-Lite-$version-Standalone-win-x64.exe"

function Assert-ContainedOutput([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    $prefix = $resolvedOutputRoot.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Output path escapes the selected output root: $resolved"
    }
}

function Assert-LastExitCode([string]$Operation) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

Assert-ContainedOutput $stage
Assert-ContainedOutput $workerStage
Assert-ContainedOutput $rendererStage
Assert-ContainedOutput $standaloneStage
Assert-ContainedOutput $zipStaging
Assert-ContainedOutput $zipPath
Assert-ContainedOutput $standaloneStaging
Assert-ContainedOutput $standalonePath
New-Item -ItemType Directory -Path $resolvedOutputRoot -Force | Out-Null
foreach ($target in @(
    $stage,
    $workerStage,
    $rendererStage,
    $standaloneStage,
    $zipStaging,
    $zipPath,
    $standaloneStaging,
    $standalonePath
)) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $stage -Force | Out-Null
New-Item -ItemType Directory -Path $workerStage -Force | Out-Null
New-Item -ItemType Directory -Path $rendererStage -Force | Out-Null
New-Item -ItemType Directory -Path $standaloneStage -Force | Out-Null

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
    $previewCoreExecutable = Join-Path $previewBuild "$Configuration\cdmw-preview-core.exe"
    & $previewCoreExecutable self-test
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

    & dotnet build (Join-Path $liteRoot "Cdmw.ArchiveLite.slnx") -c $Configuration --nologo --verbosity:minimal
    Assert-LastExitCode ".NET solution build"

    & dotnet publish $rendererProject -c $Configuration -r win-x64 --self-contained true --nologo --output $rendererStage `
        -p:PublishSingleFile=false -p:PublishTrimmed=false -p:PublishReadyToRun=true -p:DebugType=None
    Assert-LastExitCode ".NET/Vortice preview renderer publish"
    $rendererExecutable = Join-Path $rendererStage "cdmw-mesh-dotnet-editor.exe"
    $previousRendererPath = $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH
    $previousItemIndexPath = $env:CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH
    $previousMeshCorePath = $env:CDMW_ARCHIVE_LITE_MESH_CORE_PATH
    $previousTextureHelperPath = $env:CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH
    try {
        $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH = $rendererExecutable
        $env:CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH = $acceleratorExecutable
        $env:CDMW_ARCHIVE_LITE_MESH_CORE_PATH = $meshCoreExecutable
        $env:CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH = $textureExecutable
        & dotnet run --project (Join-Path $liteRoot "tests\Cdmw.ArchiveLite.Tests\Cdmw.ArchiveLite.Tests.csproj") -c $Configuration --no-build
        Assert-LastExitCode "Archive Lite focused tests"
    }
    finally {
        $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH = $previousRendererPath
        $env:CDMW_ARCHIVE_LITE_ITEM_INDEX_PATH = $previousItemIndexPath
        $env:CDMW_ARCHIVE_LITE_MESH_CORE_PATH = $previousMeshCorePath
        $env:CDMW_ARCHIVE_LITE_TEXTURE_HELPER_PATH = $previousTextureHelperPath
    }

    & dotnet publish $appProject -c $Configuration -r win-x64 --self-contained true --nologo --output $stage -p:Version=$version -p:DebugType=None
    Assert-LastExitCode "Archive Lite application publish"
    & dotnet publish $workerProject -c $Configuration -r win-x64 --self-contained true --nologo --output $workerStage -p:Version=$version -p:DebugType=None
    Assert-LastExitCode "Archive Lite worker publish"
}
finally {
    Pop-Location
}

$workerPayload = @(
    "CdmwArchiveLite.Worker.exe",
    "CdmwArchiveLite.Worker.dll",
    "CdmwArchiveLite.Worker.deps.json",
    "CdmwArchiveLite.Worker.runtimeconfig.json",
    "Cdmw.ArchiveLite.Core.dll"
)
foreach ($workerFile in $workerPayload) {
    $workerSource = Join-Path $workerStage $workerFile
    if (-not (Test-Path -LiteralPath $workerSource -PathType Leaf)) {
        throw "Worker publish did not produce $workerFile."
    }
    Copy-Item -LiteralPath $workerSource -Destination $stage -Force
}
Copy-Item -LiteralPath (Join-Path $nativeBuild "$Configuration\cdmw-archive-core.dll") -Destination $stage -Force
$previewPayload = Join-Path $stage "preview"
$rendererPayload = Join-Path $stage "renderer"
$indexerPayload = Join-Path $stage "indexer"
$meshPayload = Join-Path $stage "mesh"
$texturePayload = Join-Path $stage "texture"
$mediaPayload = Join-Path $stage "media"
New-Item -ItemType Directory -Path $previewPayload -Force | Out-Null
New-Item -ItemType Directory -Path $rendererPayload -Force | Out-Null
New-Item -ItemType Directory -Path $indexerPayload -Force | Out-Null
New-Item -ItemType Directory -Path $meshPayload -Force | Out-Null
New-Item -ItemType Directory -Path $texturePayload -Force | Out-Null
New-Item -ItemType Directory -Path $mediaPayload -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $previewBuild "$Configuration\cdmw-preview-core.exe") -Destination $previewPayload -Force
Copy-Item -LiteralPath $acceleratorExecutable -Destination $indexerPayload -Force
Copy-Item -LiteralPath $meshCoreExecutable -Destination $meshPayload -Force
Copy-Item -LiteralPath $textureExecutable -Destination $texturePayload -Force
Copy-Item -Path (Join-Path $rendererStage "*") -Destination $rendererPayload -Recurse -Force
$vgmstreamManifest = Get-Content -LiteralPath $vgmstreamManifestPath -Raw | ConvertFrom-Json
if ($vgmstreamManifest.version -ne "r1980" -or
    $vgmstreamManifest.build_commit -ne "21bfb6f0a513271f2e18a51322128756bb59f365") {
    throw "The bundled vgmstream dependency does not match the pinned r1980 build."
}
foreach ($fileProperty in $vgmstreamManifest.files.PSObject.Properties) {
    $sourcePath = Join-Path $vgmstreamRoot $fileProperty.Name
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Pinned vgmstream file is missing: $($fileProperty.Name)"
    }
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = ([string]$fileProperty.Value).ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Pinned vgmstream file hash mismatch: $($fileProperty.Name)"
    }
    Copy-Item -LiteralPath $sourcePath -Destination $mediaPayload -Force
}
Copy-Item -LiteralPath $vgmstreamManifestPath -Destination $mediaPayload -Force
Copy-Item -LiteralPath (Join-Path $liteRoot "README.md") -Destination $stage -Force
Copy-Item -LiteralPath (Join-Path $liteRoot "THIRD-PARTY-NOTICES.md") -Destination $stage -Force

$contents = Get-ChildItem -LiteralPath $stage -Recurse -File | Sort-Object FullName | ForEach-Object {
    [pscustomobject]@{
        path = $_.FullName.Substring($stage.TrimEnd('\').Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$contents | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $stage "PACKAGE-CONTENTS.json") -Encoding utf8

& (Join-Path $PSScriptRoot "verify_archive_lite_artifact.ps1") -ArtifactDirectory $stage
Assert-LastExitCode "Archive Lite artifact guard"

Compress-Archive -LiteralPath $stage -DestinationPath $zipStaging -CompressionLevel Optimal
Move-Item -LiteralPath $zipStaging -Destination $zipPath

& dotnet publish $standaloneProject -c $Configuration -r win-x64 --self-contained true --nologo --output $standaloneStage `
    -p:Version=$version -p:DebugType=None "-p:ArchiveLitePayloadPath=$zipPath"
Assert-LastExitCode "Archive Lite standalone launcher publish"
$standaloneExecutable = Join-Path $standaloneStage "CdmwArchiveLite.Standalone.exe"
if (-not (Test-Path -LiteralPath $standaloneExecutable -PathType Leaf)) {
    throw "Standalone publish did not produce CdmwArchiveLite.Standalone.exe."
}
$standaloneRuntimeFiles = @(Get-ChildItem -LiteralPath $standaloneStage -File | Where-Object { $_.Extension -ne ".pdb" })
if ($standaloneRuntimeFiles.Count -ne 1 -or
    -not $standaloneRuntimeFiles[0].FullName.Equals($standaloneExecutable, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Standalone publish requires runtime companion files: $($standaloneRuntimeFiles.Name -join ', ')"
}
Copy-Item -LiteralPath $standaloneExecutable -Destination $standaloneStaging
& (Join-Path $PSScriptRoot "verify_archive_lite_standalone.ps1") -ExecutablePath $standaloneStaging
Assert-LastExitCode "Archive Lite standalone artifact guard"
Move-Item -LiteralPath $standaloneStaging -Destination $standalonePath

Remove-Item -LiteralPath $workerStage -Recurse -Force
Remove-Item -LiteralPath $rendererStage -Recurse -Force
Remove-Item -LiteralPath $standaloneStage -Recurse -Force

Write-Host "Portable Archive Lite package: $zipPath"
Write-Host "Standalone Archive Lite executable: $standalonePath"
