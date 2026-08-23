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

$buildPath = Join-Path $repoRoot "build\tellme_sensei"
$distPath = Join-Path $repoRoot "dist"
$distAppPath = Join-Path $distPath "TellMeSensei"
foreach ($path in @($buildPath, $distAppPath)) {
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

$exePath = Join-Path $distAppPath "TellMeSensei.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Portable executable was not created: $exePath"
}

$forbiddenPaths = Get-ChildItem -LiteralPath $distAppPath -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -match "[\\/]paddle(ocr)?([\\/]|$)" -or
        $_.FullName -match "[\\/]ppocr([\\/]|$)" -or
        $_.FullName -match "[\\/]ppstructure([\\/]|$)" -or
        $_.FullName -match "[\\/]Cython[\\/]Utility[\\/]CppSupport\.cpp$"
    } |
    Select-Object -First 1
if ($null -ne $forbiddenPaths) {
    throw "Forbidden Paddle/Cython runtime was bundled in Core: $($forbiddenPaths.FullName)"
}
Write-Host "Core no-Paddle filesystem verification passed."

$smokeTest = Start-Process -FilePath $exePath -ArgumentList "--smoke-core" -WorkingDirectory "C:\" -WindowStyle Hidden -Wait -PassThru
if ($smokeTest.ExitCode -ne 0) {
    throw "Packaged Core smoke test failed with exit code $($smokeTest.ExitCode)."
}
Write-Host "Packaged Core smoke test passed."

$exe = Get-Item -LiteralPath $exePath
Write-Host "Portable build succeeded: $($exe.FullName)"
Write-Host "Executable size: $([math]::Round($exe.Length / 1MB, 2)) MB"
Write-Host "Version: $version"
