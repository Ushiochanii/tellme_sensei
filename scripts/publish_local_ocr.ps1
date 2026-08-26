param(
    [string]$DistributionRepository = "Ushiochanii/tellme_sensei"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This publishing script must run on Windows."
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if ($null -eq $gh) {
    throw "GitHub CLI (gh) was not found. Install it and run gh auth login first."
}

& $gh.Source auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI authentication is required. Run gh auth login first."
}

$repoJson = (& $gh.Source repo view $DistributionRepository --json isPrivate 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoJson)) {
    throw "Distribution repository was not found: $DistributionRepository"
}
$repoInfo = $repoJson | ConvertFrom-Json
if ($repoInfo.isPrivate) {
    throw "Distribution repository must be public: $DistributionRepository"
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) { throw "Python was not found." }
    $pythonPath = $pythonCommand.Source
}
$version = (& $pythonPath -c "from app.local_ocr.version import LOCAL_OCR_VERSION; print(LOCAL_OCR_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
    throw "Could not read the Local OCR component version."
}

$tag = "local-ocr-v$version"
$archiveName = "TellMeSensei-LocalOCR-$version-windows-x64.zip"
$componentsPath = Join-Path $repoRoot "dist\components"
$archivePath = Join-Path $componentsPath $archiveName
$manifestName = "local-ocr-manifest-windows-x64.json"
$manifestPath = Join-Path $componentsPath $manifestName
foreach ($requiredPath in @($archivePath, $manifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required distribution artifact was not found: $requiredPath"
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.component -ne "local-ocr" -or
    $manifest.version -ne $version -or $manifest.platform -ne "windows" -or
    $manifest.arch -ne "x86_64" -or $manifest.archive_format -ne "zip") {
    throw "Distribution manifest metadata does not match Local OCR $version."
}
$archive = Get-Item -LiteralPath $archivePath
$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ([int64]$manifest.size -ne [int64]$archive.Length -or $manifest.sha256.ToLowerInvariant() -ne $actualHash) {
    throw "Distribution manifest does not match the archive bytes."
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $gh.Source release view $tag --repo $DistributionRepository 2>$null
$releaseViewExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($releaseViewExitCode -eq 0) {
    throw "Release already exists. Bump the component version instead of overwriting a published component."
}

$title = "TellMeSensei Local OCR v$version"
$notes = "Windows x86_64`nPaddleOCR local component`npersistent worker support`nbackground prewarm support"
& $gh.Source release create $tag $archivePath $manifestPath --repo $DistributionRepository --title $title --notes $notes
if ($LASTEXITCODE -ne 0) {
    throw "GitHub release creation failed."
}

$baseUrl = "https://github.com/$DistributionRepository/releases/download/$tag"
$manifestUrl = "$baseUrl/$manifestName"
$archiveUrl = "$baseUrl/$archiveName"
$verifyRoot = Join-Path ([IO.Path]::GetTempPath()) ("tellme-sensei-release-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $verifyRoot -Force | Out-Null
try {
    $downloadedManifestPath = Join-Path $verifyRoot $manifestName
    $downloadedArchivePath = Join-Path $verifyRoot $archiveName
    Invoke-WebRequest -Uri $manifestUrl -OutFile $downloadedManifestPath -UseBasicParsing -TimeoutSec 600
    Invoke-WebRequest -Uri $archiveUrl -OutFile $downloadedArchivePath -UseBasicParsing -TimeoutSec 600
    $onlineManifest = Get-Content -LiteralPath $downloadedManifestPath -Raw | ConvertFrom-Json
    $onlineHash = (Get-FileHash -LiteralPath $downloadedArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($onlineManifest.version -ne $version -or $onlineManifest.sha256.ToLowerInvariant() -ne $onlineHash) {
        throw "Anonymous release verification failed: manifest and archive do not match."
    }
} finally {
    Remove-Item -LiteralPath $verifyRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Release page: https://github.com/$DistributionRepository/releases/tag/$tag"
Write-Host "Manifest URL: $manifestUrl"
Write-Host "Archive URL: $archiveUrl"
Write-Host "Version: $version"
Write-Host "Archive size: $($archive.Length) bytes"
Write-Host "SHA256: $actualHash"
