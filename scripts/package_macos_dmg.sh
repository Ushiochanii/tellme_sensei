#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This DMG packaging script must run on macOS." >&2
    exit 1
fi

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
python_path="$repo_root/.venv/bin/python"
if [[ ! -x "$python_path" ]]; then
    python_path="$(command -v python3 || true)"
fi
if [[ -z "$python_path" || ! -x "$python_path" ]]; then
    echo "Python 3 was not found. Create .venv or put python3 on PATH." >&2
    exit 1
fi

app_path="$repo_root/dist/macos/TellMeSensei.app"
release_path="$repo_root/dist/release"
version="$("$python_path" -c 'from app.version import __version__; print(__version__)')"
executable_path="$app_path/Contents/MacOS/TellMeSensei"
plist_path="$app_path/Contents/Info.plist"

if [[ ! -d "$app_path" || ! -x "$executable_path" ]]; then
    echo "Expected macOS app bundle was not found: $app_path" >&2
    exit 1
fi
if [[ ! -f "$plist_path" ]]; then
    echo "App Info.plist was not found: $plist_path" >&2
    exit 1
fi

bundle_identifier="$(plutil -extract CFBundleIdentifier raw -o - "$plist_path")"
bundle_version="$(plutil -extract CFBundleVersion raw -o - "$plist_path")"
ls_ui_element="$(plutil -extract LSUIElement raw -o - "$plist_path")"
if [[ "$bundle_identifier" != "com.tellmesensei.app" || "$bundle_version" != "$version" ]]; then
    echo "Unexpected app metadata in $plist_path" >&2
    plutil -p "$plist_path" >&2
    exit 1
fi
if [[ "$ls_ui_element" != "1" && "$ls_ui_element" != "true" ]]; then
    echo "LSUIElement must be true for the tray application." >&2
    exit 1
fi
executable_format="$(file "$executable_path")"
if grep -Fq "Mach-O universal binary" <<<"$executable_format"; then
    echo "Universal2 macOS app binaries are not accepted by this native DMG pipeline." >&2
    echo "$executable_format" >&2
    exit 1
elif grep -Fq "Mach-O 64-bit executable arm64" <<<"$executable_format"; then
    dmg_arch="arm64"
elif grep -Fq "Mach-O 64-bit executable x86_64" <<<"$executable_format"; then
    dmg_arch="x64"
else
    echo "The macOS app executable is not a supported native arm64 or x86_64 Mach-O binary." >&2
    echo "$executable_format" >&2
    exit 1
fi
dmg_path="$release_path/TellMeSensei-$version-macos-$dmg_arch.dmg"
/usr/bin/codesign --verify --deep --strict "$app_path"

if grep -R -aEq '127\.0\.0\.1:8765|localhost:8765|downloads\.example\.invalid' "$app_path"; then
    echo "Development manifest URL found in the app bundle." >&2
    exit 1
fi
if find "$app_path" \( -iname 'LocalOCR' -o -iname 'TellMeSenseiOCR*' \) -print -quit | grep -q .; then
    echo "Local OCR component content must not be included in the Core DMG." >&2
    exit 1
fi

dmg_overwrite="$(printenv TELLME_MACOS_DMG_OVERWRITE || true)"
if [[ -e "$dmg_path" ]]; then
    if [[ "$dmg_overwrite" != "1" ]]; then
        echo "DMG already exists; set TELLME_MACOS_DMG_OVERWRITE=1 for a development overwrite: $dmg_path" >&2
        exit 1
    fi
    rm -f "$dmg_path"
fi

mkdir -p "$release_path"
tmp_dir="$(printenv TMPDIR || echo /tmp)"
staging_path="$(mktemp -d "$tmp_dir/tellmesensei-dmg.XXXXXX")"
cleanup() {
    rm -rf "$staging_path"
}
trap cleanup EXIT

ditto "$app_path" "$staging_path/TellMeSensei.app"
ln -s /Applications "$staging_path/Applications"
/usr/bin/hdiutil create \
    -volname "TellMeSensei $version" \
    -srcfolder "$staging_path" \
    -format UDZO \
    -ov \
    "$dmg_path"

echo "DMG created: $dmg_path"
echo "Version: $version"
echo "Architecture: $dmg_arch"
