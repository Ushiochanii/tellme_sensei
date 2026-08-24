#!/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="${TELLME_LOCAL_OCR_PYTHON:-$(command -v python3 || true)}"
codesign_path="/usr/bin/codesign"
spec_path="$repo_root/packaging/local_ocr_worker.spec"
constraints_path="$repo_root/packaging/macos/local_ocr_x64_constraints.txt"
dist_path="$repo_root/dist/local-ocr-macos-x64"
work_path="$repo_root/build/local-ocr-macos-x64"
worker_path="$dist_path/LocalOCR/TellMeSenseiOCR"

if [[ -z "$python_path" || ! -x "$python_path" ]]; then
    echo "Python 3.12 executable was not found. Activate the Local OCR build environment or set TELLME_LOCAL_OCR_PYTHON." >&2
    exit 1
fi
if [[ ! -f "$spec_path" ]]; then
    echo "Local OCR worker spec was not found: $spec_path" >&2
    exit 1
fi
if [[ ! -f "$constraints_path" ]]; then
    echo "macOS x64 constraints were not found: $constraints_path" >&2
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
    raise SystemExit(f"macOS Local OCR build requires darwin, got {sys.platform}")
if platform.machine() != "x86_64":
    raise SystemExit(
        f"This build entry targets Intel x86_64, got {platform.machine()}"
    )
if sys.version_info[:2] != (3, 12):
    raise SystemExit(
        f"This build entry requires Python 3.12, got {sys.version_info.major}.{sys.version_info.minor}"
    )

expected = {
    "numpy": "1.26.4",
    "paddlepaddle": "2.6.2",
    "paddleocr": "2.7.3",
    "opencv-python": "4.6.0.66",
}
for package, required_version in expected.items():
    actual_version = importlib.metadata.version(package)
    if actual_version != required_version:
        raise SystemExit(
            f"{package}=={required_version} is required, got {actual_version}"
        )

import numpy

if int(numpy.__version__.split(".", 1)[0]) >= 2:
    raise SystemExit(f"NumPy 2.x is not supported by this Local OCR baseline: {numpy.__version__}")

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
print(f"Constraints: {repo_root / 'packaging/macos/local_ocr_x64_constraints.txt'}")
PY

echo "Cleaning macOS Local OCR build outputs: $dist_path and $work_path"
rm -rf "$dist_path" "$work_path"

cd "$repo_root"
PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-/tmp/tellmesensei-pyinstaller-ocr}" \
    "$python_path" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$dist_path" \
    --workpath "$work_path" \
    "$spec_path"

if [[ ! -x "$worker_path" ]]; then
    echo "macOS Local OCR worker executable was not created: $worker_path" >&2
    exit 1
fi

if find "$dist_path/LocalOCR" -iname '*PySide6*' -print -quit | grep -q .; then
    echo "PySide6 was bundled into the standalone Local OCR worker." >&2
    exit 1
fi

file "$worker_path"
if ! file "$worker_path" | grep -Fq 'Mach-O 64-bit executable x86_64'; then
    echo "Unexpected Local OCR worker architecture: $worker_path" >&2
    exit 1
fi

clean_env=(env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" HOME="${HOME:-/tmp}")
"${clean_env[@]}" "$worker_path" --help >/dev/null

model_source="${TELLME_LOCAL_OCR_MODEL_ROOT:-$HOME/.paddleocr}"
model_target="$dist_path/LocalOCR/models"
MODEL_SOURCE="$model_source" MODEL_TARGET="$model_target" "$python_path" - <<'PY'
from pathlib import Path
import os
import shutil

source = Path(os.environ["MODEL_SOURCE"])
target = Path(os.environ["MODEL_TARGET"])
if not source.is_dir():
    raise SystemExit(f"PaddleOCR model cache was not found: {source}")
for kind in ("det", "rec"):
    matches = sorted(
        path.parent
        for path in source.rglob("inference.pdmodel")
        if kind in path.parts and (path.parent / "inference.pdiparams").is_file()
    )
    if not matches:
        raise SystemExit(f"Japanese {kind} model was not found below {source}")
    destination = target / kind / matches[0].name
    shutil.copytree(matches[0], destination, dirs_exist_ok=True)
    print(f"Bundled {kind} model: {destination}")
PY

build_home="${TMPDIR:-/tmp}/tellmesensei-local-ocr-build-home"
mkdir -p "$build_home"
env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" HOME="$build_home" \
    "$worker_path" --smoke --model-root "$model_target"

"$codesign_path" -d -v "$worker_path" 2>&1 | sed -n '1,8p'
"$codesign_path" --verify "$worker_path"

echo "macOS Local OCR worker build succeeded: $dist_path/LocalOCR"
