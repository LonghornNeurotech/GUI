"""
Auto-updater for NeuroTechGUI.

On startup, checks the latest GitHub release against the local build version.
If a newer release is available, prompts the user and (optionally) downloads it,
then spawns a small platform-specific script that replaces the running binary
and restarts the application.
"""

import os
import sys
import platform
import subprocess
import tempfile
import threading

import requests
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject

from version import CURRENT_VERSION

REPO_OWNER = "LonghornNeurotech"
REPO_NAME = "GUI"
API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"


# ── helpers ────────────────────────────────────────────────────────────────────

def _parse_build_number(tag: str) -> int | None:
    """Extract the numeric build number from a tag like 'build-42'."""
    if tag and tag.startswith("build-"):
        try:
            return int(tag.split("-", 1)[1])
        except (ValueError, IndexError):
            pass
    return None


def _find_platform_asset(assets: list[dict]) -> tuple[str | None, str | None]:
    """Find the release asset for the running OS by keyword matching.

    Returns (asset_filename, download_url) or (None, None) if no match.
    This is intentionally decoupled from the exact naming convention used
    by CI so that renaming artefacts never breaks the updater.

    On Windows, if an NSIS installer (``-Setup-`` in the name) is available
    *and* the app was installed via that installer, prefer it.  Otherwise
    fall back to the standalone ``.exe``.
    """
    system = platform.system()

    if system == "Darwin":
        matchers = [("macOS", ".zip"), ("Darwin", ".zip"), ("mac", ".zip")]
    elif system == "Windows":
        # Prefer the installer when the app was installed via NSIS;
        # otherwise prefer the standalone exe.
        if _is_installed_via_installer():
            matchers = [("Setup", ".exe"), ("Windows", ".exe"), ("Win", ".exe")]
        else:
            # Standalone: skip any asset whose name contains "Setup"
            matchers = [("Windows", ".exe"), ("Win", ".exe")]
    else:
        matchers = [("Linux", ""), ("linux", "")]

    for asset in assets:
        name: str = asset.get("name", "")
        url: str = asset.get("browser_download_url", "")
        for keyword, ext in matchers:
            if keyword.lower() in name.lower() and (not ext or name.lower().endswith(ext)):
                # For standalone mode, skip installer assets
                if system == "Windows" and not _is_installed_via_installer() and "setup" in name.lower():
                    continue
                return name, url

    return None, None


# ── public API ─────────────────────────────────────────────────────────────────

def check_for_updates() -> tuple[str | None, str | None]:
    """
    Query GitHub for the latest release.

    Returns
    -------
    (latest_tag, download_url) if a newer release exists, else (None, None).
    """
    try:
        resp = requests.get(API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None, None

    latest_tag: str = data.get("tag_name", "")
    current_num = _parse_build_number(CURRENT_VERSION)
    latest_num = _parse_build_number(latest_tag)

    # If we can compare numerically, do so; otherwise fall back to string !=
    if current_num is not None and latest_num is not None:
        if latest_num <= current_num:
            return None, None
    elif latest_tag == CURRENT_VERSION:
        return None, None

    asset_name, download_url = _find_platform_asset(data.get("assets", []))
    if asset_name and download_url:
        return latest_tag, download_url

    return None, None


# ── download with progress ────────────────────────────────────────────────────

class _DownloadSignals(QObject):
    """Signals emitted by the background download thread."""
    progress = pyqtSignal(int)        # 0-100
    finished = pyqtSignal(str)        # downloaded file path
    error = pyqtSignal(str)           # error message


def _download_worker(url: str, dest: str, signals: _DownloadSignals):
    """Download *url* into *dest*, emitting progress signals."""
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        signals.progress.emit(int(downloaded * 100 / total))
        signals.finished.emit(dest)
    except Exception as exc:
        signals.error.emit(str(exc))


# ── platform-specific updaters ────────────────────────────────────────────────

def _is_installed_via_installer() -> bool:
    """Return True if the app was installed via the NSIS installer (Windows only)."""
    if platform.system() != "Windows":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\NeuroTechGUI",
            0,
            winreg.KEY_READ,
        )
        winreg.QueryValueEx(key, "InstallPath")
        winreg.CloseKey(key)
        return True
    except (FileNotFoundError, PermissionError, OSError):
        return False


def _apply_update_windows(downloaded_path: str):
    """Apply a Windows update, choosing strategy based on install type."""
    if _is_installed_via_installer():
        _apply_update_windows_installer(downloaded_path)
    else:
        _apply_update_windows_standalone(downloaded_path)


def _apply_update_windows_installer(downloaded_path: str):
    """Run the downloaded NSIS installer silently and exit."""
    updater_bat = os.path.join(tempfile.gettempdir(), "neurotechgui_updater.bat")

    bat = f"""@echo off
timeout /t 2 /nobreak > NUL
start "" "{downloaded_path}" /S
del "%~f0"
"""
    with open(updater_bat, "w") as f:
        f.write(bat)

    subprocess.Popen(
        [updater_bat],
        creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
    )
    sys.exit(0)


