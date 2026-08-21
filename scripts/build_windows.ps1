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

$exePath = Join-Path $distPath "TellMeSensei\TellMeSensei.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Portable executable was not created: $exePath"
}

$exe = Get-Item -LiteralPath $exePath
Write-Host "Portable build succeeded: $($exe.FullName)"
Write-Host "Executable size: $([math]::Round($exe.Length / 1MB, 2)) MB"
