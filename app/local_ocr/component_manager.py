"""Installation lifecycle for the optional Local OCR component."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

from app.local_ocr.manifest import ComponentManifest, ManifestError
from app.local_ocr.platform import LocalOCRPlatformSpec, current_spec, spec_for_manifest
from app.local_ocr.version import current_local_ocr_version
from app.runtime_paths import user_runtime_directory


class ComponentError(RuntimeError):
    """A user-facing component installation error."""


class ComponentCancelled(ComponentError):
    """Raised when a component operation is cooperatively cancelled."""


ProgressCallback = Callable[[int], None]


class LocalOCRComponentManager:
    """Manage one versioned, user-writable Local OCR installation."""

    def __init__(
        self,
        runtime_root: Path | str | None = None,
        version: str | None = None,
        platform_spec: LocalOCRPlatformSpec | None = None,
    ) -> None:
        self.runtime_root = Path(runtime_root) if runtime_root is not None else user_runtime_directory()
        self.version = version or current_local_ocr_version()
        self._platform_spec_explicit = platform_spec is not None
        self.platform_spec = platform_spec or current_spec()

    @property
    def components_root(self) -> Path:
        return self.runtime_root / "components" / "local-ocr"

    def installed_path(self) -> Path:
        return self.components_root / self.version

    def installed_executable(self) -> Path:
        return self.installed_path() / self.platform_spec.executable_name

    def is_installed(self) -> bool:
        return self.verify_installation()

    def installed_version(self) -> str | None:
        return self.version if self.is_installed() else None

    def verify_installation(self, path: Path | None = None) -> bool:
        root = path or self.installed_path()
        executable = root / self.platform_spec.executable_name
        if not executable.is_file() or not (root / "_internal").is_dir():
            return False
        if self.platform_spec.platform_id.startswith("macos"):
            if not os.access(executable, os.X_OK):
                return False
            return self._models_are_complete(root / "models")
        return True

    def smoke_test(self, path: Path | None = None, timeout: float | None = None) -> bool:
        root = path or self.installed_path()
        executable = root / self.platform_spec.executable_name
        if not self.verify_installation(root):
            return False
        if timeout is None:
            timeout = 120.0 if self.platform_spec.platform_id.startswith("macos") else 30.0
        command = [str(executable), "--smoke"]
        if self.platform_spec.platform_id.startswith("macos"):
            command.extend(["--model-root", str(root / "models")])
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    def install_archive(
        self,
        archive_path: Path | str,
        manifest: ComponentManifest,
        *,
        cancel_event: threading.Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> Path:
        if manifest.version != self.version:
            raise ComponentError("Local OCR component version is not supported by this application.")
        manifest_spec = spec_for_manifest(manifest.platform, manifest.arch)
        if manifest_spec is None:
            raise ComponentError("Local OCR component platform or architecture is unsupported.")
        if not self._platform_spec_explicit and manifest_spec.platform_id != current_spec().platform_id:
            raise ComponentError("Local OCR component platform or architecture is unsupported on this host.")
        # ComponentManifest has already performed host validation. Selecting
        # from its normalized values keeps explicit fixture managers stable.
        self.platform_spec = manifest_spec
        archive = Path(archive_path)
        if not archive.is_file():
            raise ComponentError("Local OCR download file is missing.")
        if self._cancelled(cancel_event):
            raise ComponentCancelled("Local OCR installation cancelled.")
        if progress:
            progress(0)
        if self._sha256(archive) != manifest.sha256.lower():
            self._safe_unlink(archive)
            raise ComponentError("Local OCR download checksum verification failed. Please download again.")

        staging: Path | None = None
        try:
            self.components_root.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{self.version}-staging-", dir=self.components_root))
            self._safe_extract(archive, staging, cancel_event)
            self._ensure_expected_executable(staging)
            if not self.verify_installation(staging):
                raise ComponentError("Local OCR package layout is invalid.")
            if progress:
                progress(90)
            if self._cancelled(cancel_event):
                raise ComponentCancelled("Local OCR installation cancelled.")
            if not self.smoke_test(staging):
                raise ComponentError("Local OCR component smoke test failed.")
            installed = self._atomic_activate(staging)
            staging = None
            if progress:
                progress(100)
            return installed
        finally:
            self._safe_unlink(archive)
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    def remove(self) -> bool:
        target = self.installed_path()
        if not target.exists():
            return False
        shutil.rmtree(target)
        return True

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _cancelled(cancel_event: threading.Event | None) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    @classmethod
    def _safe_extract(
        cls,
        archive: Path,
        destination: Path,
        cancel_event: threading.Event | None,
    ) -> None:
        try:
            with zipfile.ZipFile(archive) as bundle:
                root = destination.resolve()
                for member in bundle.infolist():
                    if cls._cancelled(cancel_event):
                        raise ComponentCancelled("Local OCR installation cancelled.")
                    name = member.filename.replace("\\", "/")
                    posix = PurePosixPath(name)
                    windows = PureWindowsPath(name)
                    if not name or posix.is_absolute() or windows.is_absolute() or windows.drive:
                        raise ComponentError("Local OCR archive contains an unsafe path.")
                    if ".." in posix.parts:
                        raise ComponentError("Local OCR archive contains an unsafe path.")
                    target = (destination / Path(*posix.parts)).resolve()
                    if os.path.commonpath((str(root), str(target))) != str(root):
                        raise ComponentError("Local OCR archive contains an unsafe path.")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    if member.external_attr >> 16 & 0o170000 == 0o120000:
                        raise ComponentError("Local OCR archive contains an unsafe link.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    # Preserve only executable bits recorded by the archive.
                    # PyInstaller macOS onedir components need these bits on
                    # the worker and bundled Mach-O dylibs after extraction.
                    mode = (member.external_attr >> 16) & 0o777
                    if mode & 0o111:
                        target.chmod(target.stat().st_mode | (mode & 0o111))
        except zipfile.BadZipFile as exc:
            raise ComponentError("Local OCR download is not a valid ZIP archive.") from exc

    def _ensure_expected_executable(self, root: Path) -> None:
        executable = root / self.platform_spec.executable_name
        if not executable.is_file():
            return
        if self.platform_spec.platform_id.startswith("macos"):
            executable.chmod(executable.stat().st_mode | 0o111)

    @staticmethod
    def _models_are_complete(model_root: Path) -> bool:
        if not model_root.is_dir():
            return False
        for kind in ("det", "rec"):
            directory = model_root / kind
            if not directory.is_dir():
                return False
            if not any(directory.rglob("inference.pdmodel")):
                return False
            if not any(directory.rglob("inference.pdiparams")):
                return False
        return True

    def _atomic_activate(self, staging: Path) -> Path:
        target = self.installed_path()
        backup: Path | None = None
        if target.exists():
            backup = self.components_root / f".{self.version}-backup-{uuid.uuid4().hex}"
            target.replace(backup)
        try:
            staging.replace(target)
        except OSError as exc:
            if backup is not None and not target.exists():
                backup.replace(target)
            raise ComponentError("Local OCR installation could not be activated.") from exc
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return target

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# Short public name for callers that do not need to know the component kind.
ComponentManager = LocalOCRComponentManager
