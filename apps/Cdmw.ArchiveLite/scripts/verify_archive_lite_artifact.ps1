param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$artifactRoot = [IO.Path]::GetFullPath($ArtifactDirectory)
if (-not (Test-Path -LiteralPath $artifactRoot -PathType Container)) {
    throw "Artifact directory does not exist: $artifactRoot"
}

$requiredFiles = @(
    "CdmwArchiveLite.exe",
    "CdmwArchiveLite.Worker.exe",
    "cdmw-archive-core.dll",
    "ICSharpCode.AvalonEdit.dll",
    "preview\cdmw-preview-core.exe",
    "indexer\cdmw-archive-accelerator.exe",
    "mesh\cdmw-mesh-core.exe",
    "texture\cd-texture-dx.exe",
    "media\vgmstream-cli.exe",
    "media\COPYING",
    "media\.cdmw-dependency.json",
    "renderer\cdmw-mesh-dotnet-editor.exe",
    "README.md",
    "THIRD-PARTY-NOTICES.md",
    "PACKAGE-CONTENTS.json"
)
foreach ($relativePath in $requiredFiles) {
    $requiredPath = Join-Path $artifactRoot $relativePath
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required artifact file is missing: $relativePath"
    }
}

$bannedExtensions = @(".py", ".pyc", ".pyo", ".pyd", ".pyw", ".whl", ".egg", ".ipynb")
$bannedFiles = Get-ChildItem -LiteralPath $artifactRoot -Recurse -File | Where-Object {
    $bannedExtensions -contains $_.Extension.ToLowerInvariant() -or
    $_.Name -match '^(python|pythonw|py)(?:3(?:\.\d+)?)?\.exe$'
}
if ($bannedFiles) {
    throw "Python payloads are present: $($bannedFiles.FullName -join ', ')"
}

$bannedDirectories = Get-ChildItem -LiteralPath $artifactRoot -Recurse -Directory | Where-Object {
    $_.Name -match '^(python(?:3(?:\.\d+)?)?|site-packages|__pycache__)$'
}
if ($bannedDirectories) {
    throw "Python runtime directories are present: $($bannedDirectories.FullName -join ', ')"
}

$pythonImportPattern = [Text.RegularExpressions.Regex]::new(
    'python(?:3\d{1,3}|\d{2,3})?\.dll',
    [Text.RegularExpressions.RegexOptions]::IgnoreCase -bor [Text.RegularExpressions.RegexOptions]::CultureInvariant)
foreach ($binary in Get-ChildItem -LiteralPath $artifactRoot -Recurse -File | Where-Object { $_.Extension -in @('.exe', '.dll') }) {
    $binaryText = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($binary.FullName))
    if ($pythonImportPattern.IsMatch($binaryText)) {
        throw "A packaged PE references a Python runtime: $($binary.FullName)"
    }
}

function Assert-PeMachine(
    [string]$Path,
    [uint16]$ExpectedMachine,
    [string]$Architecture
) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4D -or $bytes[1] -ne 0x5A) {
        throw "Not a valid PE file: $Path"
    }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) {
        throw "Invalid PE header offset: $Path"
    }
    $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
    if ($machine -ne $ExpectedMachine) {
        throw "Artifact is not $Architecture (machine 0x$($machine.ToString('X4'))): $Path"
    }
}

function Assert-X64Pe([string]$Path) {
    Assert-PeMachine -Path $Path -ExpectedMachine 0x8664 -Architecture "x64"
}

function Assert-X86Pe([string]$Path) {
    Assert-PeMachine -Path $Path -ExpectedMachine 0x014C -Architecture "x86"
}

