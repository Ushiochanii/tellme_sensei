#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_path="${TELLME_LOCAL_OCR_SOURCE:-$repo_root/dist/local-ocr-macos-x64/LocalOCR}"
output_path="${TELLME_LOCAL_OCR_OUTPUT:-$repo_root/dist/components-macos-x64}"
python_path="${TELLME_LOCAL_OCR_PYTHON:-$(command -v python3 || true)}"
base_url="${TELLME_LOCAL_OCR_BASE_URL:-http://127.0.0.1:8765}"

if [[ ! -x "$source_path/TellMeSenseiOCR" ]]; then
    echo "macOS Local OCR source executable was not found: $source_path/TellMeSenseiOCR" >&2
    exit 1
fi
if [[ ! -d "$source_path/models/det" || ! -d "$source_path/models/rec" ]]; then
    echo "Bundled Japanese det/rec models were not found below: $source_path/models" >&2
    exit 1
fi
if [[ -z "$python_path" || ! -x "$python_path" ]]; then
    echo "Python was not found; set TELLME_LOCAL_OCR_PYTHON." >&2
    exit 1
fi

mkdir -p "$output_path"
version="$($python_path -c 'from app.local_ocr.version import LOCAL_OCR_VERSION; print(LOCAL_OCR_VERSION)')"
archive="$output_path/TellMeSensei-LocalOCR-${version}-macos-x64-dev.zip"
manifest="$output_path/local-ocr-manifest-macos-x64-dev.json"
rm -f "$archive" "$manifest"

(cd "$source_path" && zip -qr "$archive" .)

ARCHIVE="$archive" MANIFEST="$manifest" BASE_URL="$base_url" VERSION="$version" \
  "$python_path" - <<'PY'
from pathlib import Path
import hashlib
import json
import os

archive = Path(os.environ["ARCHIVE"])
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
payload = {
    "schema_version": 1,
    "component": "local-ocr",
    "version": os.environ["VERSION"],
    "platform": "macos",
    "arch": "x86_64",
    "url": f"{os.environ['BASE_URL'].rstrip('/')}/{archive.name}",
    "sha256": digest,
    "size": archive.stat().st_size,
    "archive_format": "zip",
}
Path(os.environ["MANIFEST"]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"Archive: {archive}")
print(f"Size: {payload['size']} bytes")
print(f"SHA256: {digest}")
print(f"Manifest: {os.environ['MANIFEST']}")
PY
