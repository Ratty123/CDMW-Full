Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$liteRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $liteRoot "..\.."))
$nativeRoot = Join-Path $repositoryRoot "native\cdmw_archive_core"
$previewRoot = Join-Path $repositoryRoot "native\cdmw_preview_core"
$rendererRoot = Join-Path $repositoryRoot "tools\dotnet_mesh_editor_experiment"
$roots = @($liteRoot, $nativeRoot, $previewRoot, $rendererRoot)
$bannedExtensions = @(".py", ".pyc", ".pyo", ".pyd", ".pyw", ".whl", ".egg", ".ipynb")

$bannedFiles = foreach ($root in $roots) {
    Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
        $bannedExtensions -contains $_.Extension.ToLowerInvariant()
    }
}
if ($bannedFiles) {
    throw "Archive Lite source contains a Python payload: $($bannedFiles.FullName -join ', ')"
}

$sourceExtensions = @(".cs", ".csproj", ".props", ".targets", ".ps1", ".cpp", ".hpp", ".h", ".txt")
$shellInvocationPattern = [Text.RegularExpressions.Regex]::new(
    '(?im)(?:^|[;&|]\s*|FileName\s*=\s*["'']|Command\s*=\s*["''])(?:[^\r\n"'']*[\\/])?(?:python(?:w|3(?:\.\d+)?)?|pyinstaller|pytest)(?:\.exe)?(?:\s|["'']|$)',
    [Text.RegularExpressions.RegexOptions]::CultureInvariant)
$codeInvocationPattern = [Text.RegularExpressions.Regex]::new(
    '(?im)(?:FileName\s*=\s*["'']|Command\s*=\s*["'']|Process\.Start\s*\(\s*["'']|\bsystem\s*\(\s*["'']|\b_popen\s*\(\s*["'']|\bCOMMAND\s+)(?:[^\r\n"'']*[\\/])?(?:python(?:w|3(?:\.\d+)?)?|pyinstaller|pytest)(?:\.exe)?(?:\s|["'']|$)',
    [Text.RegularExpressions.RegexOptions]::CultureInvariant)
$guardPath = [IO.Path]::GetFullPath($MyInvocation.MyCommand.Path)
$violations = foreach ($root in $roots) {
    Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
        $sourceExtensions -contains $_.Extension.ToLowerInvariant() -or $_.Name -eq "CMakeLists.txt"
    } | Where-Object {
        -not $_.FullName.Equals($guardPath, [StringComparison]::OrdinalIgnoreCase) -and
        $(if ($_.Extension.Equals(".ps1", [StringComparison]::OrdinalIgnoreCase)) {
            $shellInvocationPattern.IsMatch([IO.File]::ReadAllText($_.FullName))
        } else {
            $codeInvocationPattern.IsMatch([IO.File]::ReadAllText($_.FullName))
        })
    }
}
if ($violations) {
    throw "Archive Lite build/runtime source invokes a Python tool: $($violations.FullName -join ', ')"
}

Write-Host "Source guard passed: Archive Lite production, build, and tests contain no Python payload or invocation."
