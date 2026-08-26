param(
    [string]$DistributionRepository = "Ushiochanii/tellme_sensei",
    [string]$DownloadUrl = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This packaging script must run on Windows."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$sourcePath = Join-Path $repoRoot "dist\LocalOCR"
$outputPath = Join-Path $repoRoot "dist\components"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) { throw "Python was not found." }
    $pythonPath = $pythonCommand.Source
}
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "Local OCR build was not found: $sourcePath"
}

$version = (& $pythonPath -c "from app.local_ocr.version import LOCAL_OCR_VERSION; print(LOCAL_OCR_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw "Could not read the Local OCR component version."
}
$archiveName = "TellMeSensei-LocalOCR-$version-windows-x64.zip"
$releaseTag = "local-ocr-v$version"
$archivePath = Join-Path $outputPath $archiveName
$manifestName = "local-ocr-manifest-windows-x64.json"
$manifestPath = Join-Path $outputPath $manifestName
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
Compress-Archive -Path (Join-Path $sourcePath "*") -DestinationPath $archivePath -CompressionLevel Optimal

$archive = Get-Item -LiteralPath $archivePath
$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($DownloadUrl)) {
    $DownloadUrl = "https://github.com/$DistributionRepository/releases/download/$releaseTag/$archiveName"
}
$manifestUrl = "https://github.com/$DistributionRepository/releases/download/$releaseTag/$manifestName"
$manifest = [ordered]@{
    schema_version = 1
    component = "local-ocr"
    version = $version
    platform = "windows"
    arch = "x86_64"
    url = $DownloadUrl
    sha256 = $hash
    size = [int64]$archive.Length
    archive_format = "zip"
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Version: $version"
Write-Host "Release tag: $releaseTag"
Write-Host "Archive path: $($archive.FullName)"
Write-Host "Archive size: $([math]::Round($archive.Length / 1MB, 2)) MB ($($archive.Length) bytes)"
Write-Host "SHA256: $hash"
Write-Host "Manifest path: $manifestPath"
Write-Host "Manifest URL: $manifestUrl"
Write-Host "Archive URL: $DownloadUrl"
