$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This build script must run on Windows."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python 3.12 was not found. Create .venv or put python on PATH."
    }
    $pythonPath = $pythonCommand.Source
}

Push-Location $repoRoot
try {
    $version = (& $pythonPath -c "from app.version import __version__; print(__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
        throw "Could not read the application version from app/version.py."
    }
}
finally {
    Pop-Location
}

$iconPath = Join-Path $repoRoot "assets\tellme_sensei.ico"
if (-not (Test-Path -LiteralPath $iconPath)) {
    throw "Application icon was not found: $iconPath"
}

$buildPath = Join-Path $repoRoot "build"
$distPath = Join-Path $repoRoot "dist"
foreach ($path in @($buildPath, $distPath)) {
    if (Test-Path -LiteralPath $path) {
        $resolved = (Resolve-Path -LiteralPath $path).Path
        if (-not $resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a path outside the repository: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

$specPath = Join-Path $repoRoot "packaging\tellme_sensei.spec"
if (-not (Test-Path -LiteralPath $specPath)) {
    throw "PyInstaller spec was not found: $specPath"
}

Push-Location $repoRoot
try {
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $buildPath $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$distAppPath = Join-Path $distPath "TellMeSensei"
$exePath = Join-Path $distAppPath "TellMeSensei.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Portable executable was not created: $exePath"
}

$cythonUtilityFile = Get-ChildItem -LiteralPath $distAppPath -Recurse -Filter "CppSupport.cpp" -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $cythonUtilityFile) {
    throw "Cython Utility data was not bundled: Cython\Utility\CppSupport.cpp"
}

$requiredPaddleSources = @(
    "paddleocr\tools\__init__.py",
    "paddleocr\ppocr\__init__.py"
)
foreach ($relativePath in $requiredPaddleSources) {
    $sourceFile = Get-ChildItem -LiteralPath $distAppPath -Recurse -Filter (Split-Path -Leaf $relativePath) -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName.EndsWith($relativePath, [System.StringComparison]::OrdinalIgnoreCase) } |
        Select-Object -First 1
    if ($null -eq $sourceFile) {
        throw "PaddleOCR runtime source was not bundled: $relativePath"
    }
    Write-Host "PaddleOCR runtime source found: $($sourceFile.FullName)"
}

$smokeTest = Start-Process -FilePath $exePath -ArgumentList "--smoke-import-ocr" -WorkingDirectory "C:\" -WindowStyle Hidden -Wait -PassThru
if ($smokeTest.ExitCode -ne 0) {
    throw "Packaged PaddleOCR import smoke test failed with exit code $($smokeTest.ExitCode)."
}
Write-Host "Packaged PaddleOCR import smoke test passed."

$exe = Get-Item -LiteralPath $exePath
Write-Host "Portable build succeeded: $($exe.FullName)"
Write-Host "Executable size: $([math]::Round($exe.Length / 1MB, 2)) MB"
Write-Host "Cython Utility data found: $($cythonUtilityFile.FullName)"
Write-Host "Version: $version"
