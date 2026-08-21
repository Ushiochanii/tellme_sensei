$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This installer build script must run on Windows."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "Python was not found. Create .venv or put python on PATH."
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

$versionMatch = [regex]::Match($version, '^(\d+\.\d+\.\d+)')
if (-not $versionMatch.Success) {
    throw "Unsupported application version: $version"
}
$installerAppVersion = $versionMatch.Groups[1].Value

$buildScript = Join-Path $repoRoot "scripts\build_windows.ps1"
$issPath = Join-Path $repoRoot "packaging\windows\tellme_sensei.iss"
$portablePath = Join-Path $repoRoot "dist\TellMeSensei"
$portableExePath = Join-Path $portablePath "TellMeSensei.exe"
$installerPath = Join-Path $repoRoot "dist\installer"

if (-not (Test-Path -LiteralPath $buildScript)) {
    throw "Portable build script was not found: $buildScript"
}
if (-not (Test-Path -LiteralPath $issPath)) {
    throw "Inno Setup script was not found: $issPath"
}

Write-Host "Building portable application..."
& $buildScript
if ($LASTEXITCODE -ne 0) {
    throw "Portable build failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path -LiteralPath $portableExePath)) {
    throw "Portable executable was not created: $portableExePath"
}

$isccPath = $null
$isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($null -ne $isccCommand) {
    $isccPath = $isccCommand.Source
}
if ($null -eq $isccPath) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            $isccPath = $candidate
            break
        }
    }
}
if ($null -eq $isccPath) {
    throw "Inno Setup 6 / ISCC.exe not found. Install Inno Setup 6 and rerun this script; automatic download is not performed."
}

New-Item -ItemType Directory -Path $installerPath -Force | Out-Null
$isccArguments = @(
    "/DVersionLabel=$version",
    "/DAppVersion=$installerAppVersion",
    "/DPortableDir=$portablePath",
    "/DOutputDir=$installerPath",
    $issPath
)
Write-Host "Compiling installer with: $isccPath"
& $isccPath @isccArguments
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
}

$installerExePath = Join-Path $installerPath "TellMeSensei-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installerExePath)) {
    throw "Installer executable was not created: $installerExePath"
}

$portableSize = (Get-ChildItem -LiteralPath $portablePath -Recurse -File | Measure-Object -Property Length -Sum).Sum
$installer = Get-Item -LiteralPath $installerExePath
Write-Host "Portable path: $portablePath"
Write-Host "Portable size: $([math]::Round($portableSize / 1MB, 2)) MB"
Write-Host "Installer path: $($installer.FullName)"
Write-Host "Installer size: $([math]::Round($installer.Length / 1MB, 2)) MB"
Write-Host "Version: $version"
Write-Host "Inno Setup compiler: $isccPath"