def _apply_update_windows_standalone(downloaded_path: str):
    """Spawn a .bat script that replaces the exe and restarts it."""
    current_exe = sys.executable
    updater_bat = os.path.join(tempfile.gettempdir(), "neurotechgui_updater.bat")

    bat = f"""@echo off
timeout /t 2 /nobreak > NUL
move /y "{downloaded_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    with open(updater_bat, "w") as f:
        f.write(bat)

    subprocess.Popen(
        [updater_bat],
        creationflags=subprocess.CREATE_NEW_CONSOLE,  # type: ignore[attr-defined]
    )
    sys.exit(0)


def _apply_update_mac(downloaded_zip: str):
    """Spawn a .sh script that replaces the .app bundle and re-opens it."""
    from pathlib import Path

    # sys.executable lives at  MyApp.app/Contents/MacOS/myapp
    app_path = Path(sys.executable).parents[2]
    install_dir = str(app_path.parent)   # e.g. /Applications or dist/
    extract_dir = os.path.join(tempfile.gettempdir(), "neurotechgui_extraction")
    updater_sh = os.path.join(tempfile.gettempdir(), "neurotechgui_updater.sh")

    # The .app name inside the zip may differ from the currently-running
    # bundle (e.g. after a rename in CI), so we discover it dynamically.
    sh = f"""#!/bin/bash
sleep 2
rm -rf "{extract_dir}"
mkdir -p "{extract_dir}"
unzip -o "{downloaded_zip}" -d "{extract_dir}"

# Find the .app bundle inside the extraction (may be nested one level by ditto)
NEW_APP=$(find "{extract_dir}" -maxdepth 2 -name '*.app' -type d | head -n 1)
if [ -z "$NEW_APP" ]; then
    echo "Error: no .app found in update archive" >&2
    exit 1
fi

# Remove old bundle and move new one into place
rm -rf "{app_path}"
mv "$NEW_APP" "{install_dir}/"

# Determine the installed name for re-launch
INSTALLED="{install_dir}/$(basename "$NEW_APP")"

rm -rf "{extract_dir}"
rm "{downloaded_zip}"
open "$INSTALLED"
rm -- "$0"
"""
    with open(updater_sh, "w") as f:
        f.write(sh)
    os.chmod(updater_sh, 0o755)

    subprocess.Popen([updater_sh], start_new_session=True)
    sys.exit(0)


def _apply_update_linux(downloaded_path: str):
    """Spawn a .sh script that replaces the binary and restarts it."""
    current_exe = sys.executable
    updater_sh = os.path.join(tempfile.gettempdir(), "neurotechgui_updater.sh")

    sh = f"""#!/bin/bash
sleep 2
mv -f "{downloaded_path}" "{current_exe}"
chmod +x "{current_exe}"
"{current_exe}" &
rm -- "$0"
"""
    with open(updater_sh, "w") as f:
        f.write(sh)
    os.chmod(updater_sh, 0o755)

    subprocess.Popen([updater_sh], start_new_session=True)
    sys.exit(0)


def apply_update(downloaded_path: str):
    """Dispatch to the correct platform updater."""
    system = platform.system()
    if system == "Windows":
        _apply_update_windows(downloaded_path)
    elif system == "Darwin":
        _apply_update_mac(downloaded_path)
    else:
        _apply_update_linux(downloaded_path)


# ── Qt dialog ─────────────────────────────────────────────────────────────────

class UpdateDialog(QDialog):
    """
    Shown when a newer release is detected.

    Phase 1 – Prompt:  asks the user whether they want to update.
    Phase 2 – Download:  shows a progress bar while downloading.
    """

    def __init__(self, latest_version: str, download_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setMinimumWidth(420)
        self.setModal(True)

        self.download_url = download_url
        self.latest_version = latest_version
        self.downloaded_path: str | None = None

        # ── layout ──
        layout = QVBoxLayout(self)

        self.info_label = QLabel(
            f"A new version is available!\n\n"
            f"Current version:  {CURRENT_VERSION}\n"
            f"Latest version:    {latest_version}\n\n"
            f"Would you like to download and install the update?"
        )
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # buttons
        btn_layout = QHBoxLayout()
        self.update_btn = QPushButton("Update Now")
        self.update_btn.setDefault(True)
        self.update_btn.clicked.connect(self._start_download)
        btn_layout.addWidget(self.update_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)

        layout.addLayout(btn_layout)

        # download thread plumbing
        self._signals = _DownloadSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.error.connect(self._on_error)

    # ── slots ──

    def _start_download(self):
        """User clicked 'Update Now'."""
        self.update_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setVisible(True)
        self.status_label.setText("Downloading…")

        # Use a stable local filename so the updater scripts can find it
        system = platform.system()
        if system == "Darwin":
            filename = "neurotechgui_update.zip"
        elif system == "Windows":
            filename = "neurotechgui_update.exe"
        else:
            filename = "neurotechgui_update"
        dest = os.path.join(tempfile.gettempdir(), filename)

        t = threading.Thread(
            target=_download_worker,
            args=(self.download_url, dest, self._signals),
            daemon=True,
        )
        t.start()

    def _on_progress(self, pct: int):
        self.progress_bar.setValue(pct)

    def _on_finished(self, path: str):
        self.downloaded_path = path
        self.status_label.setText("Download complete. Applying update…")
        self.accept()                       # closes dialog — caller invokes apply_update

    def _on_error(self, msg: str):
        self.status_label.setText(f"Download failed: {msg}")
        self.update_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        QMessageBox.warning(self, "Update Error", f"Failed to download update:\n{msg}")


# ── convenience function called from main() ───────────────────────────────────

def prompt_update_if_available(parent=None) -> bool:
    """
    Check GitHub for a newer build and, if found, show the update dialog.

    Returns True if the app is about to restart (caller should skip further
    init), False otherwise.
    """
    latest_tag, url = check_for_updates()
    if latest_tag is None or url is None:
        return False

    dlg = UpdateDialog(latest_tag, url, parent=parent)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.downloaded_path:
        apply_update(dlg.downloaded_path)
        return True  # will not actually reach here — apply_update calls sys.exit

    return False
