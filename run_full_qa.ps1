param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$cargoBin = Join-Path $env:USERPROFILE ".cargo\bin"
if (Test-Path -LiteralPath $cargoBin) {
    $env:PATH = "$cargoBin;$env:PATH"
}

$pythonExe = Join-Path $scriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    $pythonExe = "python"
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Remove-QAPath {
    param([Parameter(Mandatory = $true)][string]$RelativePath)

    $target = Resolve-Path -LiteralPath $RelativePath -ErrorAction SilentlyContinue
    if (-not $target) {
        return
    }
    $workspace = (Resolve-Path -LiteralPath $scriptDir).Path
    if (-not $target.Path.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove outside workspace: $($target.Path)"
    }
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Remove-Item -LiteralPath $target.Path -Recurse -Force -ErrorAction Stop
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
    $qaDist = Join-Path $scriptDir "build\qa-dist"
    $processes = @(Get-Process -Name "CrimsonDesertModWorkbench" -ErrorAction SilentlyContinue | Where-Object {
        try {
            $path = $_.Path
            return $path -and $path.StartsWith($qaDist, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            return $false
        }
    })
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not stop QA process $($process.Id): $($_.Exception.Message)"
        }
    }
    foreach ($process in $processes) {
        try {
            Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
        } catch {
            # Process already exited.
        }
    }
}

try {
    Invoke-NativeStep "Runtime dependency import smoke" {
        & $pythonExe -c "import cv2, numpy, PIL, lz4.block, cryptography; from PySide6.QtWidgets import QApplication; print('runtime deps ok')"
    }
    Invoke-NativeStep "Python unit tests" {
        & $pythonExe -m unittest discover -s tests
    }
    Invoke-NativeStep "Python compileall" {
        & $pythonExe -m compileall -q cdmw tests
    }
    Invoke-NativeStep "Python dependency check" {
        & $pythonExe -m pip check
    }
    Invoke-NativeStep "cd_hkx cargo fmt" {
        Push-Location native\cd_hkx
        try { cargo fmt --check } finally { Pop-Location }
    }
    Invoke-NativeStep "cd_hkx cargo test" {
        Push-Location native\cd_hkx
        try { cargo test } finally { Pop-Location }
    }
    Invoke-NativeStep "PyInstaller QA build" {
        & $pythonExe -m PyInstaller --noconfirm --clean --log-level WARN --distpath build\qa-dist --workpath build\qa-work CrimsonDesertModWorkbench.spec
    }
    Invoke-NativeStep "Packaged EXE startup smoke" {
        $env:QT_QPA_PLATFORM = "offscreen"
        $env:CDMW_GUI_STARTUP_SMOKE = "1"
        & .\build\qa-dist\CrimsonDesertModWorkbench.exe
    }
} finally {
    Stop-QAExecutableProcesses
    Remove-QAPath "build\qa-dist"
    Remove-QAPath "build\qa-work"
    Remove-QAPath "crash_reports"
}

Write-Host ""
Write-Host "Full QA completed."
