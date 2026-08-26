#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="${TELLME_VISION_LITE_PYTHON:-$repo_root/.venv/bin/python}"
if [[ ! -x "$python_path" ]]; then
    python_path="$(command -v python3 || true)"
fi
if [[ -z "$python_path" || ! -x "$python_path" ]]; then
    echo "Python 3 was not found." >&2
    exit 1
fi

spec_path="$repo_root/packaging/macos/tellme_sensei_vision_lite.spec"
dist_path="$repo_root/dist/vision-lite-macos-arm64"
work_path="$repo_root/build/vision-lite-macos-arm64"
app_path="$dist_path/TellMeSensei Lite.app"
executable_path="$app_path/Contents/MacOS/TellMeSenseiLite"
release_path="$repo_root/dist/release"

"$python_path" - "$repo_root" <<'PY'
import platform
import sys
from pathlib import Path

root = Path(sys.argv[1])
if sys.platform != "darwin" or platform.machine() != "arm64":
    raise SystemExit("Vision Lite build requires native macOS arm64")
if sys.version_info[:2] != (3, 12):
    raise SystemExit("Vision Lite build requires Python 3.12")
print(f"Python: {sys.version.split()[0]}")
print(f"Architecture: {platform.machine()}")
sys.path.insert(0, str(root))
from app.lite_version import __version__
print(f"Version: {__version__}")
PY

cd "$repo_root"
rm -rf "$dist_path" "$work_path"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-/tmp/tellmesensei-pyinstaller-lite}" \
    "$python_path" -m PyInstaller --noconfirm --clean \
    --distpath "$dist_path" --workpath "$work_path" "$spec_path"

if [[ ! -x "$executable_path" ]]; then
    echo "Lite executable was not created: $executable_path" >&2
    exit 1
fi
file "$executable_path"
file "$executable_path" | grep -F "Mach-O 64-bit executable arm64" >/dev/null

plist_path="$app_path/Contents/Info.plist"
bundle_identifier="$(plutil -extract CFBundleIdentifier raw -o - "$plist_path")"
bundle_version="$(plutil -extract CFBundleVersion raw -o - "$plist_path")"
if [[ "$bundle_identifier" != "com.tellmesensei.vision-lite" || "$bundle_version" != "0.1.0" ]]; then
    echo "Unexpected Lite bundle metadata" >&2
    plutil -p "$plist_path" >&2
    exit 1
fi

forbidden_path="$(find "$app_path" -type f | grep -E '/(paddle|paddleocr|paddlex|ppocr|ppstructure|local_ocr|Cython|google/cloud/vision)(/|$)' | head -1 || true)"
if [[ -n "$forbidden_path" ]]; then
    echo "Forbidden OCR/Paddle payload found: $forbidden_path" >&2
    exit 1
fi

/usr/bin/codesign --force --deep --sign - "$app_path" >/dev/null
/usr/bin/codesign --verify --deep --strict "$app_path"

mkdir -p "$release_path"
dmg_path="$release_path/TellMeSensei-Lite-0.1.0-macos-arm64.dmg"
rm -f "$dmg_path"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/tellmesensei-lite-dmg.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT
ditto "$app_path" "$tmp_dir/TellMeSensei Lite.app"
ln -s /Applications "$tmp_dir/Applications"
/usr/bin/hdiutil create -volname "TellMeSensei Lite 0.1.0" -srcfolder "$tmp_dir" -format UDZO -ov "$dmg_path" >/dev/null

echo "Lite app: $app_path"
echo "Lite DMG: $dmg_path"
echo "App bytes: $(du -sh "$app_path" | awk '{print $1}')"
echo "Executable bytes: $(stat -f '%z' "$executable_path")"
echo "DMG bytes: $(stat -f '%z' "$dmg_path")"
