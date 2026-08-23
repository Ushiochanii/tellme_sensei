$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This development component installer must run on Windows."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$sourcePath = Join-Path $repoRoot "dist\LocalOCR"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "Local OCR build was not found: $sourcePath"
}
$sourceExe = Join-Path $sourcePath "TellMeSenseiOCR.exe"
if (-not (Test-Path -LiteralPath $sourceExe -PathType Leaf)) {
    throw "Local OCR executable was not found: $sourceExe"
}

if (Test-Path -LiteralPath $pythonPath) {
    $runtimePath = (& $pythonPath -c "from app.runtime_paths import user_runtime_directory; print(user_runtime_directory())").Trim()
} else {
    $runtimePath = (& python -c "from app.runtime_paths import user_runtime_directory; print(user_runtime_directory())").Trim()
}
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($runtimePath)) {
    throw "Could not resolve the user runtime directory."
}

$versionCommand = if (Test-Path -LiteralPath $pythonPath) { $pythonPath } else { "python" }
$componentVersion = (& $versionCommand -c "from app.local_ocr.version import LOCAL_OCR_VERSION; print(LOCAL_OCR_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($componentVersion)) {
    throw "Could not read the local OCR component version."
}

$targetPath = Join-Path $runtimePath "components\local-ocr\$componentVersion"
$resolvedTarget = [System.IO.Path]::GetFullPath($targetPath)
$resolvedRoot = [System.IO.Path]::GetFullPath($repoRoot)
if ($resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to install the component inside the repository: $resolvedTarget"
}

New-Item -ItemType Directory -Force -Path $resolvedTarget | Out-Null
Get-ChildItem -LiteralPath $sourcePath -Force | Copy-Item -Destination $resolvedTarget -Recurse -Force

$targetExe = Join-Path $resolvedTarget "TellMeSenseiOCR.exe"
if (-not (Test-Path -LiteralPath $targetExe -PathType Leaf)) {
    throw "Local OCR component copy did not produce: $targetExe"
}
Write-Host "Local OCR development component installed at: $resolvedTarget"
