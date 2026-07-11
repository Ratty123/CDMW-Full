param(
    [ValidateRange(1, 86400)]
    [int]$StepTimeoutSeconds = 3600,
    [ValidateRange(1, 86400)]
    [int]$BuildTimeoutSeconds = 3600
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path


function ConvertTo-QAProcessArgument {
    param([AllowEmptyString()][string]$Value)

    if ($Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }
    if ($Value.Contains('"')) {
        throw "QA process arguments cannot contain double quotes: $Value"
    }
    return '"' + $Value + '"'
}


function Invoke-QAStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][ValidateRange(1, 86400)][int]$TimeoutSeconds
    )

    Write-Host ""
    Write-Host "==> $Name (timeout: $TimeoutSeconds s)"
    $argumentText = ""
    if ($ArgumentList.Count -gt 0) {
        $argumentText = (($ArgumentList | ForEach-Object {
            ConvertTo-QAProcessArgument ([string]$_)
        }) -join " ")
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $argumentText
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "$Name could not start '$FilePath'."
        }
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
            if (Test-Path -LiteralPath $taskkill) {
                & $taskkill /PID $process.Id /T /F 2>$null | Out-Null
            } else {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
            $process.WaitForExit(5000) | Out-Null
            throw "$Name timed out after $TimeoutSeconds second(s)."
        }
        $process.WaitForExit()
        $exitCode = $process.ExitCode
    } finally {
        $process.Dispose()
    }
    if ($exitCode -ne 0) {
        throw "$Name failed with exit code $exitCode."
    }
}


