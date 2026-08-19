"""
zapret++ — DPI Bypass Manager
Fork of ZapretTester | Minimalist B&W UI
"""

import sys
import os
import subprocess
import threading
import time
import json
import ctypes
import winreg
import random
import psutil
import requests
import ping3
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QCheckBox,
    QTextEdit, QSystemTrayIcon, QMenu, QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import (
    QIcon, QPixmap, QColor, QPalette, QImage,
    QPainter, QBrush, QPen, QCursor, QAction, QFont
)

# ══════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════

APP_NAME = "zapret++"
APP_VERSION = "1.0.0"
WINDOW_W, WINDOW_H = 800, 600  # 4:3

# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════

def resource_path(rel: str) -> str:
    """Resolve path for both dev and PyInstaller frozen mode."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(os.path.abspath("."), rel)


def get_app_dir() -> Path:
    if hasattr(sys, 'frozen'):
        return Path(sys.executable).parent
    return Path(__file__).parent


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def apply_dark_titlebar(hwnd: int):
    try:
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
    except Exception:
        pass


# ── winws management ─────────────────────────────────────────────

def _run_bat_admin(bat_path: Path):
    """Run a .bat file hidden, then hide winws windows."""
    path_str = str(bat_path.resolve())
    work_dir = str(bat_path.parent.resolve())
    cmd = f'cmd.exe /c "{path_str}"'
    subprocess.Popen(
        cmd, cwd=work_dir, shell=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    def _hide_after_start():
        time.sleep(2)
        _hide_winws_windows()
    threading.Thread(target=_hide_after_start, daemon=True).start()


def _hide_winws_windows():
    """Hide all visible windows belonging to winws.exe."""
    try:
        user32 = ctypes.windll.user32
        winws_pids: set[int] = set()
        for p in psutil.process_iter(["name", "pid"]):
            if p.info["name"] and "winws" in p.info["name"].lower():
                winws_pids.add(p.info["pid"])
        if not winws_pids:
            return
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
        )
        def _enum_cb(hwnd, _):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in winws_pids:
                user32.ShowWindow(hwnd, 0)
                ex_style = user32.GetWindowLongW(hwnd, -20)
                new_style = (ex_style | 0x00000080) & ~0x00040000
                user32.SetWindowLongW(hwnd, -20, new_style)
            return True
        user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)
    except Exception:
        pass


def _kill_winws():
    try:
        for p in psutil.process_iter(["name", "pid"]):
            if p.info["name"] and "winws" in p.info["name"].lower():
                try:
                    psutil.Process(p.info["pid"]).terminate()
                    time.sleep(0.05)
                except Exception:
                    try:
                        psutil.Process(p.info["pid"]).kill()
                    except Exception:
                        pass
    except Exception:
        pass


def _is_winws_running() -> bool:
    try:
        for p in psutil.process_iter(["name"]):
            if p.info["name"] and "winws" in p.info["name"].lower():
                return True
    except Exception:
        pass
    return False


def _test_url(url: str) -> bool:
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        return r.status_code == 200
    except Exception:
        return False


def _make_tray_icon(connected: bool) -> QIcon:
    """Black & white tray icon."""
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#ffffff") if connected else QColor("#555555")
    p.setBrush(QBrush(color))
    p.setPen(QPen(QColor("#333"), 2))
    p.drawEllipse(4, 4, 56, 56)
    inner = QColor("#0d0d0d") if connected else QColor("#222")
    p.setBrush(QBrush(inner))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(22, 22, 20, 20)
    p.end()
    return QIcon(QPixmap.fromImage(img))


# ══════════════════════════════════════════════════════════════════
#  STYLESHEET — Windows 11 B&W minimalism
# ══════════════════════════════════════════════════════════════════

STYLE = """
* {
    font-family: 'Segoe UI', sans-serif;
    margin: 0; padding: 0;
}

QMainWindow, QWidget {
    background: #0a0a0a;
}

/* ── Panels ── */
QWidget#panelLeft {
    background: #0d0d0d;
}
QWidget#panelRight {
    background: #0a0a0a;
}
QWidget#panelDivider {
    background: #181818;
    min-width: 1px;
    max-width: 1px;
}

/* ── Tab bar ── */
QWidget#tabBar {
    background: #0f0f0f;
    border-bottom: 1px solid #1a1a1a;
}
QPushButton#tab {
    background: transparent;
    color: #555;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 12px 0;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
QPushButton#tab:hover {
    color: #888;
    background: #111;
}
QPushButton#tab[active="true"] {
    color: #e0e0e0;
    border-bottom: 2px solid #ffffff;
    background: #0a0a0a;
}

/* ── Buttons ── */
QPushButton#actionBtn {
    background: #1a1a1a;
    color: #bbb;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 500;
}
QPushButton#actionBtn:hover {
    background: #222;
    border-color: #3a3a3a;
    color: #eee;
}
QPushButton#actionBtn:pressed {
    background: #151515;
}
QPushButton#actionBtn:disabled {
    color: #444;
    border-color: #1a1a1a;
}

QPushButton#testBtn {
    background: #1a1a1a;
    color: #ccc;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#testBtn:hover {
    background: #222;
    border-color: #444;
    color: #fff;
}
QPushButton#testBtn[testing="true"] {
    background: #1a1a1a;
    color: #999;
    border-color: #333;
}

QPushButton#stopBtn {
    background: #1a1a1a;
    color: #bbb;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#stopBtn:hover {
    background: #222;
    border-color: #444;
    color: #eee;
}

QPushButton#createBtn {
    background: #ffffff;
    color: #0a0a0a;
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#createBtn:hover {
    background: #e0e0e0;
}
QPushButton#createBtn:disabled {
    background: #333;
    color: #666;
}

