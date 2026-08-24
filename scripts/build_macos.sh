#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
codesign_path="/usr/bin/codesign"
python_path="$repo_root/.venv/bin/python"
if [[ ! -x "$python_path" ]]; then
    python_path="$(command -v python3 || true)"
fi
if [[ -z "$python_path" || ! -x "$python_path" ]]; then
    echo "Python 3 was not found. Create .venv or put python3 on PATH." >&2
    exit 1
fi

spec_path="$repo_root/packaging/macos/tellme_sensei.spec"
dist_path="$repo_root/dist/macos"
work_path="$repo_root/build/macos"
app_path="$dist_path/TellMeSensei.app"
identity="${TELLME_MACOS_CODESIGN_IDENTITY:-}"

if [[ ! -f "$spec_path" ]]; then
    echo "PyInstaller spec was not found: $spec_path" >&2
    exit 1
fi
if [[ ! -x "$codesign_path" ]]; then
    echo "macOS codesign tool was not found: $codesign_path" >&2
    exit 1
fi

if [[ -n "$identity" ]]; then
    identity_output="$(security find-identity -v -p codesigning)"
    if ! grep -Fq "$identity" <<<"$identity_output"; then
        echo "The requested macOS codesigning identity is not available: $identity" >&2
        echo "$identity_output" >&2
        exit 1
    fi
fi

pyinstaller_args=(
    -m PyInstaller
    --noconfirm
    --clean
    --distpath "$dist_path"
    --workpath "$work_path"
)
if [[ -n "$identity" ]]; then
    pyinstaller_args+=(--codesign-identity "$identity")
fi
pyinstaller_args+=("$spec_path")

cd "$repo_root"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-/tmp/tellmesensei-pyinstaller}" \
    "$python_path" "${pyinstaller_args[@]}"

if [[ ! -x "$app_path/Contents/MacOS/TellMeSensei" ]]; then
    echo "macOS app executable was not created: $app_path" >&2
    exit 1
fi

plist_path="$app_path/Contents/Info.plist"
ls_ui_element="$(plutil -extract LSUIElement raw -o - "$plist_path")"
bundle_identifier="$(plutil -extract CFBundleIdentifier raw -o - "$plist_path")"
bundle_version="$(plutil -extract CFBundleVersion raw -o - "$plist_path")"
if [[ "$ls_ui_element" != "1" && "$ls_ui_element" != "true" ]] || \
    [[ "$bundle_identifier" != "com.tellmesensei.app" || "$bundle_version" != "0.5.0" ]]; then
    echo "Unexpected macOS bundle metadata in $plist_path" >&2
    plutil -p "$plist_path" >&2
    exit 1
fi

forbidden_path="$(find "$app_path" -type d \( -iname paddle -o -iname paddleocr -o -iname ppocr -o -iname ppstructure -o -iname Cython \) -print -quit)"
if [[ -n "$forbidden_path" ]]; then
    echo "Forbidden Paddle/Cython runtime was bundled in Core: $forbidden_path" >&2
    exit 1
fi

"$app_path/Contents/MacOS/TellMeSensei" --smoke-core
"$codesign_path" --verify --deep --strict --verbose=2 "$app_path"

signature_details="$("$codesign_path" -dv --verbose=4 "$app_path" 2>&1)"
if [[ -n "$identity" ]]; then
    if grep -Fq 'Signature=adhoc' <<<"$signature_details" || ! grep -Fq 'Authority=' <<<"$signature_details"; then
        echo "Requested identity was not applied to the macOS app bundle." >&2
        echo "$signature_details" >&2
        exit 1
    fi
fi

echo "macOS build succeeded: $app_path"
echo "LSUIElement=$ls_ui_element"
echo "CFBundleIdentifier=$bundle_identifier"
echo "CFBundleVersion=$bundle_version"
if [[ -n "$identity" ]]; then
    echo "Code signing identity: $identity"
else
    echo "Code signing identity: ad-hoc"
fi
echo "$signature_details"
