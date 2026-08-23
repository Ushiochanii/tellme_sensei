param(
    [string]$DownloadUrl = "",
    [string]$BaseUrl = ""
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
$archiveName = "TellMeSensei-LocalOCR-$version-win-x64.zip"
$archivePath = Join-Path $outputPath $archiveName
$manifestPath = Join-Path $outputPath "local-ocr-manifest.json"
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
Compress-Archive -Path (Join-Path $sourcePath "*") -DestinationPath $archivePath -CompressionLevel Optimal

$archive = Get-Item -LiteralPath $archivePath
$hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ([string]::IsNullOrWhiteSpace($DownloadUrl)) {
    if (-not [string]::IsNullOrWhiteSpace($BaseUrl)) {
        $DownloadUrl = $BaseUrl.TrimEnd('/') + "/" + $archiveName
    } else {
        $DownloadUrl = "https://downloads.example.invalid/tellme-sensei/$archiveName"
        Write-Warning "No download URL supplied; manifest contains the distribution placeholder URL."
    }
}
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

Write-Host "Local OCR archive: $($archive.FullName)"
Write-Host "Archive size: $([math]::Round($archive.Length / 1MB, 2)) MB"
Write-Host "SHA-256: $hash"
Write-Host "Manifest: $manifestPath"
Write-Host "Version: $version"
