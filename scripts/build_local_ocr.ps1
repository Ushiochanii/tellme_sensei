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

$distPath = Join-Path $repoRoot "dist"
$workerDistPath = Join-Path $distPath "LocalOCR"
$workPath = Join-Path $repoRoot "build\local_ocr_worker"
$specPath = Join-Path $repoRoot "packaging\local_ocr_worker.spec"
if (-not (Test-Path -LiteralPath $specPath)) {
    throw "Local OCR worker spec was not found: $specPath"
}

foreach ($path in @($workerDistPath, $workPath)) {
    if (Test-Path -LiteralPath $path) {
        $resolved = (Resolve-Path -LiteralPath $path).Path
        if (-not $resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a path outside the repository: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

Push-Location $repoRoot
try {
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $workPath $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller local OCR worker build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$exePath = Join-Path $workerDistPath "TellMeSenseiOCR.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Local OCR worker executable was not created: $exePath"
}

$cythonUtilityFile = Get-ChildItem -LiteralPath $workerDistPath -Recurse -Filter "CppSupport.cpp" -File -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -eq $cythonUtilityFile) {
    throw "Cython Utility data was not bundled into the local OCR worker."
}

$requiredPaddleSources = @(
    "paddleocr\tools\__init__.py",
    "paddleocr\ppocr\__init__.py"
)
foreach ($relativePath in $requiredPaddleSources) {
    $sourceFile = Get-ChildItem -LiteralPath $workerDistPath -Recurse -Filter (Split-Path -Leaf $relativePath) -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName.EndsWith($relativePath, [System.StringComparison]::OrdinalIgnoreCase) } |
        Select-Object -First 1
    if ($null -eq $sourceFile) {
        throw "PaddleOCR runtime source was not bundled: $relativePath"
    }
    Write-Host "PaddleOCR runtime source found: $($sourceFile.FullName)"
}

$smokeTest = Start-Process -FilePath $exePath -ArgumentList "--smoke" -WorkingDirectory "C:\" -WindowStyle Hidden -Wait -PassThru
if ($smokeTest.ExitCode -ne 0) {
    throw "Local OCR worker PaddleOCR import smoke test failed with exit code $($smokeTest.ExitCode)."
}

$files = Get-ChildItem -LiteralPath $workerDistPath -Recurse -File
$size = ($files | Measure-Object -Property Length -Sum).Sum
$exe = Get-Item -LiteralPath $exePath
Write-Host "Local OCR worker build succeeded: $($exe.FullName)"
Write-Host "Executable size: $([math]::Round($exe.Length / 1MB, 2)) MB"
Write-Host "Worker directory size: $([math]::Round($size / 1MB, 2)) MB"
Write-Host "Cython Utility data found: $($cythonUtilityFile.FullName)"
