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


def _asset_name_for_platform() -> str:
    """Return the release-asset filename appropriate for the running OS."""
    system = platform.system()
    if system == "Darwin":
        return "NeuroTechGUI_macOS.zip"
    elif system == "Windows":
        return "NeuroTechGUI_Windows.exe"
    else:
        return "NeuroTechGUI_Linux"


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

    target_asset = _asset_name_for_platform()
    for asset in data.get("assets", []):
        if asset.get("name") == target_asset:
            return latest_tag, asset["browser_download_url"]

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

def _apply_update_windows(downloaded_path: str):
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
    app_name = app_path.name  # e.g. "NeuroTechGUI_macOS.app"
    extract_dir = os.path.join(tempfile.gettempdir(), "neurotechgui_extraction")
    updater_sh = os.path.join(tempfile.gettempdir(), "neurotechgui_updater.sh")

    sh = f"""#!/bin/bash
sleep 2
mkdir -p "{extract_dir}"
unzip -o "{downloaded_zip}" -d "{extract_dir}"
rm -rf "{app_path}"
mv "{extract_dir}/{app_name}" "{app_path}"
rm -rf "{extract_dir}"
rm "{downloaded_zip}"
open "{app_path}"
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

        filename = _asset_name_for_platform()
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
