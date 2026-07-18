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

$version = "0.2.0"
$nativeRoot = Join-Path $repositoryRoot "native\cdmw_archive_core"
$nativeBuild = Join-Path $nativeRoot "build"
$previewRoot = Join-Path $repositoryRoot "native\cdmw_preview_core"
$previewBuild = Join-Path $previewRoot "build"
$rendererProject = Join-Path $repositoryRoot "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
$appProject = Join-Path $liteRoot "src\Cdmw.ArchiveLite.App\Cdmw.ArchiveLite.App.csproj"
$workerProject = Join-Path $liteRoot "src\Cdmw.ArchiveLite.Worker\Cdmw.ArchiveLite.Worker.csproj"
$stage = Join-Path $resolvedOutputRoot "CDMW-Archive-Lite-win-x64"
$workerStage = Join-Path $resolvedOutputRoot ".worker-publish"
$rendererStage = Join-Path $resolvedOutputRoot ".renderer-publish"
$zipStaging = Join-Path $resolvedOutputRoot ".CDMW-Archive-Lite-$version-win-x64.tmp.zip"
$zipPath = Join-Path $resolvedOutputRoot "CDMW-Archive-Lite-$version-win-x64.zip"

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
Assert-ContainedOutput $zipStaging
Assert-ContainedOutput $zipPath
New-Item -ItemType Directory -Path $resolvedOutputRoot -Force | Out-Null
foreach ($target in @($stage, $workerStage, $rendererStage, $zipStaging, $zipPath)) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $stage -Force | Out-Null
New-Item -ItemType Directory -Path $workerStage -Force | Out-Null
New-Item -ItemType Directory -Path $rendererStage -Force | Out-Null

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

    & dotnet build (Join-Path $liteRoot "Cdmw.ArchiveLite.slnx") -c $Configuration --nologo --verbosity:minimal
    Assert-LastExitCode ".NET solution build"

    & dotnet publish $rendererProject -c $Configuration -r win-x64 --self-contained true --nologo --output $rendererStage `
        -p:PublishSingleFile=true -p:PublishTrimmed=false -p:PublishReadyToRun=true `
        -p:IncludeNativeLibrariesForSelfExtract=true -p:DebugType=None
    Assert-LastExitCode ".NET/Vortice preview renderer publish"
    $rendererExecutable = Join-Path $rendererStage "cdmw-mesh-dotnet-editor.exe"
    $previousRendererPath = $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH
    try {
        $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH = $rendererExecutable
        & dotnet run --project (Join-Path $liteRoot "tests\Cdmw.ArchiveLite.Tests\Cdmw.ArchiveLite.Tests.csproj") -c $Configuration --no-build
        Assert-LastExitCode "Archive Lite focused tests"
    }
    finally {
        $env:CDMW_ARCHIVE_LITE_DOTNET_PREVIEW_PATH = $previousRendererPath
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
New-Item -ItemType Directory -Path $previewPayload -Force | Out-Null
New-Item -ItemType Directory -Path $rendererPayload -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $previewBuild "$Configuration\cdmw-preview-core.exe") -Destination $previewPayload -Force
Copy-Item -Path (Join-Path $rendererStage "*") -Destination $rendererPayload -Recurse -Force
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
Remove-Item -LiteralPath $workerStage -Recurse -Force
Remove-Item -LiteralPath $rendererStage -Recurse -Force

Write-Host "Portable Archive Lite package: $zipPath"