/* ── List widget ── */
QListWidget {
    background: #0f0f0f;
    color: #999;
    border: 1px solid #1a1a1a;
    border-radius: 6px;
    font-size: 12px;
    outline: none;
    padding: 4px;
}
QListWidget::item {
    padding: 10px 12px;
    border-radius: 4px;
    border-left: 3px solid transparent;
    margin: 1px 0;
}
QListWidget::item:hover {
    background: #141414;
    color: #bbb;
}
QListWidget::item:selected {
    background: #181818;
    color: #e0e0e0;
    border-left: 3px solid #ffffff;
}

/* ── CheckBox ── */
QCheckBox {
    color: #777;
    font-size: 12px;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid #333;
    border-radius: 3px;
    background: #141414;
}
QCheckBox::indicator:checked {
    background: #ffffff;
    border-color: #ffffff;
}
QCheckBox:hover {
    color: #aaa;
}

/* ── Console ── */
QTextEdit#console {
    background: #080808;
    color: #999;
    border: 1px solid #151515;
    border-radius: 6px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    padding: 8px;
}

/* ── ScrollBar ── */
QScrollBar:vertical {
    background: #0d0d0d;
    width: 6px;
    border: none;
    margin: 0;
    padding: 0;
}
QScrollBar::handle:vertical {
    background: #2a2a2a;
    border-radius: 3px;
    min-height: 24px;
    border: none;
}
QScrollBar::handle:vertical:hover {
    background: #3a3a3a;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    border: none;
    background: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    border: none;
}
QScrollBar:horizontal {
    height: 0;
    background: none;
    border: none;
}

/* ── Status bar ── */
QLabel#statusBar {
    background: #060606;
    color: #333;
    font-size: 11px;
    border-top: 1px solid #111;
    padding: 0 14px;
}

/* ── Section labels ── */
QLabel#sectionLbl {
    color: #555;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    background: transparent;
}

/* ── Info label ── */
QLabel#infoLbl {
    color: #555;
    font-size: 11px;
    background: transparent;
}