function Remove-QAOwnedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$OwnedRoot
    )

    $tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\', '/')
    $owned = [System.IO.Path]::GetFullPath($OwnedRoot).TrimEnd('\', '/')
    $target = [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    $tempPrefix = $tempRoot + [System.IO.Path]::DirectorySeparatorChar
    $ownedPrefix = $owned + [System.IO.Path]::DirectorySeparatorChar
    if (-not $owned.StartsWith($tempPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing QA cleanup outside the system temp directory: $owned"
    }
    if ($target -ne $owned -and -not $target.StartsWith($ownedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove outside the QA-owned temp directory: $target"
    }
    if (-not (Test-Path -LiteralPath $target)) {
        return
    }
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($attempt -ge 10) {
                throw
            }
            Start-Sleep -Milliseconds 500
        }
    }
}


function Stop-QAExecutableProcesses {
    param([Parameter(Mandatory = $true)][string]$QaDist)

    $qaDistPath = [System.IO.Path]::GetFullPath($QaDist)
    $processes = @(Get-Process -Name "CrimsonDesertModWorkbench" -ErrorAction SilentlyContinue | Where-Object {
        try {
            $path = $_.Path
            return $path -and $path.StartsWith($qaDistPath, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            return $false
        }
    })
    foreach ($process in $processes) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }
    foreach ($process in $processes) {
        Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
    }
}


function Invoke-FullQA {
    $originalPath = $env:PATH
    $runId = [Guid]::NewGuid().ToString("N")
    $qaRoot = Join-Path ([System.IO.Path]::GetTempPath()) "cdmw-full-qa-$runId"
    $qaDist = Join-Path $qaRoot "dist"
    $qaWork = Join-Path $qaRoot "work"
    $qaPytest = Join-Path $qaRoot "pytest"
    $qaSmokeResult = Join-Path $qaRoot "gui-startup-result.json"
    $qaCrashDir = Join-Path $qaRoot "crash-reports"
    New-Item -ItemType Directory -Path $qaRoot -Force | Out-Null

    $qaEnvironment = @{
        "TEMP" = $qaRoot
        "TMP" = $qaRoot
        "PYTHONPYCACHEPREFIX" = (Join-Path $qaRoot "pycache")
        "CARGO_TARGET_DIR" = (Join-Path $qaRoot "cargo-target")
        "CDMW_PYINSTALLER_MODE" = "onedir"
        "CDMW_PYINSTALLER_PROFILE" = "release"
    }
    $previousQaEnvironment = @{}
    foreach ($name in $qaEnvironment.Keys) {
        $previousQaEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
        [System.Environment]::SetEnvironmentVariable($name, $qaEnvironment[$name], "Process")
    }

    $cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
    if (Test-Path -LiteralPath $cargoBin) {
        $env:PATH = "$cargoBin;$env:PATH"
    }
    $venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"
    $pythonExe = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
    $powerShellName = if ($PSVersionTable.PSEdition -eq "Core") { "pwsh.exe" } else { "powershell.exe" }
    $powerShellExe = Join-Path $PSHOME $powerShellName
    $codexCheck = Join-Path $scriptDir "scripts\codex_check.ps1"
    $packageBuilder = Join-Path $scriptDir "build_pyside6_app.ps1"

    try {
        Invoke-QAStep "Canonical full pytest gate" $powerShellExe @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $codexCheck,
            "-Area", "full", "-PytestBaseTemp", $qaPytest
        ) $scriptDir $StepTimeoutSeconds
        Invoke-QAStep "Python compileall" $pythonExe @("-m", "compileall", "-q", "cdmw", "tests") $scriptDir 600
        Invoke-QAStep "Python dependency check" $pythonExe @("-m", "pip", "check") $scriptDir 300
        Invoke-QAStep "cd_hkx cargo fmt" "cargo" @("fmt", "--check") (Join-Path $scriptDir "native\cd_hkx") 300
        Invoke-QAStep "cd_hkx cargo test" "cargo" @("test") (Join-Path $scriptDir "native\cd_hkx") $StepTimeoutSeconds
        Invoke-QAStep "Production Mesh Editor helper build and hidden GPU smoke" $powerShellExe @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $packageBuilder,
            "-BuildProfile", "release", "-NativeHelpersOnly"
        ) $scriptDir $BuildTimeoutSeconds
        Invoke-QAStep "PyInstaller QA build" $pythonExe @(
            "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
            "--distpath", $qaDist, "--workpath", $qaWork, "CrimsonDesertModWorkbench.spec"
        ) $scriptDir $BuildTimeoutSeconds
        $qaPackageDir = Join-Path $qaDist "CrimsonDesertModWorkbench"
        $packagedDotNetHelper = Join-Path $qaPackageDir "_internal\native\cdmw-mesh-dotnet-editor.exe"
        Invoke-QAStep "Packaged .NET Mesh Editor hidden GPU smoke" $powerShellExe @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $packageBuilder,
            "-DotNetGpuSmokeExecutable", $packagedDotNetHelper
        ) $scriptDir $StepTimeoutSeconds

        $smokeEnvironment = @{
            "QT_QPA_PLATFORM" = "offscreen"
            "CDMW_GUI_STARTUP_SMOKE" = "1"
            "CDMW_GUI_STARTUP_SMOKE_RESULT" = $qaSmokeResult
            "CDMW_SINGLE_INSTANCE_SCOPE" = "full-qa-$runId"
            "CDMW_CRASH_DIR" = $qaCrashDir
            "CDMW_TEMP_CACHE_ROOT" = (Join-Path $qaRoot "cache")
        }
        $previousEnvironment = @{}
        foreach ($name in $smokeEnvironment.Keys) {
            $previousEnvironment[$name] = [System.Environment]::GetEnvironmentVariable($name, "Process")
            [System.Environment]::SetEnvironmentVariable($name, $smokeEnvironment[$name], "Process")
        }
        try {
            $qaExecutable = Join-Path $qaPackageDir "CrimsonDesertModWorkbench.exe"
            Invoke-QAStep "Packaged EXE startup smoke" $qaExecutable @() $qaDist 120
            if (-not (Test-Path -LiteralPath $qaSmokeResult)) {
                throw "Packaged EXE startup smoke did not write its result marker."
            }
            $smokeResult = Get-Content -LiteralPath $qaSmokeResult -Raw | ConvertFrom-Json
            if ($smokeResult.ok -ne $true -or [string]$smokeResult.stage -ne "post_construction") {
                throw "Packaged EXE startup smoke did not prove post-construction success."
            }
        } finally {
            foreach ($name in $smokeEnvironment.Keys) {
                [System.Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
            }
        }
    } finally {
        Stop-QAExecutableProcesses $qaDist
        foreach ($name in $qaEnvironment.Keys) {
            [System.Environment]::SetEnvironmentVariable($name, $previousQaEnvironment[$name], "Process")
        }
        $env:PATH = $originalPath
        Remove-QAOwnedPath $qaRoot $qaRoot
    }

    Write-Host ""
    Write-Host "Full QA completed."
}


if ($MyInvocation.InvocationName -ne ".") {
    Invoke-FullQA
}