Assert-X64Pe (Join-Path $artifactRoot "CdmwArchiveLite.exe")
Assert-X64Pe (Join-Path $artifactRoot "CdmwArchiveLite.Worker.exe")
Assert-X64Pe (Join-Path $artifactRoot "cdmw-archive-core.dll")
Assert-X64Pe (Join-Path $artifactRoot "preview\cdmw-preview-core.exe")
Assert-X64Pe (Join-Path $artifactRoot "indexer\cdmw-archive-accelerator.exe")
Assert-X64Pe (Join-Path $artifactRoot "mesh\cdmw-mesh-core.exe")
Assert-X64Pe (Join-Path $artifactRoot "texture\cd-texture-dx.exe")
Assert-X64Pe (Join-Path $artifactRoot "renderer\cdmw-mesh-dotnet-editor.exe")
foreach ($mediaBinary in Get-ChildItem -LiteralPath (Join-Path $artifactRoot "media") -File | Where-Object { $_.Extension -in @(".exe", ".dll") }) {
    Assert-X86Pe $mediaBinary.FullName
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-HiddenProcess(
    [string]$Path,
    [string[]]$Arguments,
    [int]$TimeoutSeconds = 30
) {
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -WorkingDirectory (Split-Path -Parent $Path) -WindowStyle Hidden -PassThru
    try {
        Wait-Process -Id $process.Id -Timeout $TimeoutSeconds -ErrorAction Stop
        $process.Refresh()
        return $process.ExitCode
    }
    catch {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        throw "Process timed out or could not be observed: $Path. $($_.Exception.Message)"
    }
    finally {
        $process.Dispose()
    }
}

$worker = Join-Path $artifactRoot "CdmwArchiveLite.Worker.exe"
$application = Join-Path $artifactRoot "CdmwArchiveLite.exe"
$previewCore = Join-Path $artifactRoot "preview\cdmw-preview-core.exe"
$itemIndexer = Join-Path $artifactRoot "indexer\cdmw-archive-accelerator.exe"
$meshCore = Join-Path $artifactRoot "mesh\cdmw-mesh-core.exe"
$textureDecoder = Join-Path $artifactRoot "texture\cd-texture-dx.exe"
$mediaDecoder = Join-Path $artifactRoot "media\vgmstream-cli.exe"
$renderer = Join-Path $artifactRoot "renderer\cdmw-mesh-dotnet-editor.exe"
$testDataRoot = Join-Path ([IO.Path]::GetTempPath()) "cdmw-archive-lite-artifact-$([Guid]::NewGuid().ToString('N'))"
$previousTestMode = $env:CDMW_ARCHIVE_LITE_TEST_MODE
$previousDataRoot = $env:CDMW_ARCHIVE_LITE_DATA_ROOT
try {
    $env:CDMW_ARCHIVE_LITE_TEST_MODE = "1"
    $env:CDMW_ARCHIVE_LITE_DATA_ROOT = $testDataRoot
    New-Item -ItemType Directory -Path $testDataRoot -Force | Out-Null

    $previewExitCode = Invoke-HiddenProcess -Path $previewCore -Arguments @("self-test")
    if ($previewExitCode -ne 0) {
        throw "Packaged native preview-core self-test failed with exit code $previewExitCode."
    }

    $indexerExitCode = Invoke-HiddenProcess -Path $itemIndexer -Arguments @("--version")
    if ($indexerExitCode -ne 0) {
        throw "Packaged native archive-accelerator version check failed with exit code $indexerExitCode."
    }

    $textureExitCode = Invoke-HiddenProcess -Path $textureDecoder -Arguments @("self-test")
    if ($textureExitCode -ne 0) {
        throw "Packaged DirectXTex decoder self-test failed with exit code $textureExitCode."
    }

    $mediaManifestPath = Join-Path $artifactRoot "media\.cdmw-dependency.json"
    $mediaManifest = Get-Content -LiteralPath $mediaManifestPath -Raw | ConvertFrom-Json
    if ($mediaManifest.version -ne "r1980" -or
        $mediaManifest.build_commit -ne "21bfb6f0a513271f2e18a51322128756bb59f365") {
        throw "Packaged vgmstream runtime does not match the pinned r1980 build."
    }
    foreach ($fileProperty in $mediaManifest.files.PSObject.Properties) {
        $mediaPath = Join-Path (Join-Path $artifactRoot "media") $fileProperty.Name
        if (-not (Test-Path -LiteralPath $mediaPath -PathType Leaf)) {
            throw "Packaged vgmstream file is missing: $($fileProperty.Name)"
        }
        $mediaHash = (Get-FileHash -LiteralPath $mediaPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($mediaHash -ne ([string]$fileProperty.Value).ToLowerInvariant()) {
            throw "Packaged vgmstream file hash mismatch: $($fileProperty.Name)"
        }
    }
    $mediaProbeExitCode = Invoke-HiddenProcess -Path $mediaDecoder -Arguments @("-V")
    if ($mediaProbeExitCode -ne 1) {
        throw "Packaged vgmstream runtime probe returned unexpected exit code $mediaProbeExitCode."
    }

    $meshJob = Join-Path $testDataRoot "mesh-export-job.json"
    $meshReport = Join-Path $testDataRoot "mesh-export-report.json"
    $meshOutput = Join-Path $testDataRoot "mesh-export.fbx"
    $meshJobPayload = [ordered]@{
        version = 1
        backend = "cdmw_mesh_core_0.1"
        operation = "fbx_export"
        output_path = $meshOutput
        base_name = "artifact_guard"
        scale = 1.0
        submeshes = @([ordered]@{
            index = 0
            name = "triangle"
            material = "default"
            vertices = @(@(-0.5, 0.0, 0.0), @(0.5, 0.0, 0.0), @(0.0, 1.0, 0.0))
            faces = @(@(0, 1, 2))
            normals = @(@(0.0, 0.0, 1.0), @(0.0, 0.0, 1.0), @(0.0, 0.0, 1.0))
            uvs = @(@(0.0, 0.0), @(1.0, 0.0), @(0.5, 1.0))
        })
        bones = @()
    } | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($meshJob, $meshJobPayload, [Text.UTF8Encoding]::new($false))
    $meshExitCode = Invoke-HiddenProcess -Path $meshCore -Arguments @(
        "fbx-export-json",
        (Quote-ProcessArgument $meshJob),
        (Quote-ProcessArgument $meshReport)
    )
    if ($meshExitCode -ne 0 -or -not (Test-Path -LiteralPath $meshOutput -PathType Leaf)) {
        throw "Packaged native mesh-core FBX export smoke failed with exit code $meshExitCode."
    }
    $meshReportPayload = Get-Content -LiteralPath $meshReport -Raw | ConvertFrom-Json
    $meshHeader = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($meshOutput), 0, 20)
    if ($meshReportPayload.status -ne "ok" -or
        $meshReportPayload.operation -ne "fbx_export" -or
        $meshHeader -ne "Kaydara FBX Binary  ") {
        throw "Packaged native mesh-core did not produce a valid FBX 7400 export."
    }

    $modelPackage = Join-Path $testDataRoot "native-package"
    $geometryRoot = Join-Path $modelPackage "geometry"
    New-Item -ItemType Directory -Path $geometryRoot -Force | Out-Null
    $geometryPath = Join-Path $geometryRoot "batch_000.bin"
    $geometryBytes = [byte[]]::new(3 * 23 * 4)
    $positions = @(
        [single[]]@(-0.5, 0.0, 0.0),
        [single[]]@(0.5, 0.0, 0.0),
        [single[]]@(0.0, 1.0, 0.0)
    )
    for ($vertexIndex = 0; $vertexIndex -lt $positions.Count; $vertexIndex++) {
        $values = [single[]]::new(23)
        $values[0] = $positions[$vertexIndex][0]
        $values[1] = $positions[$vertexIndex][1]
        $values[2] = $positions[$vertexIndex][2]
        $values[5] = 1.0
        $values[9] = $positions[$vertexIndex][0] + 0.5
        $values[10] = $positions[$vertexIndex][1]
        for ($floatIndex = 0; $floatIndex -lt $values.Count; $floatIndex++) {
            $bytes = [BitConverter]::GetBytes($values[$floatIndex])
            [Buffer]::BlockCopy($bytes, 0, $geometryBytes, (($vertexIndex * 23) + $floatIndex) * 4, 4)
        }
    }
    [IO.File]::WriteAllBytes($geometryPath, $geometryBytes)
    $geometryHash = (Get-FileHash -LiteralPath $geometryPath -Algorithm SHA256).Hash
    [ordered]@{
        schema_version = 8
        backend = "d3d11"
        batches = @([ordered]@{
            index = 0
            material_name = "artifact_guard"
            vertex_file = "geometry/batch_000.bin"
            vertex_count = 3
            base_color = @(0.35, 0.45, 0.6)
            roughness = 0.5
            metalness = 0.7
            specular = 0.4
            material_category = "metal"
            dds_textures = [ordered]@{}
        })
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $modelPackage "manifest.json") -Encoding utf8
    [ordered]@{
        editable_submesh_count = 1
        reference_submesh_count = 0
        interaction_mode = "placement"
        comparison_mode = "replacement_only"
        grid = [ordered]@{ visible = $false; origin = @(0.0, -1.0, 0.0); spacing = 0.25 }
        gizmo = [ordered]@{ visible = $false; tool = "move" }
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $modelPackage "dotnet_scene.json") -Encoding utf8
    [ordered]@{ read_only = $true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $modelPackage "mesh.cdmeta.json") -Encoding utf8
    [ordered]@{ material_slots = @(); submeshes = @() } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $modelPackage "net_materials.json") -Encoding utf8

    $rendererRuntime = Join-Path $testDataRoot "renderer-runtime"
    $rendererOutput = Join-Path $rendererRuntime "output"
    New-Item -ItemType Directory -Path $rendererRuntime -Force | Out-Null
    $rendererStatus = Join-Path $rendererRuntime "status.json"
    $rendererArguments = @(
        "--input-package", (Quote-ProcessArgument $modelPackage),
        "--mesh", (Quote-ProcessArgument (Join-Path $modelPackage "manifest.json")),
        "--metadata", (Quote-ProcessArgument (Join-Path $modelPackage "mesh.cdmeta.json")),
        "--status", (Quote-ProcessArgument $rendererStatus),
        "--output", (Quote-ProcessArgument $rendererOutput),
        "--edit-operations", (Quote-ProcessArgument (Join-Path $rendererRuntime "edit_operations.json")),
        "--evaluation", (Quote-ProcessArgument (Join-Path $rendererRuntime "evaluation.md")),
        "--simple-preview",
        "--headless-smoke"
    )
    $rendererExitCode = Invoke-HiddenProcess -Path $renderer -Arguments $rendererArguments
    if ($rendererExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $rendererOutput "mesh.obj") -PathType Leaf)) {
        throw "Packaged .NET renderer did not load the synthetic native preview package (exit $rendererExitCode)."
    }
    $rendererStatusPayload = Get-Content -LiteralPath $rendererStatus -Raw | ConvertFrom-Json
    if ($rendererStatusPayload.event -ne "saved") {
        throw "Packaged .NET renderer did not report a successful native-package smoke result."
    }
    if ((Get-FileHash -LiteralPath $geometryPath -Algorithm SHA256).Hash -ne $geometryHash) {
        throw "Packaged .NET renderer changed the read-only native preview geometry."
    }

    $gpuReportPath = Join-Path $testDataRoot "gpu-smoke.json"
    $gpuArguments = @(
        "--headless-gpu-sparse-soak",
        "--gpu-soak-report", (Quote-ProcessArgument $gpuReportPath),
        "--gpu-soak-smoke",
        "--gpu-soak-vertices", "30000",
        "--gpu-soak-updates", "100",
        "--gpu-soak-warmup", "16",
        "--gpu-soak-no-cadence"
    )
    $gpuExitCode = Invoke-HiddenProcess -Path $renderer -Arguments $gpuArguments -TimeoutSeconds 120
    if ($gpuExitCode -ne 0 -or -not (Test-Path -LiteralPath $gpuReportPath -PathType Leaf)) {
        throw "Packaged .NET/Vortice renderer GPU smoke failed with exit code $gpuExitCode."
    }
    $gpuReport = Get-Content -LiteralPath $gpuReportPath -Raw | ConvertFrom-Json
    if ($gpuReport.ok -ne $true -or $gpuReport.backend_proof.backend -ne "d3d11_vortice_shader") {
        throw "Packaged renderer did not prove the production d3d11_vortice_shader backend."
    }

    $workerExitCode = Invoke-HiddenProcess -Path $worker -Arguments @("--self-test")
    if ($workerExitCode -ne 0) {
        throw "Packaged worker self-test failed with exit code $workerExitCode."
    }

    $applicationExitCode = Invoke-HiddenProcess -Path $application -Arguments @("--self-test")
    if ($applicationExitCode -ne 0) {
        throw "Packaged application self-test failed with exit code $applicationExitCode."
    }

    $orphanWorker = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).Equals($worker, [StringComparison]::OrdinalIgnoreCase)
    }
    if ($orphanWorker) {
        throw "Packaged self-test left an Archive Lite worker process running."
    }
}
finally {
    $env:CDMW_ARCHIVE_LITE_TEST_MODE = $previousTestMode
    $env:CDMW_ARCHIVE_LITE_DATA_ROOT = $previousDataRoot
    if (Test-Path -LiteralPath $testDataRoot) {
        Remove-Item -LiteralPath $testDataRoot -Recurse -Force
    }
}

Write-Host "Artifact guard passed: x64 app/native helpers, pinned isolated x86 media runtime, native DDS/model preview and mesh export, hidden Vortice GPU, worker-connected, and Python-free."
