#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="${TELLME_LOCAL_OCR_ARM64_PYTHON:-$(command -v python3 || true)}"
codesign_path="/usr/bin/codesign"
spec_path="$repo_root/packaging/local_ocr_worker_arm64.spec"
constraints_path="$repo_root/packaging/macos/local_ocr_arm64_constraints.txt"
dist_path="$repo_root/dist/local-ocr-macos-arm64"
work_path="$repo_root/build/local-ocr-macos-arm64"
worker_path="$dist_path/LocalOCR/TellMeSenseiOCR"

if [[ -z "$python_path" || ! -x "$python_path" ]]; then
    echo "Native ARM64 Python 3.12 was not found. Set TELLME_LOCAL_OCR_ARM64_PYTHON." >&2
    exit 1
fi
if [[ ! -f "$spec_path" || ! -f "$constraints_path" ]]; then
    echo "ARM64 worker spec or constraints are missing." >&2
    exit 1
fi
if [[ ! -x "$codesign_path" ]]; then
    echo "macOS codesign tool was not found: $codesign_path" >&2
    exit 1
fi

"$python_path" - "$repo_root" <<'PY'
import importlib.metadata
import platform
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
if sys.platform != "darwin":
    raise SystemExit(f"macOS ARM64 Local OCR build requires darwin, got {sys.platform}")
if platform.machine() != "arm64":
    raise SystemExit(f"This build requires native arm64 Python, got {platform.machine()}")
if sys.version_info[:2] != (3, 12):
    raise SystemExit(
        f"This build requires Python 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
    )

expected = {
    "numpy": "2.3.5",
    "paddlepaddle": "3.3.0",
    "paddleocr": "3.7.0",
    "paddlex": "3.7.2",
    "opencv-contrib-python": "4.10.0.84",
    "pyinstaller": "6.22.2",
}
for package, required_version in expected.items():
    actual_version = importlib.metadata.version(package)
    if actual_version != required_version:
        raise SystemExit(
            f"{package}=={required_version} is required, got {actual_version}"
        )

try:
    import PySide6  # noqa: F401
except ImportError:
    pass
else:
    raise SystemExit("PySide6 must not be installed in the standalone worker build environment")

print(f"Python: {sys.version.split()[0]}")
print(f"Architecture: {platform.machine()}")
print("PySide6: not installed")
for package, required_version in expected.items():
    print(f"{package}: {required_version}")
print(f"Constraints: {repo_root / 'packaging/macos/local_ocr_arm64_constraints.txt'}")
PY

echo "Cleaning ARM64 Local OCR build outputs: $dist_path and $work_path"
rm -rf "$dist_path" "$work_path"

cd "$repo_root"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-/tmp/tellmesensei-pyinstaller-ocr-arm64}" \
    "$python_path" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$dist_path" \
    --workpath "$work_path" \
    "$spec_path"

if [[ ! -x "$worker_path" ]]; then
    echo "ARM64 Local OCR worker executable was not created: $worker_path" >&2
    exit 1
fi

if find "$dist_path/LocalOCR" -iname '*PySide6*' -print -quit | grep -q .; then
    echo "PySide6 was bundled into the standalone ARM64 Local OCR worker." >&2
    exit 1
fi

worker_file="$(file "$worker_path")"
echo "$worker_file"
if [[ "$worker_file" != *"Mach-O 64-bit executable arm64"* ]]; then
    echo "Unexpected ARM64 Local OCR worker architecture: $worker_path" >&2
    exit 1
fi

native_report="$({
    find "$dist_path/LocalOCR" -type f \
        \( -name '*.dylib' -o -name '*.so' -o -name '*.so.*' -perm -111 \) \
        -print0 | xargs -0 -n1 file
} || true)"
if grep -E 'Mach-O.*x86_64' <<<"$native_report" | grep -v 'universal' >/dev/null; then
    echo "An x86_64-only native file was bundled in the ARM64 worker:" >&2
    grep -E 'Mach-O.*x86_64' <<<"$native_report" >&2
    exit 1
fi
printf '%s\n' "$native_report" | awk '/Mach-O/ {n++; if (/universal/) u++; else if (/arm64/) a++} END {printf "Mach-O files: %d arm64-only, %d universal2\n", a, u}'

"$codesign_path" --force --sign - "$worker_path" >/dev/null
"$codesign_path" --verify "$worker_path"

clean_env=(env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin")
"${clean_env[@]}" HOME="${TMPDIR:-/tmp}/tellmesensei-arm64-frozen-help-home" \
    "$worker_path" --help >/dev/null

det_model="${TELLME_LOCAL_OCR_ARM64_DET_MODEL:-$HOME/.paddlex/official_models/PP-OCRv6_medium_det}"
rec_model="${TELLME_LOCAL_OCR_ARM64_REC_MODEL:-$HOME/.paddlex/official_models/PP-OCRv6_medium_rec}"
model_target="$dist_path/LocalOCR/models"
DET_MODEL="$det_model" REC_MODEL="$rec_model" MODEL_TARGET="$model_target" \
    "$python_path" - <<'PY'
from pathlib import Path
import os
import shutil

from app.local_ocr.model_layout import ModelLayoutError, detect_model_layout

target = Path(os.environ["MODEL_TARGET"])
target.mkdir(parents=True, exist_ok=True)
for kind, variable in (("det", "DET_MODEL"), ("rec", "REC_MODEL")):
    source = Path(os.environ[variable]).expanduser().resolve()
    try:
        layout = detect_model_layout(source)
    except ModelLayoutError as exc:
        raise SystemExit(str(exc)) from exc
    if layout is None:
        raise SystemExit(f"Incomplete PaddleOCR model directory: {source}")
    destination = target / kind / source.name
    shutil.copytree(source, destination, dirs_exist_ok=True)
    print(f"Bundled {kind} model ({layout}): {destination}")
PY

build_home="${TMPDIR:-/tmp}/tellmesensei-local-ocr-arm64-frozen-home"
rm -rf "$build_home"
mkdir -p "$build_home"
env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" HOME="$build_home" \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    "$worker_path" --smoke --model-root "$model_target"

echo "macOS ARM64 Local OCR frozen worker build succeeded: $dist_path/LocalOCR"