/* ── Tray menu ── */
QMenu {
    background: #111;
    color: #bbb;
    border: 1px solid #222;
    font-size: 12px;
}
QMenu::item {
    padding: 6px 20px;
}
QMenu::item:selected {
    background: #1a1a1a;
    color: #eee;
}
QMenu::separator {
    background: #1e1e1e;
    height: 1px;
    margin: 3px 0;
}
"""

# ══════════════════════════════════════════════════════════════════
#  POWER BUTTON (3 states: off / pending / on)
# ══════════════════════════════════════════════════════════════════

class PowerButton(QLabel):
    clicked = pyqtSignal()

    STATE_OFF = 0
    STATE_PENDING = 1
    STATE_ON = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self.STATE_OFF
        self.setFixedSize(180, 180)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pix = {self.STATE_OFF: None, self.STATE_PENDING: None, self.STATE_ON: None}
        self._load_images()
        self._refresh()

    def _load_images(self):
        mapping = {
            self.STATE_ON: "on.png",
            self.STATE_OFF: "off.png",
            self.STATE_PENDING: "pending.png",
        }
        # Try icons/ subdirectory first, then root
        for state, fname in mapping.items():
            for prefix in ("icons/", ""):
                p = resource_path(prefix + fname)
                if os.path.exists(p):
                    px = QPixmap(p).scaled(
                        180, 180,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self._pix[state] = px
                    break

    def _refresh(self):
        px = self._pix.get(self._state)
        if px:
            self.setPixmap(px)
            return
        # Fallback: draw simple circle
        img = QImage(120, 120, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = {
            self.STATE_OFF: QColor("#555"),
            self.STATE_PENDING: QColor("#888"),
            self.STATE_ON: QColor("#fff"),
        }
        c = colors.get(self._state, QColor("#555"))
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(3, 3, 114, 114)
        p.setBrush(QBrush(QColor("#0a0a0a")))
        p.drawEllipse(30, 30, 60, 60)
        pw = QPen(QColor("#0a0a0a"), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pw)
        p.drawLine(60, 30, 60, 63)
        p.end()
        self.setPixmap(QPixmap.fromImage(img))

    def set_state(self, state: int):
        if self._state != state:
            self._state = state
            self._refresh()

    @property
    def state(self):
        return self._state

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ══════════════════════════════════════════════════════════════════
#  CONNECT WORKER — background connection with pending state
# ══════════════════════════════════════════════════════════════════

class ConnectWorker(QThread):
    connected = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, bat_path: Path):
        super().__init__()
        self.bat_path = bat_path

    def run(self):
        try:
            _run_bat_admin(self.bat_path)
            # Wait for winws to actually start
            for _ in range(15):  # up to 7.5s
                time.sleep(0.5)
                if _is_winws_running():
                    self.connected.emit()
                    return
            # Timeout — check one more time
            if _is_winws_running():
                self.connected.emit()
            else:
                self.failed.emit("winws.exe did not start within timeout")
        except Exception as e:
            self.failed.emit(str(e))


# ══════════════════════════════════════════════════════════════════
#  TEST WORKER (fixed sorting: services > ping)
# ══════════════════════════════════════════════════════════════════

class TestWorker(QThread):
    log = pyqtSignal(str, str)
    result = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, bat_files: list, zapret_dir: Path):
        super().__init__()
        self.bat_files = bat_files
        self.zapret_dir = zapret_dir
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        results = []
        ping_targets = {
            "Discord": "discord.com",
            "YouTube": "youtube.com",
            "Yandex": "yandex.com",
        }

        self.log.emit("━" * 45, "dim")
        self.log.emit(f"  Testing {len(self.bat_files)} configs...", "white")
        self.log.emit("━" * 45, "dim")

        for idx, bat_file in enumerate(self.bat_files):
            if self._stop:
                break

            bat_path = self.zapret_dir / bat_file
            self.log.emit(f"\n▶ [{idx+1}/{len(self.bat_files)}] {bat_file}", "white")

            try:
                self.log.emit("  Stopping old processes...", "dim")
                _kill_winws()
                time.sleep(1)
                if self._stop:
                    break

                self.log.emit("  Starting config...", "dim")
                _run_bat_admin(bat_path)
                time.sleep(3)
                if self._stop:
                    _kill_winws()
                    break

                res = {"name": bat_file, "services": {}, "pings": {}, "avg": 0}

                # Service checks (priority!)
                for svc, url in [("YouTube", "https://www.youtube.com"),
                                 ("Discord", "https://discord.com")]:
                    if self._stop:
                        break
                    ok = _test_url(url)
                    res["services"][svc] = ok
                    mark = "✓" if ok else "✗"
                    self.log.emit(f"    {svc}: {mark}", "white" if ok else "dim")

                if self._stop:
                    _kill_winws()
                    break

                # Ping checks
                ping_vals = []
                for svc, host in ping_targets.items():
                    if self._stop:
                        break
                    try:
                        d = ping3.ping(host, timeout=3)
                        ms = int(d * 1000) if d else 999
                    except Exception:
                        ms = 999
                    res["pings"][svc] = ms
                    ping_vals.append(ms)
                    self.log.emit(f"    {svc} ping: {ms} ms", "dim")

                valid = [p for p in ping_vals if p < 999]
                res["avg"] = sum(valid) / len(valid) if valid else 999
                results.append(res)

                _kill_winws()
                time.sleep(1)

            except Exception as e:
                self.log.emit(f"  Error: {e}", "white")
                _kill_winws()

        if self._stop:
            _kill_winws()
            self.log.emit("\n⛔  Tests stopped by user.", "white")
        else:
            if results:
                self._show_top(results)
            self.log.emit("\n✅  All tests completed.", "white")

        self.finished.emit()

    def _show_top(self, results):
        # FIX: services count is the primary sort key, avg ping is secondary
        srt = sorted(
            results,
            key=lambda x: (-sum(x["services"].values()), x["avg"])
        )[:3]

        lines = ["\n" + "━" * 45, "  TOP 3 RESULTS", "━" * 45]
        for i, r in enumerate(srt, 1):
            av = sum(r["services"].values())
            total = len(r["services"])
            lines.append(f"\n{i}. {r['name']}")
            lines.append(f"   Services: {av}/{total}  |  Avg ping: {r['avg']:.0f} ms")
            for k, v in r["pings"].items():
                lines.append(f"   {k}: {v} ms")
        self.result.emit("\n".join(lines))


# ══════════════════════════════════════════════════════════════════
#  CREATE WORKER — auto-generate bat files
# ══════════════════════════════════════════════════════════════════

# Strategy templates for bat generation — comprehensive set
# Each tuple: (name_suffix, winws_tcp_args_template)
# {bin} is replaced with %BIN% at generation time
STRATEGIES = [
    # ── multisplit variants (different seqovl + patterns) ──
    ("multisplit-568-google", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=568 '
        '--dpi-desync-split-pos=1 --dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-681-google", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=681 '
        '--dpi-desync-split-pos=1 --dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-2-google", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=2 '
        '--dpi-desync-split-pos=1 --dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-568-4pda", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=568 '
        '--dpi-desync-split-pos=1 --dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_4pda_to.bin"'
    )),
    ("multisplit-681-4pda", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=681 '
        '--dpi-desync-split-pos=1 --dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_4pda_to.bin"'
    )),
    ("multisplit-1-midsld", (
        '--dpi-desync=multisplit --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-568-r8", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=568 '
        '--dpi-desync-split-pos=1 --dpi-desync-repeats=8 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-681-r11", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=681 '
        '--dpi-desync-split-pos=1 --dpi-desync-repeats=11 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── fake,fakedsplit variants (different fooling + repeats + patterns) ──
    ("fakedsplit-ts-r6-google", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-badseq-r6-google", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=badseq --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-md5sig-r6", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=md5sig --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-ts-r8-google", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-badseq-r8", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=badseq --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-ts-r11", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=11 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-badseq-r11", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=11 '
        '--dpi-desync-fooling=badseq --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-ts-r14-max", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=14 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("fakedsplit-ts-r6-stun", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}stun.bin" '
        '--dpi-desync-fake-http="{bin}tls_clienthello_max_ru.bin"'
    )),

    # ── fake,multidisorder variants (auto TLS, fooling, mods) ──
    ("multidisorder-badseq-rnd-r11", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=11 --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls=0x00000000 --dpi-desync-fake-tls=^! '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com'
    )),
    ("multidisorder-ts-r8", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=8 --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multidisorder-badseq-r8", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=8 --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multidisorder-ts-r11-max", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=11 --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_max_ru.bin" '
        '--dpi-desync-fake-http="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("multidisorder-badseq-r14-rnd", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=14 --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls=0x00000000 '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com '
        '--dpi-desync-fake-http="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("multidisorder-md5sig-r6", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=6 --dpi-desync-fooling=md5sig '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── syndata variants ──
    ("syndata-multidisorder-n4", (
        '--dpi-desync=syndata,multidisorder '
        '--dpi-desync-any-protocol=1 --dpi-desync-cutoff=n4'
    )),
    ("syndata-multidisorder-n3", (
        '--dpi-desync=syndata,multidisorder '
        '--dpi-desync-any-protocol=1 --dpi-desync-cutoff=n3'
    )),
    ("syndata-multidisorder-n2", (
        '--dpi-desync=syndata,multidisorder '
        '--dpi-desync-any-protocol=1 --dpi-desync-cutoff=n2'
    )),

    # ── pure fake variants (different repeats + fake payloads) ──
    ("fake-r6-google", (
        '--dpi-desync=fake --dpi-desync-repeats=6 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fake-r8-google", (
        '--dpi-desync=fake --dpi-desync-repeats=8 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fake-r11-google", (
        '--dpi-desync=fake --dpi-desync-repeats=11 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fake-r14-google", (
        '--dpi-desync=fake --dpi-desync-repeats=14 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fake-r6-max", (
        '--dpi-desync=fake --dpi-desync-repeats=6 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("fake-r11-max", (
        '--dpi-desync=fake --dpi-desync-repeats=11 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("fake-r6-zero", (
        '--dpi-desync=fake --dpi-desync-repeats=6 '
        '--dpi-desync-fake-tls=0x00000000'
    )),
    ("fake-r11-zero", (
        '--dpi-desync=fake --dpi-desync-repeats=11 '
        '--dpi-desync-fake-tls=0x00000000'
    )),
    ("fake-r6-stun", (
        '--dpi-desync=fake --dpi-desync-repeats=6 '
        '--dpi-desync-fake-tls="{bin}stun.bin"'
    )),

    # ── split variants (different positions) ──
    ("split-1", (
        '--dpi-desync=split --dpi-desync-split-pos=1'
    )),
    ("split-midsld", (
        '--dpi-desync=split --dpi-desync-split-pos=midsld'
    )),
    ("split-2", (
        '--dpi-desync=split --dpi-desync-split-pos=2'
    )),
    ("split2-1-midsld", (
        '--dpi-desync=split2 --dpi-desync-split-pos=1,midsld'
    )),

    # ── disorder variants ──
    ("disorder-1", (
        '--dpi-desync=disorder --dpi-desync-split-pos=1'
    )),
    ("disorder2-1-midsld", (
        '--dpi-desync=disorder2 --dpi-desync-split-pos=1,midsld'
    )),

    # ── fake+split combos ──
    ("fakesplit-r6-ts", (
        '--dpi-desync=fake,split2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakesplit-r8-badseq", (
        '--dpi-desync=fake,split2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── fake+disorder combos ──
    ("fakedisorder-r6-ts", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-r8-badseq", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-r11-md5sig", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=11 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=md5sig '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── tamper combos ──
    ("multisplit-fake-r6-ts", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=6 '
        '--dpi-desync-split-seqovl=568 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin" '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-fake-r11-badseq", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=11 '
        '--dpi-desync-split-seqovl=681 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin" '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_4pda_to.bin"'
    )),
]


def _generate_bat_content(zapret_dir: Path, strategy_args: str) -> str:
    """Generate a complete bat file content using a strategy."""
    bin_dir = zapret_dir / "bin"
    lists_dir = zapret_dir / "lists"
    bin_path = str(bin_dir).replace("/", "\\") + "\\"
    lists_path = str(lists_dir).replace("/", "\\") + "\\"

    # Replace {bin} placeholder
    tcp_args = strategy_args.replace("{bin}", "%BIN%")

    content = f'''@echo off
chcp 65001 > nul
cd /d "%~dp0"

set "BIN=%~dp0bin\\"
set "LISTS=%~dp0lists\\"
cd /d %BIN%

start "zapret: %~n0" /min "%BIN%winws.exe" --wf-tcp=80,443 --wf-udp=443,19294-19344,50000-50100 ^
--filter-udp=443 --hostlist="%LISTS%list-general.txt" --dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-fake-quic="%BIN%quic_initial_www_google_com.bin" --new ^
--filter-udp=19294-19344,50000-50100 --filter-l7=discord,stun --dpi-desync=fake --dpi-desync-fake-discord="%BIN%ACTIVE_DISCORD_UDP.bin" --dpi-desync-fake-stun="%BIN%ACTIVE_DISCORD_UDP.bin" --dpi-desync-repeats=6 --new ^
--filter-tcp=443 --hostlist="%LISTS%list-general.txt" {tcp_args} --new ^
--filter-tcp=80 --hostlist="%LISTS%list-general.txt" {tcp_args}
'''
    return content


class CreateWorker(QThread):
    log = pyqtSignal(str, str)
    success = pyqtSignal(str)  # filename of created bat
    finished = pyqtSignal()

    def __init__(self, zapret_dir: Path):
        super().__init__()
        self.zapret_dir = zapret_dir
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        self.log.emit("━" * 45, "dim")
        self.log.emit("  Route creation started", "white")
        self.log.emit("━" * 45, "dim")

        # Shuffle strategies for randomness
        strats = list(STRATEGIES)
        random.shuffle(strats)

        for idx, (name, args) in enumerate(strats):
            if self._stop:
                break

            self.log.emit(f"\n▶ Attempt {idx + 1}/{len(strats)}: {name}", "white")

            # Kill any running winws
            _kill_winws()
            time.sleep(0.5)

            # Generate bat file
            bat_content = _generate_bat_content(self.zapret_dir, args)
            tmp_bat = self.zapret_dir / f"_test_custom_{name}.bat"

            try:
                tmp_bat.write_text(bat_content, encoding="utf-8")
            except Exception as e:
                self.log.emit(f"  Error writing bat: {e}", "white")
                continue

            # Run it
            self.log.emit("  Starting winws...", "dim")
            try:
                _run_bat_admin(tmp_bat)
            except Exception as e:
                self.log.emit(f"  Error running bat: {e}", "white")
                try:
                    tmp_bat.unlink()
                except Exception:
                    pass
                continue

            # Wait for winws to start
            time.sleep(4)

            if self._stop:
                _kill_winws()
                try:
                    tmp_bat.unlink()
                except Exception:
                    pass
                break

            if not _is_winws_running():
                self.log.emit("  winws did not start", "dim")
                try:
                    tmp_bat.unlink()
                except Exception:
                    pass
                continue

            # Test connectivity
            self.log.emit("  Testing Discord...", "dim")
            discord_ok = _test_url("https://discord.com")
            self.log.emit(f"    Discord: {'✓' if discord_ok else '✗'}", "white" if discord_ok else "dim")

            if self._stop:
                _kill_winws()
                try:
                    tmp_bat.unlink()
                except Exception:
                    pass
                break

            self.log.emit("  Testing YouTube...", "dim")
            youtube_ok = _test_url("https://www.youtube.com")
            self.log.emit(f"    YouTube: {'✓' if youtube_ok else '✗'}", "white" if youtube_ok else "dim")

            _kill_winws()
            time.sleep(0.5)

            if discord_ok and youtube_ok:
                # Success! Save the bat file permanently
                custom_num = 1
                while (self.zapret_dir / f"custom_{custom_num}.bat").exists():
                    custom_num += 1
                final_name = f"custom_{custom_num}.bat"
                final_path = self.zapret_dir / final_name

                try:
                    tmp_bat.rename(final_path)
                except Exception:
                    try:
                        final_path.write_text(bat_content, encoding="utf-8")
                        tmp_bat.unlink()
                    except Exception:
                        pass

                self.log.emit(f"\n✅  Route created: {final_name}", "white")
                self.log.emit(f"  Strategy: {name}", "dim")
                self.success.emit(final_name)
                self.finished.emit()
                return
            else:
                # Clean up temp file
                try:
                    tmp_bat.unlink()
                except Exception:
                    pass
                self.log.emit("  ✗ No access, trying next...", "dim")

        _kill_winws()

        if self._stop:
            self.log.emit("\n⛔  Route creation stopped.", "white")
        else:
            self.log.emit("\n✗  All strategies exhausted. No working route found.", "white")

        self.finished.emit()


# ══════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet(STYLE)

        # Window icon
        for ico_path in ("icons/ico.ico", "icons/ico.png", "ico.ico"):
            p = resource_path(ico_path)
            if os.path.exists(p):
                self.setWindowIcon(QIcon(p))
                break

        # State
        self._connected = False
        self._bat_files: list[str] = []
        self._current_bat: str | None = None
        self._test_worker: TestWorker | None = None
        self._create_worker: CreateWorker | None = None
        self._connect_worker: ConnectWorker | None = None
        self._dark_applied = False

        # Paths
        self._app_dir = get_app_dir()
        self._zapret_dir = self._find_zapret_dir()
        self._cfg_file = self._app_dir / "zapret_settings.json"

        self._auto_connect = False
        self._auto_start = False
        self._load_settings()

        self._build_ui()
        self._load_bat_files()
        self._setup_tray()

        if _is_winws_running():
            self._connected = True
            self._power_btn.set_state(PowerButton.STATE_ON)
            self._sync_ui()
            self._log("Detected active winws process.", "dim")

        if self._auto_connect and self._current_bat:
            QTimer.singleShot(1000, self._connect)

    # ── Zapret dir detection (reworked) ───────────────────────────

    def _find_zapret_dir(self) -> Path:
        """
        Find zapret directory: any folder next to exe containing
        bat files AND bin/winws.exe (or winws.exe in root).
        """
        app_dir = self._app_dir

        for item in sorted(app_dir.iterdir()):
            if not item.is_dir():
                continue
            # Skip known non-zapret dirs
            if item.name.lower() in ("icons", "__pycache__", "build", "dist",
                                      ".git", "venv", ".venv"):
                continue

            has_bats = bool(list(item.glob("*.bat")))
            has_winws = (
                (item / "bin" / "winws.exe").exists() or
                (item / "winws.exe").exists()
            )

            if has_bats and has_winws:
                return item

        # Fallback: try old-style zapret/ subfolder
        base = app_dir / "zapret"
        if base.exists():
            if list(base.glob("*.bat")):
                return base
            subdirs = [d for d in base.iterdir() if d.is_dir()]
            if len(subdirs) == 1:
                return subdirs[0]

        # Create default
        base.mkdir(exist_ok=True)
        return base

    # ── Settings ──────────────────────────────────────────────────

    def _load_settings(self):
        if self._cfg_file.exists():
            try:
                d = json.loads(self._cfg_file.read_text(encoding="utf-8"))
                self._current_bat = d.get("last_bat")
                self._auto_connect = d.get("auto_connect", False)
                self._auto_start = d.get("auto_start", False)
                self._apply_auto_start()
            except Exception:
                pass

    def _save_settings(self):
        try:
            self._cfg_file.write_text(
                json.dumps({
                    "last_bat": self._current_bat,
                    "auto_connect": self._auto_connect,
                    "auto_start": self._auto_start,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _apply_auto_start(self):
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        name = APP_NAME
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            )
            if self._auto_start:
                exe = sys.executable if hasattr(sys, "frozen") else sys.argv[0]
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    # ── UI Build ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        vlay = QVBoxLayout(root)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # Tab bar
        tab_bar = QWidget()
        tab_bar.setObjectName("tabBar")
        tab_bar.setFixedHeight(46)
        tb = QHBoxLayout(tab_bar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(0)

        self._tab_connect = self._mk_tab("Connect")
        self._tab_create = self._mk_tab("Create")
        self._tab_settings = self._mk_tab("Settings")

        self._tab_connect.clicked.connect(lambda: self._switch(0))
        self._tab_create.clicked.connect(lambda: self._switch(1))
        self._tab_settings.clicked.connect(lambda: self._switch(2))

        tb.addWidget(self._tab_connect)
        tb.addWidget(self._tab_create)
        tb.addWidget(self._tab_settings)
        vlay.addWidget(tab_bar)

        # Pages
        self._pg_connect = self._build_connect_page()
        self._pg_create = self._build_create_page()
        self._pg_settings = self._build_settings_page()
        vlay.addWidget(self._pg_connect, 1)
        vlay.addWidget(self._pg_create, 1)
        vlay.addWidget(self._pg_settings, 1)

        # Status bar
        self._status_bar = QLabel()
        self._status_bar.setObjectName("statusBar")
        self._status_bar.setFixedHeight(24)
        vlay.addWidget(self._status_bar)

        self._switch(0)
        self._refresh_statusbar()

    def _mk_tab(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("tab")
        b.setProperty("active", "false")
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        return b

    def _switch(self, idx: int):
        self._pg_connect.setVisible(idx == 0)
        self._pg_create.setVisible(idx == 1)
        self._pg_settings.setVisible(idx == 2)
        for i, b in enumerate([self._tab_connect, self._tab_create, self._tab_settings]):
            b.setProperty("active", "true" if i == idx else "false")
            b.style().unpolish(b)
            b.style().polish(b)

    # ══════════════════════════════════════════════════════════════
    #  CONNECT PAGE — list left, power button right
    # ══════════════════════════════════════════════════════════════

    def _build_connect_page(self) -> QWidget:
        w = QWidget()
        hlay = QHBoxLayout(w)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)

        # ── Left panel: config list ──
        left = QWidget()
        left.setObjectName("panelLeft")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(14, 14, 14, 14)
        left_lay.setSpacing(8)

        lbl = QLabel("CONFIGS")
        lbl.setObjectName("sectionLbl")
        left_lay.addWidget(lbl)

        self._config_list = QListWidget()
        self._config_list.currentItemChanged.connect(self._on_list_changed)
        left_lay.addWidget(self._config_list, 1)

        hlay.addWidget(left, 38)

        # ── Right panel: power button + status ──
        right = QWidget()
        right.setObjectName("panelRight")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(24, 20, 24, 20)
        right_lay.setSpacing(0)
        right_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        right_lay.addStretch(2)

        # Power button
        self._power_btn = PowerButton()
        self._power_btn.clicked.connect(self._toggle_connection)
        right_lay.addWidget(self._power_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        right_lay.addSpacing(16)

        # Status label
        self._status_lbl = QLabel("Disconnected")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            "color: #777; font-size: 16px; font-weight: 600; background: transparent;"
        )
        right_lay.addWidget(self._status_lbl)
        right_lay.addSpacing(8)

        # Selected config label
        self._selected_lbl = QLabel("")
        self._selected_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._selected_lbl.setStyleSheet(
            "color: #444; font-size: 11px; background: transparent;"
        )
        right_lay.addWidget(self._selected_lbl)

        right_lay.addStretch(2)

        # Options at bottom
        opts_w = QWidget()
        opts_lay = QVBoxLayout(opts_w)
        opts_lay.setContentsMargins(0, 0, 0, 0)
        opts_lay.setSpacing(6)

        opt_lbl = QLabel("OPTIONS")
        opt_lbl.setObjectName("sectionLbl")
        opts_lay.addWidget(opt_lbl)

        chk_row = QHBoxLayout()
        chk_row.setSpacing(20)
        self._chk_autostart = QCheckBox("Autostart")
        self._chk_autostart.setChecked(self._auto_start)
        self._chk_autostart.toggled.connect(self._on_autostart_changed)

        self._chk_autoconnect = QCheckBox("Auto-connect")
        self._chk_autoconnect.setChecked(self._auto_connect)
        self._chk_autoconnect.toggled.connect(self._on_autoconnect_changed)

        chk_row.addWidget(self._chk_autostart)
        chk_row.addWidget(self._chk_autoconnect)
        chk_row.addStretch()
        opts_lay.addLayout(chk_row)

        right_lay.addWidget(opts_w)

        hlay.addWidget(right, 62)
        return w

    # ══════════════════════════════════════════════════════════════
    #  CREATE PAGE — button left, log right
    # ══════════════════════════════════════════════════════════════

    def _build_create_page(self) -> QWidget:
        w = QWidget()
        hlay = QHBoxLayout(w)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)

        # ── Left panel: buttons ──
        left = QWidget()
        left.setObjectName("panelLeft")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(16, 20, 16, 20)
        left_lay.setSpacing(10)

        lbl = QLabel("ROUTE BUILDER")
        lbl.setObjectName("sectionLbl")
        left_lay.addWidget(lbl)
        left_lay.addSpacing(8)

        self._btn_create_route = QPushButton("Create Route")
        self._btn_create_route.setObjectName("createBtn")
        self._btn_create_route.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_create_route.clicked.connect(self._start_create)
        left_lay.addWidget(self._btn_create_route)

        self._btn_create_stop = QPushButton("Stop")
        self._btn_create_stop.setObjectName("stopBtn")
        self._btn_create_stop.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_create_stop.clicked.connect(self._stop_create)
        self._btn_create_stop.setVisible(False)
        left_lay.addWidget(self._btn_create_stop)

        left_lay.addStretch()

        # Info label
        info_lbl = QLabel(
            "Automatically generates and\n"
            "tests DPI bypass configs\n"
            "for your connection."
        )
        info_lbl.setObjectName("infoLbl")
        info_lbl.setWordWrap(True)
        left_lay.addWidget(info_lbl)

        hlay.addWidget(left, 35)

        # ── Right panel: log ──
        right = QWidget()
        right.setObjectName("panelRight")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(14, 14, 14, 14)
        right_lay.setSpacing(6)

        row_lbl = QHBoxLayout()
        con_lbl = QLabel("OUTPUT")
        con_lbl.setObjectName("sectionLbl")
        self._btn_create_clear = QPushButton("Clear")
        self._btn_create_clear.setObjectName("actionBtn")

        self._btn_create_clear.clicked.connect(lambda: self._create_console.clear())
        row_lbl.addWidget(con_lbl)
        row_lbl.addStretch()
        row_lbl.addWidget(self._btn_create_clear)
        right_lay.addLayout(row_lbl)

        self._create_console = QTextEdit()
        self._create_console.setObjectName("console")
        self._create_console.setReadOnly(True)
        self._create_console.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        right_lay.addWidget(self._create_console, 1)

        hlay.addWidget(right, 65)
        return w

    # ══════════════════════════════════════════════════════════════
    #  SETTINGS PAGE — buttons left, console right
    # ══════════════════════════════════════════════════════════════

    def _build_settings_page(self) -> QWidget:
        w = QWidget()
        hlay = QHBoxLayout(w)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)

        # ── Left panel: buttons + results ──
        left = QWidget()
        left.setObjectName("panelLeft")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(16, 14, 16, 14)
        left_lay.setSpacing(8)

        act_lbl = QLabel("ACTIONS")
        act_lbl.setObjectName("sectionLbl")
        left_lay.addWidget(act_lbl)
        left_lay.addSpacing(4)

        self._btn_service = QPushButton("Run service.bat")
        self._btn_service.setObjectName("actionBtn")
        self._btn_service.clicked.connect(self._run_service)
        left_lay.addWidget(self._btn_service)

        self._btn_test = QPushButton("Test All Configs")
        self._btn_test.setObjectName("testBtn")
        self._btn_test.setProperty("testing", "false")
        self._btn_test.clicked.connect(self._toggle_testing)
        left_lay.addWidget(self._btn_test)

        self._btn_clear = QPushButton("Clear Log")
        self._btn_clear.setObjectName("actionBtn")
        
        self._btn_clear.clicked.connect(self._console_clear)
        left_lay.addWidget(self._btn_clear)

        left_lay.addSpacing(10)

        res_lbl = QLabel("RESULTS")
        res_lbl.setObjectName("sectionLbl")
        left_lay.addWidget(res_lbl)

        self._results = QTextEdit()
        self._results.setObjectName("console")
        self._results.setReadOnly(True)
        left_lay.addWidget(self._results, 1)

        hlay.addWidget(left, 35)

        # ── Right panel: console ──
        right = QWidget()
        right.setObjectName("panelRight")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(14, 14, 14, 14)
        right_lay.setSpacing(6)

        row = QHBoxLayout()
        c_lbl = QLabel("CONSOLE")
        c_lbl.setObjectName("sectionLbl")
        row.addWidget(c_lbl)
        row.addStretch()
        right_lay.addLayout(row)

        self._console = QTextEdit()
        self._console.setObjectName("console")
        self._console.setReadOnly(True)
        self._console.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        right_lay.addWidget(self._console, 1)

        hlay.addWidget(right, 65)
        return w

    # ── Tray ──────────────────────────────────────────────────────

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip(APP_NAME)
        self._tray.activated.connect(self._on_tray_activated)

        m = QMenu()
        m.setStyleSheet(STYLE)
        self._act_open = QAction("Open", self)
        self._act_conn = QAction("Connect", self)
        self._act_disc = QAction("Disconnect", self)
        self._act_exit = QAction("Exit", self)
        self._act_open.triggered.connect(self._restore)
        self._act_conn.triggered.connect(self._connect)
        self._act_disc.triggered.connect(self._disconnect)
        self._act_exit.triggered.connect(self._exit_app)
        m.addAction(self._act_open)
        m.addSeparator()
        m.addAction(self._act_conn)
        m.addAction(self._act_disc)
        m.addSeparator()
        m.addAction(self._act_exit)
        self._tray.setContextMenu(m)
        self._tray.show()
        self._refresh_tray()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore()

    def _restore(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _exit_app(self):
        self._disconnect()
        self._tray.hide()
        QApplication.quit()

    def _refresh_tray(self):
        self._act_conn.setVisible(not self._connected)
        self._act_disc.setVisible(self._connected)
        self._tray.setIcon(_make_tray_icon(self._connected))

    # ── Window events ─────────────────────────────────────────────

    def showEvent(self, e):
        super().showEvent(e)
        if not self._dark_applied:
            self._dark_applied = True
            try:
                apply_dark_titlebar(int(self.winId()))
            except Exception:
                pass

    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self._tray.showMessage(
            APP_NAME,
            "Minimized to tray. Click the icon to restore.",
            QSystemTrayIcon.MessageIcon.Information, 2000
        )

    # ── BAT files ─────────────────────────────────────────────────

    def _load_bat_files(self):
        self._bat_files = []
        if self._zapret_dir.exists():
            for f in sorted(self._zapret_dir.glob("*.bat")):
                name_lower = f.name.lower()
                # Skip service.bat and temp test files
                if name_lower == "service.bat" or name_lower.startswith("_test_custom_"):
                    continue
                self._bat_files.append(f.name)

        self._config_list.blockSignals(True)
        self._config_list.clear()
        for fname in self._bat_files:
            item = QListWidgetItem(fname)
            self._config_list.addItem(item)

        # Restore selection
        if self._current_bat and self._current_bat in self._bat_files:
            idx = self._bat_files.index(self._current_bat)
            self._config_list.setCurrentRow(idx)
        elif self._bat_files:
            self._current_bat = self._bat_files[0]
            self._config_list.setCurrentRow(0)

        self._config_list.blockSignals(False)
        self._update_selected_label()

    def _on_list_changed(self, current, previous):
        if current:
            text = current.text()
            old_bat = self._current_bat
            self._current_bat = text
            self._save_settings()
            self._update_selected_label()
            self._log(f"Selected: {text}", "dim")
            # Auto-reconnect if connected and config changed
            if self._connected and old_bat != text:
                self._log(f"Switching from {old_bat} to {text}...", "dim")
                self._disconnect()
                QTimer.singleShot(500, self._connect)

    def _update_selected_label(self):
        if self._current_bat:
            # Show clean name without .bat extension
            name = self._current_bat.replace(".bat", "")
            self._selected_lbl.setText(name)
        else:
            self._selected_lbl.setText("No config selected")

    # ── Connection (with pending state) ───────────────────────────

    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        elif self._power_btn.state != PowerButton.STATE_PENDING:
            self._connect()

    def _connect(self):
        if not self._current_bat:
            self._set_status("No config selected", "#777")
            return
        bat = self._zapret_dir / self._current_bat
        if not bat.exists():
            self._set_status("File not found", "#777")
            self._log(f"Not found: {bat}", "white")
            return

        # Set pending state
        self._power_btn.set_state(PowerButton.STATE_PENDING)
        self._set_status("Connecting...", "#888")
        self._log(f"Connecting: {self._current_bat}...", "dim")

        # Run in background thread
        self._connect_worker = ConnectWorker(bat)
        self._connect_worker.connected.connect(self._on_connected)
        self._connect_worker.failed.connect(self._on_connect_failed)
        self._connect_worker.start()

    def _on_connected(self):
        self._connected = True
        self._power_btn.set_state(PowerButton.STATE_ON)
        self._sync_ui()
        self._log(f"Connected: {self._current_bat}", "white")

    def _on_connect_failed(self, err: str):
        self._power_btn.set_state(PowerButton.STATE_OFF)
        self._connected = False
        self._set_status("Connection failed", "#777")
        self._sync_ui()
        self._log(f"Error: {err}", "white")

    def _disconnect(self):
        _kill_winws()
        self._connected = False
        self._power_btn.set_state(PowerButton.STATE_OFF)
        self._sync_ui()
        self._log("Disconnected.", "dim")

    def _sync_ui(self):
        self._set_status(
            "Connected" if self._connected else "Disconnected",
            "#e0e0e0" if self._connected else "#777"
        )
        self._refresh_tray()
        self._refresh_statusbar()

    def _set_status(self, text: str, color: str):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color: {color}; font-size: 16px; font-weight: 600; background: transparent;"
        )

    def _refresh_statusbar(self):
        dot = "●" if self._connected else "○"
        state = "Connected" if self._connected else "Disconnected"
        col = "#888" if self._connected else "#333"
        admin = "Admin ✓" if is_admin() else "No admin"
        self._status_bar.setText(f"  {dot} {state}   ·   {admin}   ·   {APP_NAME} v{APP_VERSION}")
        self._status_bar.setStyleSheet(
            f"background: #060606; color: {col}; font-size: 11px; "
            f"border-top: 1px solid #111; padding: 0 14px;"
        )

    # ── Settings actions ──────────────────────────────────────────

    def _on_autostart_changed(self, v: bool):
        self._auto_start = v
        self._apply_auto_start()
        self._save_settings()
        self._log(f"Autostart {'enabled' if v else 'disabled'}", "dim")

    def _on_autoconnect_changed(self, v: bool):
        self._auto_connect = v
        self._save_settings()
        self._log(f"Auto-connect {'enabled' if v else 'disabled'}", "dim")

    def _console_clear(self):
        self._console.clear()

    def _run_service(self):
        svc = self._zapret_dir / "service.bat"
        if not svc.exists():
            self._log("ERROR: service.bat not found!", "white")
            return
        self._log("Starting service.bat...", "dim")

        def _run():
            try:
                p = subprocess.Popen(
                    ["cmd.exe", "/c", str(svc.resolve())],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="ignore",
                    cwd=str(svc.parent.resolve()),
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                for line in p.stdout:
                    if line.strip():
                        self._log(line.strip(), "dim")
                p.wait()
                self._log("service.bat completed.", "white")
            except Exception as e:
                self._log(f"Error: {e}", "white")

        threading.Thread(target=_run, daemon=True).start()

    # ── Testing ───────────────────────────────────────────────────

    def _toggle_testing(self):
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.stop()
            self._btn_test.setEnabled(False)
            self._btn_test.setText("Stopping...")
        else:
            self._start_testing()

    def _start_testing(self):
        if not self._bat_files:
            self._log("No .bat files found.", "white")
            return

        self._results.clear()
        self._btn_test.setText("⛔  Stop Testing")
        self._btn_test.setProperty("testing", "true")
        self._btn_test.style().unpolish(self._btn_test)
        self._btn_test.style().polish(self._btn_test)

        self._test_worker = TestWorker(self._bat_files, self._zapret_dir)
        self._test_worker.log.connect(self._log)
        self._test_worker.result.connect(self._results.setPlainText)
        self._test_worker.finished.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self):
        self._btn_test.setText("Test All Configs")
        self._btn_test.setEnabled(True)
        self._btn_test.setProperty("testing", "false")
        self._btn_test.style().unpolish(self._btn_test)
        self._btn_test.style().polish(self._btn_test)

    # ── Create route ──────────────────────────────────────────────

    def _start_create(self):
        if not self._zapret_dir.exists():
            self._create_log("No zapret directory found!", "white")
            return

        # Check for winws.exe
        has_winws = (
            (self._zapret_dir / "bin" / "winws.exe").exists() or
            (self._zapret_dir / "winws.exe").exists()
        )
        if not has_winws:
            self._create_log("winws.exe not found in zapret directory!", "white")
            return

        self._btn_create_route.setEnabled(False)
        self._btn_create_stop.setVisible(True)

        self._create_worker = CreateWorker(self._zapret_dir)
        self._create_worker.log.connect(self._create_log)
        self._create_worker.success.connect(self._on_create_success)
        self._create_worker.finished.connect(self._on_create_done)
        self._create_worker.start()

    def _stop_create(self):
        if self._create_worker and self._create_worker.isRunning():
            self._create_worker.stop()
            self._btn_create_stop.setEnabled(False)
            self._btn_create_stop.setText("Stopping...")

    def _on_create_success(self, filename: str):
        # Reload bat list so the new config appears
        self._load_bat_files()

    def _on_create_done(self):
        self._btn_create_route.setEnabled(True)
        self._btn_create_stop.setVisible(False)
        self._btn_create_stop.setEnabled(True)
        self._btn_create_stop.setText("Stop")

    def _create_log(self, text: str, color: str = "white"):
        COLORS = {
            "white": "#bbb",
            "dim": "#555",
        }
        hx = COLORS.get(color, "#bbb")
        ts = time.strftime("%H:%M:%S")
        self._create_console.append(
            f'<span style="color:#222;">[{ts}]</span> '
            f'<span style="color:{hx};">{text}</span>'
        )
        sb = self._create_console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Logging ───────────────────────────────────────────────────

    def _log(self, text: str, color: str = "white"):
        COLORS = {
            "white": "#bbb",
            "dim": "#555",
        }
        hx = COLORS.get(color, "#bbb")
        ts = time.strftime("%H:%M:%S")
        self._console.append(
            f'<span style="color:#222;">[{ts}]</span> '
            f'<span style="color:{hx};">{text}</span>'
        )
        sb = self._console.verticalScrollBar()
        sb.setValue(sb.maximum())


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(10, 10, 10))
    p.setColor(QPalette.ColorRole.WindowText, QColor(187, 187, 187))
    p.setColor(QPalette.ColorRole.Base, QColor(8, 8, 8))
    p.setColor(QPalette.ColorRole.Text, QColor(187, 187, 187))
    app.setPalette(p)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
