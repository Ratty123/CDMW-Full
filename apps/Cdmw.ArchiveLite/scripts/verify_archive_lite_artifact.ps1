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
    "README.md",
    "THIRD-PARTY-NOTICES.md"
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

function Assert-X64Pe([string]$Path) {
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -lt 64 -or $bytes[0] -ne 0x4D -or $bytes[1] -ne 0x5A) {
        throw "Not a valid PE file: $Path"
    }
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3C)
    if ($peOffset -lt 0 -or $peOffset + 6 -gt $bytes.Length) {
        throw "Invalid PE header offset: $Path"
    }
    $machine = [BitConverter]::ToUInt16($bytes, $peOffset + 4)
    if ($machine -ne 0x8664) {
        throw "Artifact is not x64 (machine 0x$($machine.ToString('X4'))): $Path"
    }
}

Assert-X64Pe (Join-Path $artifactRoot "CdmwArchiveLite.exe")
Assert-X64Pe (Join-Path $artifactRoot "CdmwArchiveLite.Worker.exe")
Assert-X64Pe (Join-Path $artifactRoot "cdmw-archive-core.dll")

$worker = Join-Path $artifactRoot "CdmwArchiveLite.Worker.exe"
$application = Join-Path $artifactRoot "CdmwArchiveLite.exe"
$testDataRoot = Join-Path ([IO.Path]::GetTempPath()) "cdmw-archive-lite-artifact-$([Guid]::NewGuid().ToString('N'))"
$previousTestMode = $env:CDMW_ARCHIVE_LITE_TEST_MODE
$previousDataRoot = $env:CDMW_ARCHIVE_LITE_DATA_ROOT
try {
    $env:CDMW_ARCHIVE_LITE_TEST_MODE = "1"
    $env:CDMW_ARCHIVE_LITE_DATA_ROOT = $testDataRoot

    $workerProcess = Start-Process -FilePath $worker -ArgumentList "--self-test" -WorkingDirectory $artifactRoot -WindowStyle Hidden -Wait -PassThru
    if ($workerProcess.ExitCode -ne 0) {
        throw "Packaged worker self-test failed with exit code $($workerProcess.ExitCode)."
    }

    $applicationProcess = Start-Process -FilePath $application -ArgumentList "--self-test" -WorkingDirectory $artifactRoot -WindowStyle Hidden -Wait -PassThru
    if ($applicationProcess.ExitCode -ne 0) {
        throw "Packaged application self-test failed with exit code $($applicationProcess.ExitCode)."
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

Write-Host "Artifact guard passed: x64, self-contained, worker-connected, and Python-free."
