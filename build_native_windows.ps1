param(
    [ValidateSet("Release", "Debug")]
    [string]$Configuration = "Release",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Resolve-VisualStudioRoot {
    $roots = New-Object System.Collections.Generic.List[string]
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere) {
        $vswhereRoot = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
        if ($vswhereRoot) {
            $roots.Add($vswhereRoot)
        }
    }

    $vs2022Root = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\2022"
    foreach ($edition in @("BuildTools", "Community", "Professional", "Enterprise")) {
        $roots.Add((Join-Path $vs2022Root $edition))
    }

    foreach ($root in $roots) {
        $vcvarsPath = Join-Path $root "VC\Auxiliary\Build\vcvars64.bat"
        if (Test-Path -LiteralPath $vcvarsPath) {
            return $root
        }
    }

    throw "Visual Studio 2022 with MSVC x64 tools was not found. Install Visual Studio Build Tools 2022 with MSVC and CMake components."
}

$vsRoot = Resolve-VisualStudioRoot
$vcvars = Join-Path $vsRoot "VC\Auxiliary\Build\vcvars64.bat"
if (-not (Test-Path -LiteralPath $vcvars)) {
    throw "vcvars64.bat was not found under '$vsRoot'."
}

$cmake = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
if (-not (Test-Path -LiteralPath $cmake)) {
    $cmake = "cmake"
}

$nativeDependencyCacheDir = Join-Path $scriptDir "build\native-deps"
$directXTexSourceCacheDir = Join-Path $nativeDependencyCacheDir "directxtex-src"

function Clear-StaleCMakeBuildDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BuildDir
    )

    $cachePath = Join-Path $BuildDir "CMakeCache.txt"
    if (-not (Test-Path -LiteralPath $cachePath)) {
        return
    }

    $cache = Get-Content -LiteralPath $cachePath -Raw
    $generatorMatch = [regex]::Match($cache, '(?m)^CMAKE_GENERATOR:INTERNAL=(.*)$')
    $platformMatch = [regex]::Match($cache, '(?m)^CMAKE_GENERATOR_PLATFORM:INTERNAL=(.*)$')
    $generator = if ($generatorMatch.Success) { $generatorMatch.Groups[1].Value.Trim() } else { "" }
    $platform = if ($platformMatch.Success) { $platformMatch.Groups[1].Value.Trim() } else { "" }
    if ($generator -eq "Visual Studio 17 2022" -and $platform -eq "x64") {
        return
    }

    $buildDirName = Split-Path -Leaf $BuildDir
    if ($buildDirName -ne "build") {
        throw "Refusing to remove unexpected CMake build directory: $BuildDir"
    }

    Write-Host "Removing stale CMake build directory for generator/platform change: $BuildDir (generator='$generator', platform='$platform')"
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}

function Test-NativeProjectUsesDirectXTex {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    $cmakeListsPath = Join-Path $ProjectDir "CMakeLists.txt"
    if (-not (Test-Path -LiteralPath $cmakeListsPath)) {
        return $false
    }
    return (Get-Content -LiteralPath $cmakeListsPath -Raw) -like "*DirectXTex.git*"
}

function Save-DirectXTexDependencyCache {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir
    )

    if (Test-Path -LiteralPath $directXTexSourceCacheDir) {
        return
    }
    $sourceDir = Join-Path $ProjectDir "build\_deps\directxtex-src"
    if (-not (Test-Path -LiteralPath $sourceDir)) {
        return
    }
    New-Item -ItemType Directory -Path $nativeDependencyCacheDir -Force | Out-Null
    Copy-Item -LiteralPath $sourceDir -Destination $directXTexSourceCacheDir -Recurse -Force
    Write-Host "Cached DirectXTex source for offline native rebuilds: $directXTexSourceCacheDir"
}

function Invoke-NativeBuild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectDir,
        [Parameter(Mandatory = $true)]
        [string]$ExeRelativePath
    )

    $buildDir = Join-Path $ProjectDir "build"
    $usesDirectXTex = Test-NativeProjectUsesDirectXTex -ProjectDir $ProjectDir
    if ($Clean -and $usesDirectXTex) {
        Save-DirectXTexDependencyCache -ProjectDir $ProjectDir
    }
    if ($Clean -and (Test-Path -LiteralPath $buildDir)) {
        Remove-Item -LiteralPath $buildDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $buildDir) {
        Clear-StaleCMakeBuildDirectory -BuildDir $buildDir
    }
    New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

    $configure = "`"$vcvars`" && `"$cmake`" -S `"$ProjectDir`" -B `"$buildDir`" -G `"Visual Studio 17 2022`" -A x64"
    if ($usesDirectXTex -and (Test-Path -LiteralPath $directXTexSourceCacheDir)) {
        $configure += " -DFETCHCONTENT_SOURCE_DIR_DIRECTXTEX=`"$directXTexSourceCacheDir`" -DFETCHCONTENT_UPDATES_DISCONNECTED=ON"
    }
    $build = "`"$vcvars`" && `"$cmake`" --build `"$buildDir`" --config $Configuration"
    cmd.exe /d /s /c $configure
    if ($LASTEXITCODE -ne 0) {
        throw "CMake configure failed for $ProjectDir with exit code $LASTEXITCODE."
    }
    cmd.exe /d /s /c $build
    if ($LASTEXITCODE -ne 0) {
        throw "Native build failed for $ProjectDir with exit code $LASTEXITCODE."
    }

    $exePath = Join-Path $ProjectDir $ExeRelativePath
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Native build completed but expected binary is missing: $exePath"
    }
    if ($usesDirectXTex) {
        Save-DirectXTexDependencyCache -ProjectDir $ProjectDir
    }
    Write-Host "Built native binary: $exePath"
}

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cd_texture_dx") `
    -ExeRelativePath ("build\$Configuration\cd-texture-dx.exe")

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cdmw_preview_core") `
    -ExeRelativePath ("build\$Configuration\cdmw-preview-core.exe")

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cdmw_d3d11_preview") `
    -ExeRelativePath ("build\$Configuration\cdmw-d3d11-preview.exe")

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cdmw_archive_accelerator") `
    -ExeRelativePath ("build\$Configuration\cdmw-archive-accelerator.exe")

Invoke-NativeBuild `
    -ProjectDir (Join-Path $scriptDir "native\cdmw_mesh_core") `
    -ExeRelativePath ("build\$Configuration\cdmw-mesh-core.exe")

$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnet) {
    throw "dotnet was not found; required Mesh Editor renderer cannot be built."
}
$dotnetProject = Join-Path $scriptDir "tools\dotnet_mesh_editor_experiment\Cdmw.MeshEditorExperiment.csproj"
& $dotnet.Source build $dotnetProject -c $Configuration --nologo
if ($LASTEXITCODE -ne 0) {
    throw ".NET Mesh Editor build failed with exit code $LASTEXITCODE."
}

$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if ($cargo) {
    Push-Location (Join-Path $scriptDir "native\cd_hkx")
    try {
        $cargoCommand = "`"$($cargo.Source)`" build --release 2>&1"
        cmd.exe /d /s /c $cargoCommand
        $cargoExitCode = $LASTEXITCODE
        if ($cargoExitCode -ne 0) {
            throw "Rust HKX native build failed with exit code $cargoExitCode."
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "cargo was not found; skipping optional native cd-hkx build."
}
