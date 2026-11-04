"""
zapret++ — DPI Bypass Manager
Fork of ZapretTester | Minimalist B&W UI
"""
from collections import Counter
import ctypes
import json
import os
import queue
import random
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path
import shutil
import urllib.request
from urllib.parse import urlparse

import psutil
from PyQt6.QtCore import QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QIcon,
    QImage,
    QMovie,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpacerItem,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink
    HAS_MULTIMEDIA = True
except Exception:
    HAS_MULTIMEDIA = False
from autostart import (
    disable_autostart,
    enable_autostart,
    get_executable_path,
    is_autostart_enabled,
)
from tg_proxy_service import (
    CfProxyTestWorker,
    CfWorkerTestWorker,
    TgProxyManager,
    coerce_domain_list,
    default_tg_config,
    validate_tg_settings,
)

# ══════════════════════════════════════════════════════════════════
#  CONSTANTS
# ══════════════════════════════════════════════════════════════════

APP_NAME = "zapret++"
APP_VERSION = "1.0.6"
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


def get_settings_dir(app_dir: Path | None = None) -> Path:
    if app_dir is None:
        app_dir = get_app_dir()
    s_dir = app_dir / "settings"
    s_dir.mkdir(parents=True, exist_ok=True)
    return s_dir


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def apply_dark_titlebar(hwnd: int, dark: bool = True):
    try:
        val = ctypes.c_int(1 if dark else 0)
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


_TEST_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _probe(url: str, timeout: float = 6.0, retries: int = 2, port_pool=None):
    """
    Реальная проверка DPI-обхода: сырой TCP-коннект + TLS handshake
    с нужным SNI, затем минимальный HTTP-запрос напрямую по сокету.

    Успех = получен ЛЮБОЙ валидный HTTP-ответ (даже 403/404/редирект).
    Если DPI блокирует — соединение оборвётся ДО этого момента
    (RST на ClientHello / timeout). Сам факт полученного HTTP-ответа
    уже доказывает, что обход сработал — status_code == 200 тут
    неверный критерий, сайт может отдать что угодно вне зависимости
    от DPI (редирект, анти-бот, гео-страницу).

    Возвращает (ok, latency_ms, resolved_ip):
      - latency_ms — реальное время TCP+TLS хендшейка до самого
        тестируемого сервиса (как меряют VPN-клиенты вроде v2rayN/Happ),
        а не ICMP-пинг до постороннего хоста.
      - resolved_ip — IP, в который зарезолвился хост (для диагностики
        DNS-подмены/throttling, если сервис стабильно недоступен).
    """
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    if not host:
        return False, None, None

    resolved_ip = None
    try:
        resolved_ip = socket.gethostbyname(host)
    except Exception:
        pass  # DNS не резолвится вообще — тоже важный диагностический факт

    for attempt in range(retries):
        start = time.perf_counter()
        try:
            with _open_connection(host, port, timeout, port_pool) as raw:
                if parsed.scheme == "https":
                    ctx = ssl.create_default_context()
                    with ctx.wrap_socket(raw, server_hostname=host) as sock:
                        if _http_probe_ok(sock, host, path, timeout):
                            elapsed_ms = int((time.perf_counter() - start) * 1000)
                            return True, elapsed_ms, resolved_ip
                else:
                    if _http_probe_ok(raw, host, path, timeout):
                        elapsed_ms = int((time.perf_counter() - start) * 1000)
                        return True, elapsed_ms, resolved_ip
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(0.5)
    return False, None, resolved_ip


def _http_probe_ok(sock, host: str, path: str, timeout: float) -> bool:
    try:
        sock.settimeout(timeout)
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: {_TEST_UA}\r\n"
            f"Accept: */*\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        sock.sendall(req)
        data = sock.recv(512)
        return data[:5] == b"HTTP/"
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
#  PARALLEL ISOLATED TESTING
#
#  Идея изоляции: каждый слот (поток) получает СВОЙ диапазон
#  локальных TCP-портов. Его winws запускается с --wf-raw, который
#  перехватывает ТОЛЬКО пакеты с этими локальными портами, а проба
#  биндится на исходящий порт из этого диапазона. Поэтому трафик
#  слота A никогда не попадает в фильтр слота B (и наоборот).
# ══════════════════════════════════════════════════════════════════

PARALLEL_SLOTS = 3
_ISO_PORT_BASE = 42000   # ниже динамического диапазона Windows (49152+)
_ISO_PORT_SPAN = 1000


class _PortPool:
    """Циклический выдатчик локальных портов (чтобы не бить в TIME_WAIT)."""

    def __init__(self, lo: int, hi: int):
        self.lo, self.hi = lo, hi
        self._next = lo
        self._lock = threading.Lock()

    @property
    def range(self) -> tuple[int, int]:
        return self.lo, self.hi

    def next_port(self) -> int:
        with self._lock:
            p = self._next
            self._next = self.lo if p >= self.hi else p + 1
            return p


def _make_slot_pools(n: int = PARALLEL_SLOTS) -> list:
    return [
        _PortPool(_ISO_PORT_BASE + i * _ISO_PORT_SPAN,
                  _ISO_PORT_BASE + (i + 1) * _ISO_PORT_SPAN - 1)
        for i in range(n)
    ]


def _open_connection(host: str, port: int, timeout: float, port_pool=None):
    """TCP-коннект; если задан port_pool — с локального порта из его диапазона."""
    if port_pool is None:
        return socket.create_connection((host, port), timeout=timeout)
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    last_exc: Exception = OSError(f"cannot connect to {host}:{port}")
    for family, stype, proto, _, addr in infos:
        for _ in range(50):
            s = socket.socket(family, stype, proto)
            try:
                s.bind(("", port_pool.next_port()))
            except OSError as e:      # порт занят — берём следующий
                s.close()
                last_exc = e
                continue
            try:
                s.settimeout(timeout)
                s.connect(addr)
                return s
            except OSError as e:      # реальная сетевая ошибка — следующий адрес
                s.close()
                last_exc = e
                break
    raise last_exc


def _find_winws_exe(zapret_dir: Path):
    for p in (zapret_dir / "bin" / "winws.exe", zapret_dir / "winws.exe"):
        if p.exists():
            return p
    return None


def _winws_supports_wf_raw(exe: Path) -> bool:
    try:
        r = subprocess.run(
            [str(exe), "--help"], capture_output=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "--wf-raw" in (r.stdout + r.stderr).decode("utf-8", "ignore")
    except Exception:
        return False


def _tokenize_cmdline(s: str) -> list:
    """Разбор командной строки с кавычками (кавычки удаляются)."""
    tokens, cur, in_q, has = [], [], False, False
    for ch in s:
        if ch == '"':
            in_q = not in_q
            has = True
            continue
        if ch.isspace() and not in_q:
            if has:
                tokens.append("".join(cur))
                cur, has = [], False
            continue
        cur.append(ch)
        has = True
    if has:
        tokens.append("".join(cur))
    return tokens


def _parse_bat_winws_args(bat_path: Path):
    """
    Достаёт аргументы winws из .bat (с раскрытием %BIN%, %LISTS%, %~dp0, set-переменных)
    и вырезает все --wf-* (фильтр WinDivert подставим свой).
    Возвращает list[str] или None, если bat нетипичный (тогда тест пойдёт старым способом).
    """
    try:
        text = bat_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    text = re.sub(r"\^[ \t]*\r?\n", " ", text)          # склейка строк с ^
    bat_dir = str(bat_path.parent.resolve()) + "\\"
    env: dict = {}
    cmd_lines: list = []

    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if not s or low.startswith(("rem ", "::", "echo", "taskkill", "tasklist")):
            continue
        m = re.match(r'(?i)^set\s+"?([^=\s"]+)=(.*?)"?\s*$', s)
        if m:
            env[m.group(1).lower()] = m.group(2)
            continue
        if "winws.exe" in low:
            rest = s[low.index("winws.exe") + len("winws.exe"):]
            if " --" in rest:
                cmd_lines.append(rest.lstrip('"'))

    if len(cmd_lines) != 1:        # 0 или несколько winws в одном bat — не поддерживаем
        return None

    def expand(t: str):
        for _ in range(6):
            t = t.replace("%~dp0", bat_dir).replace("%~n0", bat_path.stem)

            def rep(m):
                name = m.group(1).lower()
                if name in env:
                    return env[name]
                if name == "bin":
                    return bat_dir + "bin\\"
                if name == "lists":
                    return bat_dir + "lists\\"
                if name.startswith("gamefilter"):
                    return "12"
                raise KeyError(name)

            try:
                new = re.sub(r"%([A-Za-z0-9_]+)%", rep, t)
            except KeyError:
                return None
            if new == t:
                break
            t = new
        return None if re.search(r"%[A-Za-z~]", t) else t

    expanded = expand(cmd_lines[0])
    if expanded is None:
        return None
    args = [a for a in _tokenize_cmdline(expanded) if not a.lower().startswith("--wf-")]
    return args or None


def _iso_filter(lo: int, hi: int) -> str:
    """WinDivert-фильтр: только TCP/443 с локальными портами слота."""
    out = f"(outbound and tcp.DstPort==443 and tcp.SrcPort>={lo} and tcp.SrcPort<={hi})"
    inn = f"(inbound and tcp.SrcPort==443 and tcp.DstPort>={lo} and tcp.DstPort<={hi})"
    return f"!impostor and !loopback and ({out} or {inn})"


class _IsolatedWinws:
    """Один процесс winws со своим фильтром; убивается только он сам."""

    def __init__(self, exe: Path, cwd: Path, args: list, port_range: tuple):
        self.cmd = [str(exe), f"--wf-raw={_iso_filter(*port_range)}"] + args
        self.cwd = str(cwd)
        self.proc = None

    def start(self, settle: float = 1.0) -> bool:
        self.proc = subprocess.Popen(
            self.cmd, cwd=self.cwd,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(settle)           # дать WinDivert открыться; невалидные опции => процесс уже завершился
        return self.proc.poll() is None

    def stop(self):
        p = self.proc
        if not p:
            return
        try:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=2)
        except Exception:
            pass


def _test_bat_isolated(bat_path: Path, exe: Path, pool: _PortPool, services: list,
                       stop_check, timeout: float, retries: int, stop_on_fail: bool = False):
    """
    Тест одного конфига в изолированном слоте.
    Возвращает (state, results): state ∈ ok | unparsable | start_failed | stopped,
    results = [(svc, ok, latency_ms, ip), ...]
    """
    args = _parse_bat_winws_args(bat_path)
    if args is None:
        return "unparsable", []
    bin_dir = exe.parent
    inst = _IsolatedWinws(exe, bin_dir, args, pool.range)
    try:
        if stop_check():
            return "stopped", []
        if not inst.start():
            return "start_failed", []
        results = []
        for svc, url in services:
            if stop_check():
                return "stopped", results
            ok, lat, ip = _probe(url, timeout=timeout, retries=retries, port_pool=pool)
            results.append((svc, ok, lat, ip))
            if stop_on_fail and not ok:
                break
        return "ok", results
    finally:
        inst.stop()


def _test_bat_legacy(bat_path: Path, services: list, stop_check, timeout: float,
                     retries: int, stop_on_fail: bool = False):
    """Старый способ (через сам bat, убивает ВСЕ winws) — только для последовательного режима."""
    _kill_winws()
    time.sleep(0.5)
    try:
        if stop_check():
            return "stopped", []
        _run_bat_admin(bat_path)
        for _ in range(40):
            if _is_winws_running():
                break
            time.sleep(0.15)
        time.sleep(0.5)
        if not _is_winws_running():
            return "start_failed", []
        results = []
        for svc, url in services:
            if stop_check():
                return "stopped", results
            ok, lat, ip = _probe(url, timeout=timeout, retries=retries)
            results.append((svc, ok, lat, ip))
            if stop_on_fail and not ok:
                break
        return "ok", results
    finally:
        _kill_winws()


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

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip('#')
    if len(h) == 3:
        h = ''.join([c * 2 for c in h])
    if len(h) != 6:
        return (10, 10, 10)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (10, 10, 10)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*(max(0, min(255, int(v))) for v in rgb))


def _blend_color(c1: str, c2: str, factor: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((
        r1 + (r2 - r1) * factor,
        g1 + (g2 - g1) * factor,
        b1 + (b2 - b1) * factor,
    ))


def _is_dark_color(h: str) -> bool:
    r, g, b = _hex_to_rgb(h)
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def build_stylesheet(color1: str = "#0a0a0a", color2: str = "#ffffff", text_color: str = "#e0e0e0", has_wallpaper: bool = False) -> str:
    dark_theme = _is_dark_color(color1)
    contrast_partner = "#ffffff" if dark_theme else "#000000"

    bg_main = color1
    bg_panel_left = _blend_color(color1, contrast_partner, 0.02)
    bg_tab_bar = _blend_color(color1, contrast_partner, 0.035)
    bg_card = _blend_color(color1, contrast_partner, 0.065)
    bg_hover = _blend_color(color1, contrast_partner, 0.10)
    bg_pressed = _blend_color(color1, contrast_partner, 0.04)
    bg_input = _blend_color(color1, contrast_partner, 0.05)
    bg_darker = _blend_color(color1, "#000000" if dark_theme else "#ffffff", 0.04)

    border_dark = _blend_color(color1, contrast_partner, 0.12)
    border_light = _blend_color(color1, contrast_partner, 0.22)

    accent = color2
    accent_hover = _blend_color(color2, color1, 0.15)
    accent_text = color1 if not _is_dark_color(color2) else "#ffffff"

    txt_primary = text_color
    txt_dim = _blend_color(text_color, color1, 0.35)
    txt_muted = _blend_color(text_color, color1, 0.55)
    txt_disabled = _blend_color(text_color, color1, 0.70)

    if has_wallpaper:
        r1, g1, b1 = _hex_to_rgb(color1)
        bg_panel_left = f"rgba({r1}, {g1}, {b1}, 0.82)"
        bg_panel_right = f"rgba({r1}, {g1}, {b1}, 0.65)"
        bg_tab_bar = f"rgba({r1}, {g1}, {b1}, 0.88)"
        bg_card = f"rgba({r1}, {g1}, {b1}, 0.80)"
        bg_hover = f"rgba({r1}, {g1}, {b1}, 0.90)"
        bg_pressed = f"rgba({r1}, {g1}, {b1}, 0.70)"
        bg_input = f"rgba({r1}, {g1}, {b1}, 0.85)"
        bg_darker = f"rgba({r1}, {g1}, {b1}, 0.80)"
        panel_rules = f"""
QMainWindow {{
    background: transparent;
}}
QWidget {{
    background: transparent;
    color: {txt_primary};
}}
QWidget#panelLeft {{
    background: {bg_panel_left};
}}
QWidget#panelRight {{
    background: {bg_panel_right};
}}
QWidget#tabBar {{
    background: {bg_tab_bar};
    border-bottom: 1px solid {border_dark};
}}
"""
    else:
        panel_rules = f"""
QMainWindow, QWidget {{
    background: {bg_main};
    color: {txt_primary};
}}
QWidget#panelLeft {{
    background: {bg_panel_left};
}}
QWidget#panelRight {{
    background: {bg_main};
}}
QWidget#tabBar {{
    background: {bg_tab_bar};
    border-bottom: 1px solid {border_dark};
}}
"""

    return f"""
* {{
    font-family: 'Segoe UI', sans-serif;
}}

{panel_rules}

QDialog {{
    background: {bg_main};
    color: {txt_primary};
    border: 1px solid {border_light};
    border-radius: 8px;
}}

/* ── Panels ── */
QWidget#panelDivider {{
    background: {border_dark};
    min-width: 1px;
    max-width: 1px;
}}
QPushButton#tab {{
    background: transparent;
    color: {txt_muted};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 12px 0;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QPushButton#tab:hover {{
    color: {txt_dim};
    background: {bg_hover};
}}
QPushButton#tab[active="true"] {{
    color: {txt_primary};
    border-bottom: 2px solid {accent};
    background: {bg_main};
}}

/* ── Side tabs for App Settings ── */
QPushButton#settingsSideTab {{
    background: transparent;
    color: {txt_muted};
    border: none;
    border-left: 3px solid transparent;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    text-align: left;
    border-radius: 0px;
}}
QPushButton#settingsSideTab:hover {{
    color: {txt_primary};
    background: {bg_hover};
}}
QPushButton#settingsSideTab[active="true"] {{
    color: {txt_primary};
    border-left: 3px solid {accent};
    background: {bg_card};
}}

/* ── Buttons ── */
QPushButton#actionBtn {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#actionBtn:hover {{
    background: {bg_hover};
    border-color: {border_light};
    color: {accent};
}}
QPushButton#actionBtn:pressed {{
    background: {bg_pressed};
}}
QPushButton#actionBtn:disabled {{
    color: {txt_disabled};
    border-color: {border_dark};
}}

QPushButton#testBtn {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#testBtn:hover {{
    background: {bg_hover};
    border-color: {border_light};
    color: {accent};
}}
QPushButton#testBtn[testing="true"] {{
    background: {bg_card};
    color: {txt_dim};
    border-color: {border_dark};
}}

QPushButton#startBtn {{
    background: {bg_card};
    color: {accent};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#startBtn:hover {{
    background: {bg_hover};
    border-color: {border_light};
    color: {accent};
}}
QPushButton#startBtn:pressed {{
    background: {bg_pressed};
    color: {accent};
}}

QPushButton#stopBtn {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#stopBtn:hover {{
    background: {bg_hover};
    border-color: {border_light};
    color: {accent};
}}

QPushButton#createBtn {{
    background: {accent};
    color: {accent_text};
    border: none;
    border-radius: 6px;
    padding: 10px 24px;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#createBtn:hover {{
    background: {accent_hover};
}}
QPushButton#createBtn:disabled {{
    background: {border_dark};
    color: {txt_disabled};
}}

/* ── List widget ── */
QListWidget {{
    background: {bg_tab_bar};
    color: {txt_dim};
    border: 1px solid {border_dark};
    border-radius: 6px;
    font-size: 12px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{
    padding: 10px 12px;
    border-radius: 4px;
    border-left: 3px solid transparent;
    margin: 1px 0;
}}
QListWidget::item:hover {{
    background: {bg_hover};
    color: {txt_primary};
}}
QListWidget::item:selected {{
    background: {bg_card};
    color: {txt_primary};
    border-left: 3px solid {accent};
}}

/* ── CheckBox ── */
QCheckBox {{
    color: {txt_primary};
    font-size: 12px;
    spacing: 7px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {border_light};
    border-radius: 3px;
    background: {bg_card};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
}}
QCheckBox:hover {{
    color: {accent};
}}

/* ── Console ── */
QTextEdit#console {{
    background: {bg_darker};
    color: {txt_dim};
    border: 1px solid {border_dark};
    border-radius: 6px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    padding: 8px;
}}

/* ── Inputs & Utils Form ── */
QLineEdit {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QLineEdit:focus {{
    border: 1px solid {border_light};
    background: {bg_input};
    color: {accent};
}}
QLineEdit:disabled {{
    color: {txt_disabled};
    background: {bg_panel_left};
    border-color: {border_dark};
}}

QTextEdit#settingText {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 6px 10px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
}}
QTextEdit#settingText:focus {{
    border: 1px solid {border_light};
    color: {accent};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QPushButton#iconBtn {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#iconBtn:hover {{
    background: {bg_hover};
    border-color: {border_light};
    color: {accent};
}}

/* ── ScrollBar ── */
QScrollBar:vertical {{
    background: {bg_panel_left};
    width: 6px;
    border: none;
    margin: 0;
    padding: 0;
}}
QScrollBar::handle:vertical {{
    background: {border_dark};
    border-radius: 3px;
    min-height: 24px;
    border: none;
}}
QScrollBar::handle:vertical:hover {{
    background: {border_light};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    border: none;
    background: none;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    border: none;
}}
QScrollBar:horizontal {{
    height: 0;
    background: none;
    border: none;
}}

/* ── Status bar ── */
QLabel#statusBar {{
    background: {bg_darker};
    color: {txt_disabled};
    font-size: 11px;
    border-top: 1px solid {border_dark};
    padding: 0 14px;
}}

/* ── Section labels ── */
QLabel#sectionLbl {{
    color: {txt_muted};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    background: transparent;
}}

/* ── Info label ── */
QLabel#infoLbl {{
    color: {txt_muted};
    font-size: 11px;
    background: transparent;
}}

/* ── Tray menu ── */
QMenu {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    font-size: 12px;
}}
QMenu::item {{
    padding: 6px 20px;
}}
QMenu::item:selected {{
    background: {bg_hover};
    color: {accent};
}}
QMenu::separator {{
    background: {border_dark};
    height: 1px;
    margin: 3px 0;
}}

/* ── Sliders ── */
QSlider::groove:horizontal {{
    background: {border_dark};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {accent};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {accent_hover};
}}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}
QSlider::add-page:horizontal {{
    background: {border_dark};
    border-radius: 2px;
}}

/* ── Progress Bar ── */
QProgressBar {{
    background: {bg_input};
    border: 1px solid {border_dark};
    border-radius: 4px;
    text-align: center;
    color: {txt_primary};
    font-size: 11px;
    height: 14px;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 3px;
}}

/* ── Color Dialog ── */
QColorDialog {{
    background: {bg_main};
}}
QColorDialog QLabel {{
    color: {txt_primary};
    background: transparent;
}}
QColorDialog QLineEdit,
QColorDialog QSpinBox {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {border_light};
}}
QColorDialog QLineEdit:focus,
QColorDialog QSpinBox:focus {{
    border-color: {accent};
}}
QColorDialog QPushButton {{
    background: {bg_card};
    color: {txt_primary};
    border: 1px solid {border_dark};
    border-radius: 6px;
    padding: 6px 14px;
    min-height: 24px;
    font-size: 12px;
    font-weight: 500;
}}
QColorDialog QPushButton:hover {{
    background: {bg_hover};
    border-color: {border_light};
    color: {accent};
}}
QColorDialog QPushButton:pressed {{
    background: {bg_pressed};
}}
QColorDialog QDialogButtonBox QPushButton {{
    min-width: 82px;
    min-height: 28px;
    padding: 6px 18px;
    margin-left: 8px;
    font-weight: 500;
}}
QColorDialog QDialogButtonBox QPushButton:default {{
    background: {accent};
    color: {bg_main};
    border: 1px solid {accent};
    font-weight: 600;
}}
QColorDialog QDialogButtonBox QPushButton:default:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
    color: {bg_main};
}}
"""


STYLE = build_stylesheet("#0a0a0a", "#ffffff", "#e0e0e0")

# ══════════════════════════════════════════════════════════════════
#  WALLPAPER WIDGET (Image / GIF / Video background)
# ══════════════════════════════════════════════════════════════════

class WallpaperWidget(QWidget):
    """
    Background widget supporting images, animated GIFs, and videos (without sound).
    Smoothly scales and centers media preserving aspect ratio (no squishing/stretching).
    """
    def __init__(self, parent: QWidget | None = None, color1: str = "#0a0a0a"):
        super().__init__(parent)
        self._color1 = color1
        self._current_pixmap: QPixmap | None = None
        self._wallpaper_path: Path | None = None
        self._movie: QMovie | None = None
        self._player: "QMediaPlayer | None" = None
        self._sink: "QVideoSink | None" = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)

    def set_base_color(self, color: str):
        self._color1 = color
        self.update()

    def clear_wallpaper(self):
        if self._movie:
            try:
                self._movie.stop()
                self._movie.deleteLater()
            except Exception:
                pass
            self._movie = None

        if self._player:
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                pass

        self._current_pixmap = None
        self._wallpaper_path = None
        self.update()

    def set_wallpaper(self, path: Path | str | None):
        self.clear_wallpaper()
        if not path:
            return

        p = Path(path)
        if not p.exists():
            return

        self._wallpaper_path = p
        ext = p.suffix.lower()

        # 1. Animated GIF
        if ext == ".gif":
            try:
                self._movie = QMovie(str(p))
                self._movie.frameChanged.connect(self._on_movie_frame)
                self._movie.start()
                self._current_pixmap = self._movie.currentPixmap()
                self.update()
                return
            except Exception:
                pass

        # 2. Video formats (no sound)
        video_exts = (".mp4", ".mkv", ".avi", ".webm", ".mov", ".wmv", ".flv", ".m4v")
        if ext in video_exts and HAS_MULTIMEDIA:
            try:
                if self._player is None:
                    self._player = QMediaPlayer(self)
                    self._sink = QVideoSink(self)
                    self._player.setVideoSink(self._sink)
                    self._player.setAudioOutput(None)
                    self._sink.videoFrameChanged.connect(self._on_video_frame)

                self._player.setLoops(QMediaPlayer.Loops.Infinite)
                self._player.setSource(QUrl.fromLocalFile(str(p)))
                self._player.play()
                return
            except Exception:
                pass

        # 3. Static image (PNG, JPG, BMP, WEBP, etc.)
        try:
            pm = QPixmap(str(p))
            if not pm.isNull():
                self._current_pixmap = pm
                self.update()
                return
        except Exception:
            pass

        # Fallback to multimedia if available
        if HAS_MULTIMEDIA and self._player is None:
            try:
                self._player = QMediaPlayer(self)
                self._sink = QVideoSink(self)
                self._player.setVideoSink(self._sink)
                self._player.setAudioOutput(None)
                self._sink.videoFrameChanged.connect(self._on_video_frame)
                self._player.setLoops(QMediaPlayer.Loops.Infinite)
                self._player.setSource(QUrl.fromLocalFile(str(p)))
                self._player.play()
            except Exception:
                pass

    def _on_movie_frame(self):
        if self._movie:
            pm = self._movie.currentPixmap()
            if not pm.isNull():
                self._current_pixmap = pm
                self.update()

    def _on_video_frame(self, frame: "QVideoFrame"):
        img = frame.toImage()
        if not img.isNull():
            self._current_pixmap = QPixmap.fromImage(img)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        if self._current_pixmap and not self._current_pixmap.isNull() and w > 0 and h > 0:
            scaled = self._current_pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation
            )
            x = (w - scaled.width()) // 2
            y = (h - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(self.rect(), QColor(self._color1))


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

    def set_theme(self, bg_color: str, accent_color: str):
        self._bg_color = bg_color
        self._accent_color = accent_color
        self._refresh()

    @property
    def state(self):
        return self._state

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ══════════════════════════════════════════════════════════════════
#  CUSTOM WIDGETS & UPDATE WORKER
# ══════════════════════════════════════════════════════════════════

class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(44, 24)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._accent_color = "#ffffff"
        self._bg_color = "#0a0a0a"

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if self._checked != checked:
            self._checked = checked
            self.update()
            self.toggled.emit(self._checked)

    def set_colors(self, accent: str, bg: str):
        self._accent_color = accent
        self._bg_color = bg
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = self.rect()
        if self._checked:
            track_brush = QBrush(QColor(self._accent_color))
            track_pen = QPen(QColor(self._accent_color), 1)
            thumb_color = QColor(self._bg_color)
            thumb_x = r.width() - 21
        else:
            track_brush = QBrush(QColor("#242424"))
            track_pen = QPen(QColor("#404040"), 1)
            thumb_color = QColor("#888888")
            thumb_x = 3

        p.setBrush(track_brush)
        p.setPen(track_pen)
        p.drawRoundedRect(1, 1, r.width() - 2, r.height() - 2, 11, 11)

        p.setBrush(QBrush(thumb_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(thumb_x, 3, 18, 18)
        p.end()


def parse_version(v_str: str) -> tuple[int, ...]:
    clean = re.sub(r'^[^\d]*', '', v_str.strip())
    parts = []
    for piece in clean.split('.'):
        num_m = re.match(r'^\d+', piece)
        if num_m:
            parts.append(int(num_m.group(0)))
        else:
            break
    return tuple(parts) if parts else (0,)


def is_newer_version(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def get_target_exe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    app_dir = Path(__file__).resolve().parent
    exe_candidate = app_dir / "dist" / "zapret_pp.exe"
    if exe_candidate.exists():
        return exe_candidate
    exe_root = app_dir / "zapret_pp.exe"
    if exe_root.exists():
        return exe_root
    return exe_candidate


class AutoUpdateWorker(QThread):
    progress = pyqtSignal(int, int)  # downloaded_bytes, total_bytes
    status = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, download_url: str, target_exe: Path):
        super().__init__()
        self.download_url = download_url
        self.target_exe = target_exe

    def run(self):
        try:
            self.status.emit("Connecting to server...")
            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "zapret_pp"}
            )
            temp_dir = Path(os.environ.get("TEMP", str(self.target_exe.parent)))
            temp_exe = temp_dir / f"zapret_pp_update_{os.getpid()}.exe"

            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 65536

                with open(temp_exe, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)

            if not temp_exe.exists() or temp_exe.stat().st_size < 10000:
                self.finished.emit(False, "Downloaded file is corrupted or too small.")
                return

            self.status.emit("Applying update and restarting...")
            updater_bat = temp_dir / f"zapret_pp_updater_{os.getpid()}.bat"
            bat_script = f"""@echo off
chcp 65001 > nul
timeout /t 1 /nobreak > nul
taskkill /f /pid {os.getpid()} > nul 2>&1
:loop
del "{self.target_exe}" > nul 2>&1
if exist "{self.target_exe}" (
    timeout /t 1 /nobreak > nul
    goto loop
)
move /y "{temp_exe}" "{self.target_exe}" > nul
start "" "{self.target_exe}"
del "%~f0"
"""
            updater_bat.write_text(bat_script, encoding="utf-8")

            subprocess.Popen(
                ["cmd.exe", "/c", str(updater_bat)],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                close_fds=True
            )
            self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class NewUpdateDialog(QDialog):
    def __init__(self, new_tag: str, current_ver: str, stylesheet: str, parent=None, auto_download: bool = False, download_url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("New update")
        self.setFixedSize(400, 230 if auto_download else 200)
        self.setModal(True)
        self.setStyleSheet(stylesheet)
        self.auto_download = auto_download
        self.download_url = download_url or f"https://github.com/bpm500/zapret_pp/releases/download/{new_tag}/zapret_pp.exe"
        self._update_worker: AutoUpdateWorker | None = None

        vlay = QVBoxLayout(self)
        vlay.setContentsMargins(28, 22, 28, 22)
        vlay.setSpacing(12)

        lbl_title = QLabel("New update")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet("font-size: 20px; font-weight: 700; letter-spacing: 0.5px; background: transparent;")
        vlay.addWidget(lbl_title)

        lbl_info = QLabel(f"A new version is available: {new_tag}\nCurrent version: v{current_ver}")
        lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_info.setStyleSheet("font-size: 13px; color: #888888; background: transparent;")
        vlay.addWidget(lbl_info)

        # Progress bar and status label for auto-download
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setVisible(False)
        vlay.addWidget(self._progress_bar)

        self._lbl_status = QLabel("")
        self._lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_status.setStyleSheet("font-size: 11px; color: #888888; background: transparent;")
        self._lbl_status.setVisible(False)
        vlay.addWidget(self._lbl_status)

        vlay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(14)

        if self.auto_download:
            self._btn_cancel = QPushButton("cancel")
            self._btn_cancel.setObjectName("actionBtn")
            self._btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_cancel.setFixedHeight(36)
            self._btn_cancel.clicked.connect(self.reject)

            self._btn_install_auto = QPushButton("install auto")
            self._btn_install_auto.setObjectName("createBtn")
            self._btn_install_auto.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_install_auto.setFixedHeight(36)
            self._btn_install_auto.clicked.connect(self._install_auto)

            btn_row.addWidget(self._btn_cancel)
            btn_row.addWidget(self._btn_install_auto)
        else:
            self._btn_back = QPushButton("back")
            self._btn_back.setObjectName("actionBtn")
            self._btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_back.setFixedHeight(36)
            self._btn_back.clicked.connect(self.reject)

            self._btn_download = QPushButton("download")
            self._btn_download.setObjectName("createBtn")
            self._btn_download.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self._btn_download.setFixedHeight(36)
            self._btn_download.clicked.connect(self._download)

            btn_row.addWidget(self._btn_back)
            btn_row.addWidget(self._btn_download)

        vlay.addLayout(btn_row)

    def _download(self):
        QDesktopServices.openUrl(QUrl("https://github.com/bpm500/zapret_pp/releases"))
        self.accept()

    def _install_auto(self):
        self._btn_cancel.setEnabled(False)
        self._btn_install_auto.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._lbl_status.setVisible(True)
        self._lbl_status.setText("Connecting...")

        target_exe = get_target_exe()
        self._update_worker = AutoUpdateWorker(self.download_url, target_exe)
        self._update_worker.progress.connect(self._on_download_progress)
        self._update_worker.status.connect(self._lbl_status.setText)
        self._update_worker.finished.connect(self._on_update_finished)
        self._update_worker.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int((downloaded / total) * 100)
            mb_down = downloaded / (1024 * 1024)
            mb_tot = total / (1024 * 1024)
            self._progress_bar.setValue(pct)
            self._lbl_status.setText(f"Downloading: {mb_down:.1f} / {mb_tot:.1f} MB ({pct}%)")
        else:
            mb_down = downloaded / (1024 * 1024)
            self._lbl_status.setText(f"Downloading: {mb_down:.1f} MB")

    def _on_update_finished(self, success: bool, err_msg: str):
        if success:
            self._lbl_status.setText("Update installed! Restarting...")
            self._lbl_status.setStyleSheet("color: #4cd964; font-size: 11px; background: transparent;")
            QTimer.singleShot(700, QApplication.quit)
        else:
            self._lbl_status.setText(f"Failed: {err_msg}")
            self._lbl_status.setStyleSheet("color: #ff5555; font-size: 11px; background: transparent;")
            self._btn_cancel.setEnabled(True)
            self._btn_install_auto.setEnabled(True)
            self._btn_install_auto.setText("retry")


class UpdateCheckWorker(QThread):
    finished = pyqtSignal(bool, str, str)  # success, tag, download_url

    def run(self):
        try:
            # 1. API releases/latest
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/bpm500/zapret_pp/releases/latest",
                    headers={"User-Agent": "zapret_pp"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    tag = data.get("tag_name")
                    if tag:
                        asset_url = ""
                        for a in data.get("assets", []):
                            n = a.get("name", "").lower()
                            if n.endswith(".exe"):
                                asset_url = a.get("browser_download_url", "")
                                break
                        if not asset_url:
                            asset_url = f"https://github.com/bpm500/zapret_pp/releases/download/{tag}/zapret_pp.exe"
                        self.finished.emit(True, str(tag), asset_url)
                        return
            except Exception:
                pass

            # 2. API tags
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/bpm500/zapret_pp/tags",
                    headers={"User-Agent": "zapret_pp"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    tags = json.loads(resp.read().decode("utf-8"))
                    if tags and isinstance(tags, list) and len(tags) > 0:
                        tag = tags[0].get("name")
                        if tag:
                            asset_url = f"https://github.com/bpm500/zapret_pp/releases/download/{tag}/zapret_pp.exe"
                            self.finished.emit(True, str(tag), asset_url)
                            return
            except Exception:
                pass

            # 3. Fallback: scrape releases page
            try:
                req = urllib.request.Request(
                    "https://github.com/bpm500/zapret_pp/releases",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    html = resp.read().decode("utf-8")
                    m = re.findall(r'/bpm500/zapret_pp/releases/tag/([^"\'\s<>]+)', html)
                    if m:
                        tag = m[0]
                        asset_url = f"https://github.com/bpm500/zapret_pp/releases/download/{tag}/zapret_pp.exe"
                        self.finished.emit(True, tag, asset_url)
                        return
            except Exception:
                pass

            self.finished.emit(False, "No releases found", "")
        except Exception as e:
            self.finished.emit(False, str(e), "")


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
#  TEST WORKERS — test selected config or test all configs
# ══════════════════════════════════════════════════════════════════

class TestSelectedWorker(QThread):
    log = pyqtSignal(str, str)
    result = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, zapret_dir: Path, bat_file: str, was_connected: bool):
        super().__init__()
        self.zapret_dir = zapret_dir
        self.bat_file = bat_file
        self.was_connected = was_connected
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        p_name = self.bat_file
        self.log.emit("━" * 45, "dim")
        self.log.emit(f"  Testing config: {p_name}", "white")
        self.log.emit("━" * 45, "dim")

        need_kill_when_done = False
        if not _is_winws_running() or not self.was_connected:
            _kill_winws()
            time.sleep(0.5)
            if self._stop:
                self.finished.emit()
                return

            bat_path = self.zapret_dir / self.bat_file
            try:
                _run_bat_admin(bat_path)
                need_kill_when_done = True
                for _ in range(20):
                    if _is_winws_running():
                        break
                    time.sleep(0.15)
                time.sleep(0.5)
            except Exception as e:
                self.log.emit(f"  Failed to start config: {e}", "white")
                self.finished.emit()
                return

        services = [
            ("Discord", "https://discord.com/api/v9/gateway"),
            ("YouTube", "https://www.youtube.com/generate_204"),
        ]

        results = {}
        for svc, url in services:
            if self._stop:
                break
            self.log.emit(f"  Probing {svc}...", "dim")
            ok, latency_ms, ip = _probe(url, timeout=4.0, retries=2)
            results[svc] = (ok, latency_ms, ip)
            mark = "✓" if ok else "✗"
            extra = f" ({latency_ms} ms, ip={ip})" if ok else f" (fail, ip={ip or '?'})"
            self.log.emit(f"    {svc}: {mark}{extra}", "white" if ok else "dim")

        if need_kill_when_done and not self.was_connected:
            _kill_winws()

        if self._stop:
            self.log.emit("\n⛔  Test stopped.", "white")
        else:
            ok_count = sum(1 for ok, _, _ in results.values() if ok)
            self.log.emit(f"\n  Config '{p_name}': {ok_count}/{len(results)} services OK.", "white")

            lines = ["━" * 45, f"  CONFIG: {p_name}", "━" * 45]
            for svc, (ok, lat, ip) in results.items():
                status = "✓ OK" if ok else "✗ BLOCKED"
                lines.append(f"  {svc}: {status} — {lat or '?'} ms (IP: {ip or '?'})")
            self.result.emit("\n".join(lines))

        self.finished.emit()


class TestWorker(QThread):
    log = pyqtSignal(str, str)
    result = pyqtSignal(str)
    ranked = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, bat_files: list, zapret_dir: Path, was_connected: bool = False, multi_ping: bool = True):
        super().__init__()
        self.bat_files = list(bat_files)
        self.zapret_dir = zapret_dir
        self.was_connected = was_connected
        self.multi_ping = multi_ping
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.bat_files)
        self.log.emit("━" * 45, "dim")
        self.log.emit(f"  Testing all {total} configs...", "white")
        self.log.emit("━" * 45, "dim")

        services = [
            ("Discord", "https://discord.com/api/v9/gateway"),
            ("YouTube", "https://www.youtube.com/generate_204"),
        ]

        _kill_winws()
        time.sleep(0.5)

        exe = _find_winws_exe(self.zapret_dir)
        parallel = self.multi_ping and exe is not None and _winws_supports_wf_raw(exe)
        if parallel:
            self.log.emit(f"  Parallel mode: {PARALLEL_SLOTS} isolated slots", "dim")
        elif self.multi_ping:
            self.log.emit("  winws has no --wf-raw support → sequential mode", "dim")
        else:
            self.log.emit("  Sequential mode", "dim")

        stop_check = lambda: self._stop
        scored: dict = {}            # bat -> (ok_count, avg_lat)
        fallback: list = []          # bat, которые не удалось разобрать
        lock = threading.Lock()
        done = [0]

        def _report(bat_file, state, results):
            """Один непрерывный блок лога + запись результата. Вызывать под lock."""
            done[0] += 1
            self.log.emit(f"\n▶ [{done[0]}/{total}] {bat_file}", "white")
            if state == "start_failed":
                self.log.emit("    winws failed to start, skipping...", "dim")
                scored[bat_file] = (0, 99999)
                return
            if state != "ok":
                scored[bat_file] = (0, 99999)
                return
            ok_count, latencies = 0, []
            for svc, ok, lat, ip in results:
                if ok:
                    ok_count += 1
                    if lat:
                        latencies.append(lat)
                extra = f" ({lat} ms)" if ok and lat else ""
                self.log.emit(f"    {svc}: {'✓' if ok else '✗'}{extra}", "white" if ok else "dim")
            avg = int(sum(latencies) / len(latencies)) if latencies else 9999
            scored[bat_file] = (ok_count, avg)

        if not parallel:
            for idx, bat_file in enumerate(self.bat_files):
                if self._stop:
                    break

                bat_path = self.zapret_dir / bat_file
                self.log.emit(f"\n▶ [{idx + 1}/{total}] {bat_file}", "white")

                _kill_winws()
                time.sleep(0.5)

                if self._stop:
                    break

                try:
                    _run_bat_admin(bat_path)
                    for _ in range(20):
                        if _is_winws_running():
                            break
                        time.sleep(0.15)
                    time.sleep(0.5)

                    if not _is_winws_running():
                        self.log.emit("    winws failed to start, skipping...", "dim")
                        scored[bat_file] = (0, 99999)
                        continue

                    # Probe services
                    ok_count = 0
                    latencies = []

                    for svc, url in services:
                        if self._stop:
                            break
                        ok, lat, ip = _probe(url, timeout=3.5, retries=1)
                        if ok:
                            ok_count += 1
                            if lat:
                                latencies.append(lat)
                        mark = "✓" if ok else "✗"
                        extra = f" ({lat} ms)" if ok and lat else ""
                        self.log.emit(f"    {svc}: {mark}{extra}", "white" if ok else "dim")

                    avg_lat = int(sum(latencies) / len(latencies)) if latencies else 9999
                    scored[bat_file] = (ok_count, avg_lat)

                except Exception as e:
                    self.log.emit(f"    Error: {e}", "white")
                    scored[bat_file] = (0, 99999)
                finally:
                    _kill_winws()
        else:
            work: "queue.Queue" = queue.Queue()
            for b in self.bat_files:
                work.put(b)

            def slot_worker(pool):
                while not self._stop:
                    try:
                        bat_file = work.get_nowait()
                    except queue.Empty:
                        return
                    try:
                        state, res = _test_bat_isolated(
                            self.zapret_dir / bat_file, exe, pool, services,
                            stop_check, timeout=3.5, retries=1,
                        )
                    except Exception as e:
                        with lock:
                            self.log.emit(f"    Error ({bat_file}): {e}", "white")
                            scored[bat_file] = (0, 99999)
                        continue
                    if state == "stopped":
                        return
                    with lock:
                        if state == "unparsable":
                            fallback.append(bat_file)
                        else:
                            _report(bat_file, state, res)

            threads = [threading.Thread(target=slot_worker, args=(p,), daemon=True)
                       for p in _make_slot_pools()]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Unparsable fallback in parallel mode
            for bat_file in fallback:
                if self._stop:
                    break
                try:
                    state, res = _test_bat_legacy(
                        self.zapret_dir / bat_file, services, stop_check, timeout=3.5, retries=1,
                    )
                except Exception as e:
                    self.log.emit(f"    Error ({bat_file}): {e}", "white")
                    scored[bat_file] = (0, 99999)
                    continue
                if state != "stopped":
                    with lock:
                        _report(bat_file, state, res)

        _kill_winws()

        if self._stop:
            self.log.emit("\n⛔  Testing all configs stopped.", "white")
            self.finished.emit()
            return

        # Сохраняем исходный порядок bat_files перед сортировкой (как в оригинале)
        scored_configs = [(b, *scored[b]) for b in self.bat_files if b in scored]

        # Sort: highest ok_count first, then lowest avg_lat
        scored_configs.sort(key=lambda x: (x[1], -x[2]), reverse=True)

        # Assign top_rank (1, 2, 3) ONLY to working configs (ok_count > 0)
        working_count = 0
        ranked_dict = {}
        for b_name, ok_c, _ in scored_configs:
            if ok_c > 0 and working_count < 3:
                working_count += 1
                ranked_dict[b_name] = working_count

        sorted_bat_files = [item[0] for item in scored_configs]

        # Build ranking report
        lines = [
            "━" * 45,
            "  TOP CONFIGS RANKING",
            "━" * 45,
        ]
        medals = ["🥇", "🥈", "🥉"]
        medal_idx = 0
        for rank, (b_name, ok_c, avg_l) in enumerate(scored_configs):
            lat_str = f"{avg_l} ms" if avg_l < 9000 else "timeout"
            if ok_c > 0:
                prefix = medals[medal_idx] if medal_idx < 3 else f" {rank+1}."
                medal_idx += 1
                lines.append(f"{prefix} {b_name} — {ok_c}/{len(services)} OK (avg {lat_str})")
            else:
                lines.append(f" ✗ {b_name} — 0/{len(services)} OK (blocked)")

        self.result.emit("\n".join(lines))
        self.log.emit("\n" + "\n".join(lines), "white")
        if working_count > 0:
            count_str = f"Top {working_count}" if working_count > 1 else "1 working"
            self.log.emit(f"\n🏆 {count_str} config(s) placed on the left!", "white")
        else:
            self.log.emit("\n⚠  No working configs found.", "white")

        self.ranked.emit(json.dumps({"sorted": sorted_bat_files, "ranks": ranked_dict}))
        self.finished.emit()


# ══════════════════════════════════════════════════════════════════
#  SOUNDCLOUD DOMAINS FOR HOSTLIST
# ══════════════════════════════════════════════════════════════════

SOUNDCLOUD_DOMAINS = [
    "soundcloud.com",
    "api.soundcloud.com",
    "feeds.soundcloud.com",
    "media.soundcloud.com",
    "cf-media.sndcdn.com",
    "edge-api.soundcloud.com",
    "w1.sndcdn.com",
    "api-v2.soundcloud.com",
    "assets.soundcloud.com",
    "secure-media.soundcloud.com",
    "cf-hls-media.sndcdn.com",
    "sndcdn.com",
    "mobi.soundcloud.com",
    "promote-v2.soundcloud.com",
    "charts.soundcloud.com",
    "developers.soundcloud.com",
    "checkout.soundcloud.com",
    "pre-pnd.soundcloud.com",
    "pnd.soundcloud.com",
    "help.soundcloud.com",
    "support.soundcloud.com",
    "a-v2.sndcdn.com",
    "style.sndcdn.com",
    "assets.web.soundcloud.cloud",
    "i1.sndcdn.com",
    "al.sndcdn.com",
    "playback.media-streaming.soundcloud.cloud",
]

SPEEDTEST_DOMAINS = [
    "speedtest.net",
    "c.speedtest.net",
    "speedtestcustom.com",
    "usbrowserspeed.com",
    "ooklaserver.net",
    "cdnst.net",
]


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

    # ── hostfakesplit variants (ALT3/ALT4/EXP bypasses) ──
    ("hostfakesplit-ts-google", (
        '--dpi-desync=hostfakesplit --dpi-desync-fooling=ts '
        '--dpi-desync-hostfakesplit-mod=host=www.google.com'
    )),
    ("hostfakesplit-ts-altorder", (
        '--dpi-desync=hostfakesplit --dpi-desync-fooling=ts '
        '--dpi-desync-hostfakesplit-mod=host=www.google.com,altorder=1'
    )),
    ("fake-hostfakesplit-rnd-google-ts", (
        '--dpi-desync=fake,hostfakesplit '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com '
        '--dpi-desync-hostfakesplit-mod=host=www.google.com,altorder=1 '
        '--dpi-desync-fooling=ts'
    )),
    ("fake-hostfakesplit-rnd-yaru-ts", (
        '--dpi-desync=fake,hostfakesplit '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=ya.ru '
        '--dpi-desync-hostfakesplit-mod=host=ya.ru,altorder=1 '
        '--dpi-desync-fooling=ts'
    )),
    ("fake-hostfakesplit-badseq-r8", (
        '--dpi-desync=fake,hostfakesplit '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com '
        '--dpi-desync-hostfakesplit-mod=host=www.google.com,altorder=1 '
        '--dpi-desync-fooling=badseq'
    )),
    ("fake-hostfakesplit-4pda-ts", (
        '--dpi-desync=fake,hostfakesplit '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=4pda.to '
        '--dpi-desync-hostfakesplit-mod=host=4pda.to,altorder=1 '
        '--dpi-desync-fooling=ts'
    )),

    # ── fakedsni variants (SNI-targeting DPI desync) ──
    ("fakedsni-ts-r6-google", (
        '--dpi-desync=fake,fakedsni --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsni-badseq-r6-google", (
        '--dpi-desync=fake,fakedsni --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsni-ts-r8-max", (
        '--dpi-desync=fake,fakedsni --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("fakedsni-badseq-r11-4pda", (
        '--dpi-desync=fake,fakedsni --dpi-desync-repeats=11 '
        '--dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_4pda_to.bin"'
    )),
    ("fakedsni-md5sig-r6", (
        '--dpi-desync=fake,fakedsni --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=md5sig '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── sniext split & disorder variants (ALT7 style) ──
    ("multisplit-sniext-679", (
        '--dpi-desync=multisplit --dpi-desync-split-pos=2,sniext+1 '
        '--dpi-desync-split-seqovl=679 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-sniext-664-max", (
        '--dpi-desync=multisplit --dpi-desync-split-pos=2,sniext+1 '
        '--dpi-desync-split-seqovl=664 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("split2-sniext", (
        '--dpi-desync=split2 --dpi-desync-split-pos=sniext'
    )),
    ("split2-1-sniext", (
        '--dpi-desync=split2 --dpi-desync-split-pos=1,sniext'
    )),
    ("disorder2-sniext", (
        '--dpi-desync=disorder2 --dpi-desync-split-pos=sniext'
    )),
    ("disorder2-1-sniext", (
        '--dpi-desync=disorder2 --dpi-desync-split-pos=1,sniext'
    )),
    ("fakesplit-sniext-r6-ts", (
        '--dpi-desync=fake,split2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=2,sniext+1 --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-sniext-r8-badseq", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=2,sniext+1 --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── autottl & explicit ttl variants ──
    ("fakesplit-autottl2-r6-ts", (
        '--dpi-desync=fake,split2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=ts '
        '--dpi-desync-autottl=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-autottl2-r8-badseq", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=badseq '
        '--dpi-desync-autottl=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-autottl-r6-ts", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=ts --dpi-desync-autottl=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-ttl3-r6", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-ttl=3 --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fake-autottl-r6-google", (
        '--dpi-desync=fake --dpi-desync-repeats=6 --dpi-desync-autottl=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-autottl-r6", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=6 '
        '--dpi-desync-split-seqovl=681 --dpi-desync-split-pos=1 '
        '--dpi-desync-autottl=2 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── badseq increment variants (ALT8/ALT11) ──
    ("fake-badseq-inc2-r6", (
        '--dpi-desync=fake --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=badseq --dpi-desync-badseq-increment=2 '
        '--dpi-desync-fake-tls-mod=none'
    )),
    ("fake-badseq-inc2-r8-google", (
        '--dpi-desync=fake --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=badseq --dpi-desync-badseq-increment=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakesplit-badseq-inc2-r6", (
        '--dpi-desync=fake,split2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=badseq '
        '--dpi-desync-badseq-increment=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-badseq-inc2-r8", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=badseq '
        '--dpi-desync-badseq-increment=2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-badseq-inc2-r8", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1 --dpi-desync-fooling=badseq '
        '--dpi-desync-badseq-increment=2 '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com'
    )),
    ("multisplit-badseq-inc2-r8", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=8 '
        '--dpi-desync-split-seqovl=681 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=badseq --dpi-desync-badseq-increment=2 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── alternative payload templates (5ka, Max, Stun2) ──
    ("multisplit-654-5ka", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=654 '
        '--dpi-desync-split-pos=1 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_5ka_ru.bin"'
    )),
    ("multisplit-664-max", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=664 '
        '--dpi-desync-split-pos=1 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_max_ru.bin"'
    )),
    ("multisplit-480-stun2", (
        '--dpi-desync=multisplit --dpi-desync-split-seqovl=480 '
        '--dpi-desync-split-pos=1 '
        '--dpi-desync-split-seqovl-pattern="{bin}stun2.bin"'
    )),
    ("fakedsplit-ts-r6-5ka", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_5ka_ru.bin"'
    )),
    ("fakedsplit-badseq-r8-5ka", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=badseq --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_5ka_ru.bin"'
    )),
    ("fakedsplit-ts-r8-stun2", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=ts --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}stun2.bin"'
    )),
    ("fake-r6-5ka", (
        '--dpi-desync=fake --dpi-desync-repeats=6 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_5ka_ru.bin"'
    )),
    ("fake-r8-stun2", (
        '--dpi-desync=fake --dpi-desync-repeats=8 '
        '--dpi-desync-fake-tls="{bin}stun2.bin"'
    )),

    # ── advanced TLS mod combinations (padenc, padsni, ya.ru) ──
    ("multidisorder-padenc-rnd-r8", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=8 --dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,padenc,sni=www.google.com'
    )),
    ("multidisorder-padsni-rnd-r8", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=8 --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls-mod=rnd,padsni,sni=www.google.com'
    )),
    ("multidisorder-rnd-4pda-r8", (
        '--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld '
        '--dpi-desync-repeats=8 --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=4pda.to'
    )),
    ("fakedsplit-padenc-rnd-r8", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=badseq '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,padenc,sni=www.google.com'
    )),
    ("fakedsplit-rnd-yaru-r8", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=8 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls-mod=rnd,dupsid,sni=ya.ru'
    )),

    # ── specialized fooling (datanoack, hopbyhop) ──
    ("fakedsplit-datanoack-r6", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=datanoack --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedsplit-hopbyhop-r6", (
        '--dpi-desync=fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=hopbyhop --dpi-desync-fakedsplit-pattern=0x00 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-hopbyhop-r6", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=hopbyhop '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-hopbyhop2-r8", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=hopbyhop2 '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("fakedisorder-datanoack-r8", (
        '--dpi-desync=fake,disorder2 --dpi-desync-repeats=8 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=datanoack '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),

    # ── extended syndata & multisplit-fake combinations ──
    ("syndata-pure-n3", (
        '--dpi-desync=syndata --dpi-desync-any-protocol=1 --dpi-desync-cutoff=n3'
    )),
    ("syndata-split2-midsld", (
        '--dpi-desync=syndata,split2 --dpi-desync-split-pos=1,midsld'
    )),
    ("syndata-fake-disorder-r6", (
        '--dpi-desync=syndata,fake,disorder2 --dpi-desync-repeats=6 '
        '--dpi-desync-split-pos=1,midsld --dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("syndata-fake-fakedsplit-r6", (
        '--dpi-desync=syndata,fake,fakedsplit --dpi-desync-repeats=6 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("syndata-multisplit-568", (
        '--dpi-desync=syndata,multisplit --dpi-desync-split-seqovl=568 '
        '--dpi-desync-split-pos=1 '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin"'
    )),
    ("multisplit-fake-r8-ts-max", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=8 '
        '--dpi-desync-split-seqovl=664 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_max_ru.bin" '
        '--dpi-desync-fake-tls="{bin}stun2.bin"'
    )),
    ("multisplit-fake-r8-badseq-5ka", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=8 '
        '--dpi-desync-split-seqovl=654 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=badseq '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_5ka_ru.bin" '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_5ka_ru.bin"'
    )),
    ("multisplit-fake-r6-badseq-4pda", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=6 '
        '--dpi-desync-split-seqovl=284 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=badseq '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_4pda_to.bin" '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_4pda_to.bin"'
    )),
    ("multisplit-fake-r11-ts-google", (
        '--dpi-desync=fake,multisplit --dpi-desync-repeats=11 '
        '--dpi-desync-split-seqovl=681 --dpi-desync-split-pos=1 '
        '--dpi-desync-fooling=ts '
        '--dpi-desync-split-seqovl-pattern="{bin}tls_clienthello_www_google_com.bin" '
        '--dpi-desync-fake-tls="{bin}tls_clienthello_www_google_com.bin"'
    )),
]


def _generate_bat_content(zapret_dir: Path, strategy_args: str, name: str = "") -> str:
    """Generate a complete bat file content using a strategy."""
    bin_dir = zapret_dir / "bin"
    lists_dir = zapret_dir / "lists"
    bin_path = str(bin_dir).replace("/", "\\") + "\\"
    lists_path = str(lists_dir).replace("/", "\\") + "\\"

    # Replace {bin} placeholder
    tcp_args = strategy_args.replace("{bin}", "%BIN%")

    rem_line = f"rem zapret++ strategy: {name}\n" if name else ""
    content = f'''@echo off
{rem_line}chcp 65001 > nul
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


def _extract_strategy_counter(arg_str: str) -> Counter:
    tokens = []
    clean_str = re.sub(r'\^\s*[\r\n]+', ' ', arg_str)
    for tok in clean_str.split():
        tok = tok.strip().strip('"').strip("'")
        if not tok or not tok.lower().startswith("--dpi-desync"):
            continue
        tok = tok.replace("{bin}", "").replace("%BIN%", "").replace("%bin%", "")
        if "=" in tok:
            k, v = tok.split("=", 1)
            v = v.strip('"').strip("'").replace("\\", "/").split("/")[-1].lower()
            tokens.append(f"{k.lower()}={v}")
        else:
            tokens.append(tok.lower())
    return Counter(tokens)


def _is_strategy_existing(zapret_dir: Path, strategy_args: str, strategy_name: str = "") -> bool:
    if not zapret_dir.exists():
        return False

    candidate_counter = _extract_strategy_counter(strategy_args)
    if not candidate_counter:
        return False

    for bat_path in sorted(zapret_dir.glob("*.bat")):
        if bat_path.name.startswith("_test_"):
            continue
        if bat_path.name.lower() in ("service.bat", "service_install.bat", "service_remove.bat"):
            continue

        try:
            content = bat_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # 1. Match by strategy name recorded in custom header
        if strategy_name:
            m = re.search(r'rem\s+zapret\+\+\s+strategy:\s*(\S+)', content, re.IGNORECASE)
            if m and m.group(1).lower() == strategy_name.lower():
                return True

        # 2. Match by exact desync parameters counter
        clean_bat = re.sub(r'\^\s*[\r\n]+', ' ', content)
        for block in clean_bat.split("--new"):
            if candidate_counter == _extract_strategy_counter(block):
                return True

    return False


def _find_existing_strategy(zapret_dir: Path, strategy_args: str, strategy_name: str = ""):
    return (_is_strategy_existing(zapret_dir, strategy_args, strategy_name), 0)


class CreateWorker(QThread):
    log = pyqtSignal(str, str)
    success = pyqtSignal(str)  # filename of created bat
    finished = pyqtSignal()

    def __init__(self, zapret_dir: Path, target_discord: bool = True, target_youtube: bool = True, num_configs: int = 1, multi_ping: bool = True):
        super().__init__()
        self.zapret_dir = zapret_dir
        self.target_discord = target_discord
        self.target_youtube = target_youtube
        self.num_configs = num_configs
        self.multi_ping = multi_ping
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        self.log.emit("━" * 45, "dim")
        self.log.emit(f"  Route creation started ({self.num_configs} config(s) requested)", "white")
        self.log.emit("━" * 45, "dim")
        targets = []
        services = []
        if self.target_discord:
            targets.append("Discord")
            services.append(("Discord", "https://discord.com/api/v9/gateway"))
        if self.target_youtube:
            targets.append("YouTube")
            services.append(("YouTube", "https://www.youtube.com/generate_204"))
        self.log.emit(f"  Target(s): {', '.join(targets)}", "dim")

        # Shuffle strategies for randomness
        strats = list(STRATEGIES)
        random.shuffle(strats)
        total = len(strats)

        _kill_winws()
        time.sleep(0.5)

        exe = _find_winws_exe(self.zapret_dir)
        parallel = self.multi_ping and exe is not None and _winws_supports_wf_raw(exe)
        if parallel:
            self.log.emit(f"  Parallel mode: {PARALLEL_SLOTS} isolated slots", "dim")
        elif self.multi_ping:
            self.log.emit("  winws has no --wf-raw support → sequential mode", "dim")
        else:
            self.log.emit("  Sequential mode", "dim")

        def _rm(p: Path):
            try:
                p.unlink()
            except Exception:
                pass

        if not parallel:
            created_count = 0
            for idx, (name, args) in enumerate(strats):
                if self._stop:
                    break

                self.log.emit(f"\n▶ Attempt {idx + 1}/{total}: {name}", "white")

                _kill_winws()
                time.sleep(0.5)

                bat_content = _generate_bat_content(self.zapret_dir, args, name)
                tmp_bat = self.zapret_dir / f"_test_custom_{name}.bat"

                try:
                    tmp_bat.write_text(bat_content, encoding="utf-8")
                except Exception as e:
                    self.log.emit(f"  Error writing bat: {e}", "white")
                    continue

                self.log.emit("  Starting winws...", "dim")
                try:
                    _run_bat_admin(tmp_bat)
                except Exception as e:
                    self.log.emit(f"  Error running bat: {e}", "white")
                    _rm(tmp_bat)
                    continue

                for _ in range(20):
                    if _is_winws_running():
                        break
                    time.sleep(0.2)

                if self._stop:
                    _kill_winws()
                    _rm(tmp_bat)
                    break

                if not _is_winws_running():
                    self.log.emit("  winws did not start", "dim")
                    _rm(tmp_bat)
                    continue

                discord_ok = True
                youtube_ok = True

                if self.target_discord:
                    self.log.emit("  Testing Discord...", "dim")
                    discord_ok, _, discord_ip = _probe("https://discord.com/api/v9/gateway", timeout=4.0, retries=2)
                    self.log.emit(f"    Discord: {'✓' if discord_ok else '✗'} (ip={discord_ip or '?'})",
                                  "white" if discord_ok else "dim")

                if self._stop:
                    _kill_winws()
                    _rm(tmp_bat)
                    break

                if self.target_youtube and discord_ok:
                    self.log.emit("  Testing YouTube...", "dim")
                    youtube_ok, _, youtube_ip = _probe("https://www.youtube.com/generate_204", timeout=4.0, retries=2)
                    self.log.emit(f"    YouTube: {'✓' if youtube_ok else '✗'} (ip={youtube_ip or '?'})",
                                  "white" if youtube_ok else "dim")

                _kill_winws()
                time.sleep(0.5)

                if discord_ok and youtube_ok:
                    if _is_strategy_existing(self.zapret_dir, args, name):
                        self.log.emit("  That config already exists.", "#9370DB")
                        _rm(tmp_bat)
                        continue

                    created_count += 1
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

                    self.log.emit(f"\n✅  Working config #{created_count}/{self.num_configs} found: {final_name}", "white")
                    self.log.emit(f"  Strategy: {name}", "dim")
                    self.success.emit(final_name)

                    if created_count >= self.num_configs:
                        break
                else:
                    _rm(tmp_bat)
                    self.log.emit("  ✗ No access, trying next...", "dim")

            _kill_winws()
            for leftover in self.zapret_dir.glob("_test_custom_*.bat"):
                _rm(leftover)

            if self._stop:
                self.log.emit("\n⛔  Route creation stopped.", "white")
            elif created_count == 0:
                self.log.emit("\n✗  All strategies exhausted. No working route found.", "white")
            else:
                self.log.emit(f"\n✅  Finished. Created {created_count}/{self.num_configs} route(s).", "white")

            self.finished.emit()
            return

        work: "queue.Queue" = queue.Queue()
        for idx, item in enumerate(strats):
            work.put((idx, item))

        lock = threading.Lock()
        enough = threading.Event()
        created = [0]
        created_names = set()
        stop_check = lambda: self._stop or enough.is_set()

        def slot_worker(pool):
            while not stop_check():
                try:
                    idx, (name, args) = work.get_nowait()
                except queue.Empty:
                    return

                bat_content = _generate_bat_content(self.zapret_dir, args, name)
                tmp_bat = self.zapret_dir / f"_test_custom_{name}.bat"
                try:
                    tmp_bat.write_text(bat_content, encoding="utf-8")
                except Exception as e:
                    with lock:
                        self.log.emit(f"\n▶ Attempt {idx + 1}/{total}: {name}", "white")
                        self.log.emit(f"  Error writing bat: {e}", "white")
                    continue

                try:
                    state, res = _test_bat_isolated(
                        tmp_bat, exe, pool, services, stop_check,
                        timeout=4.0, retries=2, stop_on_fail=True,
                    )
                except Exception as e:
                    _rm(tmp_bat)
                    with lock:
                        self.log.emit(f"\n▶ Attempt {idx + 1}/{total}: {name}", "white")
                        self.log.emit(f"  Error: {e}", "white")
                    continue

                if state == "stopped":
                    _rm(tmp_bat)
                    return

                with lock:
                    if stop_check():
                        _rm(tmp_bat)
                        return

                    self.log.emit(f"\n▶ Attempt {idx + 1}/{total}: {name}", "white")
                    if state == "unparsable":
                        self.log.emit("  Cannot parse generated bat, skipping", "dim")
                        _rm(tmp_bat)
                        continue
                    if state == "start_failed":
                        self.log.emit("  winws did not start", "dim")
                        _rm(tmp_bat)
                        continue

                    for svc, ok, _lat, ip in res:
                        self.log.emit(f"    {svc}: {'✓' if ok else '✗'} (ip={ip or '?'})",
                                      "white" if ok else "dim")

                    all_ok = len(res) == len(services) and all(r[1] for r in res)
                    if not all_ok:
                        _rm(tmp_bat)
                        self.log.emit("  ✗ No access, trying next...", "dim")
                        continue

                    if enough.is_set() or created[0] >= self.num_configs:
                        self.log.emit("  Working, but the requested number of configs is already found — skipped.", "dim")
                        _rm(tmp_bat)
                        return

                    if _is_strategy_existing(self.zapret_dir, args, name) or name in created_names:
                        self.log.emit("  That config already exists.", "#9370DB")
                        _rm(tmp_bat)
                        continue

                    created[0] += 1
                    created_names.add(name)
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

                    self.log.emit(f"\n✅  Working config #{created[0]}/{self.num_configs} found: {final_name}", "white")
                    self.log.emit(f"  Strategy: {name}", "dim")
                    self.success.emit(final_name)

                    if created[0] >= self.num_configs:
                        enough.set()
                        return

        n_threads = PARALLEL_SLOTS
        pools = _make_slot_pools(n_threads)
        threads = [threading.Thread(target=slot_worker, args=(p,), daemon=True) for p in pools]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        _kill_winws()

        # Подчистка возможных хвостов _test_custom_*.bat
        for leftover in self.zapret_dir.glob("_test_custom_*.bat"):
            _rm(leftover)

        created_count = created[0]
        if self._stop:
            self.log.emit("\n⛔  Route creation stopped.", "white")
        elif created_count == 0:
            self.log.emit("\n✗  All strategies exhausted. No working route found.", "white")
        else:
            self.log.emit(f"\n✅  Finished. Created {created_count}/{self.num_configs} route(s).", "white")

        self.finished.emit()


# ══════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setFixedSize(WINDOW_W, WINDOW_H)

        # Paths
        self._app_dir = get_app_dir()
        self._settings_dir = get_settings_dir(self._app_dir)
        self._zapret_dir = self._find_zapret_dir()
        self._cfg_file = self._settings_dir / "zapret_settings.json"
        self._app_settings_file = self._settings_dir / "app_settings.json"

        # App settings (transparency, custom colors, update check)
        self._transparency = 100
        self._color1 = "#0a0a0a"
        self._color2 = "#ffffff"
        self._text_color = "#e0e0e0"
        self._check_update = True
        self._auto_download = False
        self._wallpaper_path: Path | None = None
        self._load_app_settings()

        has_wall = bool(self._wallpaper_path and self._wallpaper_path.exists())
        self._current_stylesheet = build_stylesheet(self._color1, self._color2, self._text_color, has_wallpaper=has_wall)
        self.setStyleSheet(self._current_stylesheet)
        self.setWindowOpacity(self._transparency / 100.0)

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
        self._bat_ranks: dict[str, int] = {}
        self._test_worker: TestWorker | None = None
        self._test_selected_worker: TestSelectedWorker | None = None
        self._create_worker: CreateWorker | None = None
        self._connect_worker: ConnectWorker | None = None
        self._dark_applied = False

        self._auto_connect = False
        self._auto_start = False
        self._tg_auto_connect = False
        self._multi_ping = True

        self._tg_manager = TgProxyManager.get(self._app_dir)
        self._tg_config = self._tg_manager.config
        self._cfproxy_test_worker: CfProxyTestWorker | None = None
        self._cfworker_test_worker: CfWorkerTestWorker | None = None

        self._load_settings()
        if "auto_connect" in self._tg_config:
            self._tg_auto_connect = bool(self._tg_config.get("auto_connect", False))

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

        if self._tg_auto_connect and not self._tg_manager.is_running():
            QTimer.singleShot(500, self._tg_start_proxy_silent)

        if self._check_update:
            QTimer.singleShot(1500, self._start_startup_update_check)

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
                                      ".git", "venv", ".venv", "settings"):
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
        legacy_file = self._app_dir / "zapret_settings.json"
        target_file = None
        if self._cfg_file.exists():
            target_file = self._cfg_file
        elif legacy_file.exists():
            target_file = legacy_file

        if target_file and target_file.exists():
            try:
                d = json.loads(target_file.read_text(encoding="utf-8"))
                self._current_bat = d.get("last_bat")
                self._auto_connect = d.get("auto_connect", False)
                self._auto_start = d.get("auto_start", False)
                self._tg_auto_connect = d.get("tg_auto_connect", False)
                self._multi_ping = d.get("multi_ping", True)
                self._apply_auto_start()
                if target_file == legacy_file:
                    self._save_settings()
                    try:
                        legacy_file.unlink()
                    except Exception:
                        pass
            except Exception:
                pass

    def _save_settings(self):
        try:
            self._settings_dir.mkdir(parents=True, exist_ok=True)
            self._cfg_file.write_text(
                json.dumps({
                    "last_bat": self._current_bat,
                    "auto_connect": self._auto_connect,
                    "auto_start": self._auto_start,
                    "tg_auto_connect": self._tg_auto_connect,
                    "multi_ping": self._multi_ping,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _apply_auto_start(self):
        # Apply Task Scheduler autostart and clean up legacy entries
        if self._auto_start:
            enable_autostart(elevate=False)
        else:
            disable_autostart(elevate=False)

    def _sync_autostart_ui(self):
        """Dynamically sync checkbox with real Windows Task Scheduler state."""
        if hasattr(self, "_chk_autostart"):
            real_state = is_autostart_enabled()
            self._chk_autostart.blockSignals(True)
            self._chk_autostart.setChecked(real_state)
            self._chk_autostart.blockSignals(False)
            if self._auto_start != real_state:
                self._auto_start = real_state
                self._save_settings()

    # ── UI Build ──────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        self._wallpaper_widget = WallpaperWidget(root, color1=self._color1)
        self._wallpaper_widget.setGeometry(0, 0, WINDOW_W, WINDOW_H)
        self._wallpaper_widget.lower()
        if self._wallpaper_path and self._wallpaper_path.exists():
            self._wallpaper_widget.set_wallpaper(self._wallpaper_path)

        vlay = QVBoxLayout(root)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        # Tab bar
        self._tab_bar = QWidget()
        self._tab_bar.setObjectName("tabBar")
        self._tab_bar.setFixedHeight(46)
        tb = QHBoxLayout(self._tab_bar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(0)

        self._tab_connect = self._mk_tab("Connect")
        self._tab_create = self._mk_tab("Create")
        self._tab_test = self._mk_tab("Test")
        self._tab_utils = self._mk_tab("Utils")

        self._tab_connect.clicked.connect(lambda: self._switch(0))
        self._tab_create.clicked.connect(lambda: self._switch(1))
        self._tab_test.clicked.connect(lambda: self._switch(2))
        self._tab_utils.clicked.connect(lambda: self._switch(3))

        tb.addWidget(self._tab_connect)
        tb.addWidget(self._tab_create)
        tb.addWidget(self._tab_test)
        tb.addWidget(self._tab_utils)
        vlay.addWidget(self._tab_bar)

        # Pages
        self._pg_connect = self._build_connect_page()
        self._pg_create = self._build_create_page()
        self._pg_test = self._build_test_page()
        self._pg_utils = self._build_utils_page()
        self._pg_app_settings = self._build_app_settings_page()
        self._pg_app_settings.setVisible(False)

        vlay.addWidget(self._pg_connect, 1)
        vlay.addWidget(self._pg_create, 1)
        vlay.addWidget(self._pg_test, 1)
        vlay.addWidget(self._pg_utils, 1)
        vlay.addWidget(self._pg_app_settings, 1)

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
        self._pg_app_settings.setVisible(False)
        self._tab_bar.setVisible(True)
        self._pg_connect.setVisible(idx == 0)
        self._pg_create.setVisible(idx == 1)
        self._pg_test.setVisible(idx == 2)
        self._pg_utils.setVisible(idx == 3)
        for i, b in enumerate([self._tab_connect, self._tab_create, self._tab_test, self._tab_utils]):
            b.setProperty("active", "true" if i == idx else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self._sync_autostart_ui()

    def _open_app_settings(self):
        self._tab_bar.setVisible(False)
        self._pg_connect.setVisible(False)
        self._pg_create.setVisible(False)
        self._pg_test.setVisible(False)
        self._pg_utils.setVisible(False)
        self._pg_app_settings.setVisible(True)
        self._switch_app_settings(0)

    def _close_app_settings(self):
        self._pg_app_settings.setVisible(False)
        self._tab_bar.setVisible(True)
        self._switch(0)

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
        self._config_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._config_list.customContextMenuRequested.connect(self._on_config_context_menu)
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
        chk_row.setSpacing(16)
        self._chk_autostart = QCheckBox("Autostart")
        self._chk_autostart.setChecked(self._auto_start)
        self._chk_autostart.toggled.connect(self._on_autostart_changed)

        self._chk_autoconnect = QCheckBox("Auto-connect")
        self._chk_autoconnect.setChecked(self._auto_connect)
        self._chk_autoconnect.toggled.connect(self._on_autoconnect_changed)

        self._btn_settings = QPushButton("settings")
        self._btn_settings.setObjectName("actionBtn")
        self._btn_settings.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_settings.clicked.connect(self._open_app_settings)

        chk_row.addWidget(self._chk_autostart)
        chk_row.addWidget(self._chk_autoconnect)
        chk_row.addWidget(self._btn_settings)
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

        target_lbl = QLabel("TARGETS")
        target_lbl.setObjectName("sectionLbl")
        left_lay.addWidget(target_lbl)

        target_row = QHBoxLayout()
        target_row.setSpacing(20)
        self._chk_target_discord = QCheckBox("Discord")
        self._chk_target_discord.setChecked(True)
        self._chk_target_youtube = QCheckBox("YouTube")
        self._chk_target_youtube.setChecked(True)
        target_row.addWidget(self._chk_target_discord)
        target_row.addWidget(self._chk_target_youtube)
        target_row.addStretch()
        left_lay.addLayout(target_row)
        left_lay.addSpacing(10)

        # Number of configs slider
        self._lbl_num_configs_title = QLabel("NUMBER OF CONFIGS: 1")
        self._lbl_num_configs_title.setObjectName("sectionLbl")
        left_lay.addWidget(self._lbl_num_configs_title)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)

        self._slider_num_configs = QSlider(Qt.Orientation.Horizontal)
        self._slider_num_configs.setMinimum(1)
        self._slider_num_configs.setMaximum(10)
        self._slider_num_configs.setValue(1)
        self._slider_num_configs.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider_num_configs.setTickInterval(1)
        self._slider_num_configs.setSingleStep(1)
        self._slider_num_configs.setPageStep(1)
        self._slider_num_configs.setFixedHeight(22)
        self._slider_num_configs.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._slider_num_configs.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #1a1a1a;
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #cccccc;
            }
            QSlider::sub-page:horizontal {
                background: #888888;
                border-radius: 2px;
            }
            QSlider::add-page:horizontal {
                background: #1a1a1a;
                border-radius: 2px;
            }
        """)

        slider_row.addWidget(self._slider_num_configs, 1)
        left_lay.addLayout(slider_row)

        ticks_row = QHBoxLayout()
        ticks_row.setContentsMargins(6, 0, 6, 0)
        for val in [str(i) for i in range(1, 11)]:
            t_lbl = QLabel(val)
            t_lbl.setStyleSheet("color: #555; font-size: 10px; font-weight: 600; background: transparent;")
            t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ticks_row.addWidget(t_lbl)
        left_lay.addLayout(ticks_row)

        self._slider_num_configs.valueChanged.connect(
            lambda v: self._lbl_num_configs_title.setText(f"NUMBER OF CONFIGS: {v}")
        )
        left_lay.addSpacing(10)

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
    #  TEST PAGE — buttons left, console right
    # ══════════════════════════════════════════════════════════════

    def _build_test_page(self) -> QWidget:
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
        self._btn_test.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_test.setToolTip("Test all configs and rank TOP 3 on the left")
        self._btn_test.setProperty("testing", "false")
        self._btn_test.clicked.connect(self._toggle_testing)
        left_lay.addWidget(self._btn_test)

        self._btn_test_selected = QPushButton("Test Selected Config")
        self._btn_test_selected.setObjectName("testBtn")
        self._btn_test_selected.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_test_selected.setToolTip("Test connectivity of the currently selected config")
        self._btn_test_selected.setProperty("testing", "false")
        self._btn_test_selected.clicked.connect(self._toggle_test_selected)
        left_lay.addWidget(self._btn_test_selected)

        self._btn_clear = QPushButton("Clear Log")
        self._btn_clear.setObjectName("actionBtn")
        self._btn_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_clear.clicked.connect(self._console_clear)
        left_lay.addWidget(self._btn_clear)

        left_lay.addSpacing(6)

        opt_lbl = QLabel("OPTIONS")
        opt_lbl.setObjectName("sectionLbl")
        left_lay.addWidget(opt_lbl)

        self._chk_multi_ping = QCheckBox("Multi-ping")
        self._chk_multi_ping.setChecked(self._multi_ping)
        self._chk_multi_ping.setToolTip("Test 3 configs simultaneously in parallel slots")
        self._chk_multi_ping.toggled.connect(self._on_multi_ping_toggled)
        left_lay.addWidget(self._chk_multi_ping)

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

    # ══════════════════════════════════════════════════════════════
    #  UTILS PAGE — TG WS Proxy integration (1 to 1)
    # ══════════════════════════════════════════════════════════════

    def _build_utils_page(self) -> QWidget:
        w = QWidget()
        hlay = QHBoxLayout(w)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)

        # ── Left panel: Status, Quick Actions, Console ──
        left = QWidget()
        left.setObjectName("panelLeft")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(16, 14, 16, 14)
        left_lay.setSpacing(8)

        lbl = QLabel("TG WS PROXY")
        lbl.setObjectName("sectionLbl")
        left_lay.addWidget(lbl)
        left_lay.addSpacing(2)

        # Status card
        status_box = QWidget()
        status_box.setObjectName("tgStatusBox")
        status_box.setStyleSheet(
            "QWidget#tgStatusBox { background: #111111; border: 1px solid #1c1c1c; border-radius: 6px; }"
        )
        sbox_lay = QVBoxLayout(status_box)
        sbox_lay.setContentsMargins(10, 10, 10, 10)
        sbox_lay.setSpacing(6)

        self._tg_status_lbl = QLabel("○ STOPPED")
        self._tg_status_lbl.setStyleSheet(
            "color: #777; font-size: 13px; font-weight: 700; background: transparent; border: none;"
        )
        sbox_lay.addWidget(self._tg_status_lbl)

        self._tg_info_lbl = QLabel("127.0.0.1:1443")
        self._tg_info_lbl.setStyleSheet(
            "color: #555; font-size: 11px; background: transparent; border: none;"
        )
        sbox_lay.addWidget(self._tg_info_lbl)

        # Start / Stop and Restart buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_tg_toggle = QPushButton("Start Proxy")
        self._btn_tg_toggle.setObjectName("startBtn")
        self._btn_tg_toggle.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_toggle.clicked.connect(self._tg_toggle_proxy)

        self._btn_tg_restart = QPushButton("Restart")
        self._btn_tg_restart.setObjectName("actionBtn")
        self._btn_tg_restart.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_restart.clicked.connect(self._tg_restart_proxy)

        btn_row.addWidget(self._btn_tg_toggle, 1)
        btn_row.addWidget(self._btn_tg_restart)
        sbox_lay.addLayout(btn_row)

        left_lay.addWidget(status_box)
        left_lay.addSpacing(6)

        # Telegram integration actions
        tg_act_lbl = QLabel("ACTIONS")
        tg_act_lbl.setObjectName("sectionLbl")
        left_lay.addWidget(tg_act_lbl)

        self._btn_tg_open = QPushButton("Connect a Telegram proxy")
        self._btn_tg_open.setObjectName("actionBtn")
        self._btn_tg_open.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_open.clicked.connect(self._tg_open_telegram)
        left_lay.addWidget(self._btn_tg_open)

        self._btn_tg_copy = QPushButton("Copy Proxy Link")
        self._btn_tg_copy.setObjectName("actionBtn")
        self._btn_tg_copy.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_copy.clicked.connect(self._tg_copy_link)
        left_lay.addWidget(self._btn_tg_copy)

        self._btn_tg_logs = QPushButton("Open Log File")
        self._btn_tg_logs.setObjectName("actionBtn")
        self._btn_tg_logs.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_logs.clicked.connect(self._tg_open_log_file)
        left_lay.addWidget(self._btn_tg_logs)

        left_lay.addSpacing(6)

        # Options: Auto-connect
        opt_lbl = QLabel("OPTIONS")
        opt_lbl.setObjectName("sectionLbl")
        left_lay.addWidget(opt_lbl)

        self._chk_tg_autoconnect = QCheckBox("Auto-connect with start")
        self._chk_tg_autoconnect.setChecked(self._tg_auto_connect)
        self._chk_tg_autoconnect.setToolTip("Start TG WS Proxy automatically on application launch")
        self._chk_tg_autoconnect.toggled.connect(self._tg_on_autoconnect_toggled)
        left_lay.addWidget(self._chk_tg_autoconnect)

        left_lay.addSpacing(6)

        # Console header & Clear
        con_row = QHBoxLayout()
        con_lbl = QLabel("OUTPUT")
        con_lbl.setObjectName("sectionLbl")
        con_row.addWidget(con_lbl)
        con_row.addStretch()
        btn_tg_clear = QPushButton("Clear")
        btn_tg_clear.setObjectName("actionBtn")
        btn_tg_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_tg_clear.clicked.connect(lambda: self._tg_console.clear())
        con_row.addWidget(btn_tg_clear)
        left_lay.addLayout(con_row)

        self._tg_console = QTextEdit()
        self._tg_console.setObjectName("console")
        self._tg_console.setReadOnly(True)
        self._tg_console.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        left_lay.addWidget(self._tg_console, 1)

        hlay.addWidget(left, 35)

        # ── Right panel: Full Settings Form (ScrollArea) ──
        right = QWidget()
        right.setObjectName("panelRight")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setObjectName("utilsScrollArea")

        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        content_lay.setContentsMargins(18, 14, 20, 16)
        content_lay.setSpacing(12)

        # Section 1: MTProto Connection
        s1_lbl = QLabel("CONNECTION (MTPROTO)")
        s1_lbl.setObjectName("sectionLbl")
        content_lay.addWidget(s1_lbl)

        row_host_port = QHBoxLayout()
        row_host_port.setSpacing(10)

        col_host = QVBoxLayout()
        col_host.setSpacing(4)
        lbl_h = QLabel("Host / IP Address")
        lbl_h.setStyleSheet("color: #777; font-size: 11px;")
        self._tg_inp_host = QLineEdit()
        self._tg_inp_host.setToolTip("Proxy listen address (usually 127.0.0.1 or 0.0.0.0)")
        col_host.addWidget(lbl_h)
        col_host.addWidget(self._tg_inp_host)
        row_host_port.addLayout(col_host, 2)

        col_port = QVBoxLayout()
        col_port.setSpacing(4)
        lbl_p = QLabel("Port")
        lbl_p.setStyleSheet("color: #777; font-size: 11px;")
        self._tg_inp_port = QLineEdit()
        self._tg_inp_port.setToolTip("Proxy port (1-65535, default: 1443)")
        col_port.addWidget(lbl_p)
        col_port.addWidget(self._tg_inp_port)
        row_host_port.addLayout(col_port, 1)
        content_lay.addLayout(row_host_port)

        col_sec = QVBoxLayout()
        col_sec.setSpacing(4)
        lbl_s = QLabel("Secret Key (32 hex characters)")
        lbl_s.setStyleSheet("color: #777; font-size: 11px;")
        sec_row = QHBoxLayout()
        sec_row.setSpacing(6)
        self._tg_inp_secret = QLineEdit()
        self._tg_inp_secret.setToolTip("32-character hexadecimal secret key")
        btn_gen_sec = QPushButton("↺")
        btn_gen_sec.setObjectName("iconBtn")
        btn_gen_sec.setFixedSize(32, 32)
        btn_gen_sec.setToolTip("Generate random secret")
        btn_gen_sec.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_gen_sec.clicked.connect(self._tg_generate_secret)
        sec_row.addWidget(self._tg_inp_secret, 1)
        sec_row.addWidget(btn_gen_sec)
        col_sec.addWidget(lbl_s)
        col_sec.addLayout(sec_row)
        content_lay.addLayout(col_sec)

        content_lay.addSpacing(14)

        # Section 2: Data Centers (DC → IP)
        s2_lbl = QLabel("TELEGRAM DATA CENTERS (DC → IP)")
        s2_lbl.setObjectName("sectionLbl")
        content_lay.addWidget(s2_lbl)

        dc_hint = QLabel("One rule per line, format: DC:IP (e.g. 2:149.154.167.220)")
        dc_hint.setStyleSheet("color: #555; font-size: 11px;")
        content_lay.addWidget(dc_hint)

        self._tg_txt_dc = QTextEdit()
        self._tg_txt_dc.setObjectName("settingText")
        self._tg_txt_dc.setFixedHeight(68)
        self._tg_txt_dc.setToolTip("Mapping of Telegram DC to server IP")
        content_lay.addWidget(self._tg_txt_dc)

        content_lay.addSpacing(20)

        # Section 3: Cloudflare Proxy
        s3_lbl = QLabel("CLOUDFLARE PROXY")
        s3_lbl.setObjectName("sectionLbl")
        content_lay.addWidget(s3_lbl)

        cf_top_row = QHBoxLayout()
        cf_top_row.setSpacing(12)
        self._tg_chk_cfproxy = QCheckBox("Enable CF-proxy")
        self._tg_chk_cfproxy.setToolTip("Route blocked Telegram data centers via Cloudflare proxy")
        self._btn_test_cfproxy = QPushButton("Test CF-Proxy")
        self._btn_test_cfproxy.setObjectName("actionBtn")
        self._btn_test_cfproxy.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_test_cfproxy.clicked.connect(self._tg_start_cfproxy_test)
        cf_top_row.addWidget(self._tg_chk_cfproxy)
        cf_top_row.addStretch()
        cf_top_row.addWidget(self._btn_test_cfproxy)
        content_lay.addLayout(cf_top_row)

        self._tg_chk_h2 = QCheckBox("Media multiplexing (HTTP/2)")
        self._tg_chk_h2.setToolTip("Multiplex media downloads through Cloudflare into a single HTTP/2 connection")
        content_lay.addWidget(self._tg_chk_h2)

        cf_custom_row = QHBoxLayout()
        cf_custom_row.setSpacing(8)
        self._tg_chk_custom_cf = QCheckBox("Custom domains:")
        self._tg_chk_custom_cf.setToolTip("Specify custom domains instead of automatic domain selection")
        self._tg_inp_custom_cf = QLineEdit()
        self._tg_inp_custom_cf.setPlaceholderText("example1.com, example2.com")
        self._tg_inp_custom_cf.setToolTip("Custom domains proxied through Cloudflare (comma-separated)")
        cf_custom_row.addWidget(self._tg_chk_custom_cf)
        cf_custom_row.addWidget(self._tg_inp_custom_cf, 1)
        content_lay.addLayout(cf_custom_row)

        content_lay.addSpacing(16)

        # Section 4: Cloudflare Worker
        s4_lbl = QLabel("CLOUDFLARE WORKER")
        s4_lbl.setObjectName("sectionLbl")
        content_lay.addWidget(s4_lbl)

        cfw_top_row = QHBoxLayout()
        cfw_top_row.setSpacing(12)
        self._tg_chk_cfworker = QCheckBox("Enable CF Worker")
        self._tg_chk_cfworker.setToolTip("Route Telegram traffic through custom Cloudflare Worker script")
        self._btn_test_cfworker = QPushButton("Test CF Worker")
        self._btn_test_cfworker.setObjectName("actionBtn")
        self._btn_test_cfworker.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_test_cfworker.clicked.connect(self._tg_start_cfworker_test)
        cfw_top_row.addWidget(self._tg_chk_cfworker)
        cfw_top_row.addStretch()
        cfw_top_row.addWidget(self._btn_test_cfworker)
        content_lay.addLayout(cfw_top_row)

        cfw_inp_row = QHBoxLayout()
        cfw_inp_row.setSpacing(8)
        lbl_w = QLabel("Worker domains:")
        lbl_w.setStyleSheet("color: #777; font-size: 11px;")
        self._tg_inp_cfworker = QLineEdit()
        self._tg_inp_cfworker.setPlaceholderText("name.account.workers.dev")
        self._tg_inp_cfworker.setToolTip("Cloudflare Worker domains (comma-separated)")
        cfw_inp_row.addWidget(lbl_w)
        cfw_inp_row.addWidget(self._tg_inp_cfworker, 1)
        content_lay.addLayout(cfw_inp_row)

        content_lay.addSpacing(16)

        # Section 5: Logs & Performance
        s5_lbl = QLabel("LOGS & PERFORMANCE")
        s5_lbl.setObjectName("sectionLbl")
        content_lay.addWidget(s5_lbl)

        logs_chk_row = QHBoxLayout()
        logs_chk_row.setSpacing(16)
        self._tg_chk_verbose = QCheckBox("Verbose logging")
        self._tg_chk_verbose.setToolTip("Write detailed debug logs to proxy.log")
        self._tg_chk_no_secure = QCheckBox("Disable TLS (plain HTTP)")
        self._tg_chk_no_secure.setToolTip("Use port 80 without TLS encryption for CF-proxy & CF-worker")
        logs_chk_row.addWidget(self._tg_chk_verbose)
        logs_chk_row.addWidget(self._tg_chk_no_secure)
        logs_chk_row.addStretch()
        content_lay.addLayout(logs_chk_row)

        perf_row = QHBoxLayout()
        perf_row.setSpacing(10)

        col_buf = QVBoxLayout()
        col_buf.setSpacing(4)
        lbl_buf = QLabel("Buffer (KB)")
        lbl_buf.setStyleSheet("color: #777; font-size: 11px;")
        self._tg_inp_buf = QLineEdit()
        self._tg_inp_buf.setToolTip("Socket buffer size in KB (default: 256)")
        col_buf.addWidget(lbl_buf)
        col_buf.addWidget(self._tg_inp_buf)
        perf_row.addLayout(col_buf, 1)

        col_pool = QVBoxLayout()
        col_pool.setSpacing(4)
        lbl_pool = QLabel("WS Pool Size")
        lbl_pool.setStyleSheet("color: #777; font-size: 11px;")
        self._tg_inp_pool = QLineEdit()
        self._tg_inp_pool.setToolTip("Ready WebSocket connections pool per DC (default: 4)")
        col_pool.addWidget(lbl_pool)
        col_pool.addWidget(self._tg_inp_pool)
        perf_row.addLayout(col_pool, 1)

        col_log_mb = QVBoxLayout()
        col_log_mb.setSpacing(4)
        lbl_lmb = QLabel("Max Log (MB)")
        lbl_lmb.setStyleSheet("color: #777; font-size: 11px;")
        self._tg_inp_log_mb = QLineEdit()
        self._tg_inp_log_mb.setToolTip("Maximum size of proxy.log in MB (default: 5)")
        col_log_mb.addWidget(lbl_lmb)
        col_log_mb.addWidget(self._tg_inp_log_mb)
        perf_row.addLayout(col_log_mb, 1)

        content_lay.addLayout(perf_row)

        content_lay.addSpacing(10)

        # Section 6: Action buttons
        act_row = QHBoxLayout()
        act_row.setSpacing(10)

        self._btn_tg_save = QPushButton("Save Settings")
        self._btn_tg_save.setObjectName("createBtn")
        self._btn_tg_save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_save.clicked.connect(self._tg_save_settings)

        self._btn_tg_reset = QPushButton("Reset Defaults")
        self._btn_tg_reset.setObjectName("actionBtn")
        self._btn_tg_reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_tg_reset.clicked.connect(self._tg_reset_defaults)

        act_row.addWidget(self._btn_tg_save)
        act_row.addWidget(self._btn_tg_reset)
        act_row.addStretch()
        content_lay.addLayout(act_row)

        self._tg_feedback_lbl = QLabel("")
        self._tg_feedback_lbl.setStyleSheet("color: #888; font-size: 12px; font-weight: 600;")
        content_lay.addWidget(self._tg_feedback_lbl)

        content_lay.addStretch()

        scroll.setWidget(content)
        right_lay.addWidget(scroll)
        hlay.addWidget(right, 65)

        # Synchronize dependent widget states
        self._tg_sync_subcontrols()
        self._tg_chk_cfproxy.toggled.connect(self._tg_sync_subcontrols)
        self._tg_chk_custom_cf.toggled.connect(self._tg_sync_subcontrols)
        self._tg_chk_cfworker.toggled.connect(self._tg_sync_subcontrols)

        # Populate form with current config
        self._tg_populate_form(self._tg_config)
        self._tg_refresh_status_ui()

        return w

    # ══════════════════════════════════════════════════════════════
    #  APP SETTINGS PAGE (Fullscreen Settings Mode)
    # ══════════════════════════════════════════════════════════════

    def _build_app_settings_page(self) -> QWidget:
        w = QWidget()
        hlay = QHBoxLayout(w)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)

        # ── Left panel: Back button + vertical tabs ──
        left = QWidget()
        left.setObjectName("panelLeft")
        left.setFixedWidth(180)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(14, 14, 14, 14)
        left_lay.setSpacing(8)

        # Back button in top-left corner
        self._btn_settings_back = QPushButton("← back")
        self._btn_settings_back.setObjectName("actionBtn")
        self._btn_settings_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_settings_back.setFixedHeight(34)
        self._btn_settings_back.clicked.connect(self._close_app_settings)
        left_lay.addWidget(self._btn_settings_back)

        left_lay.addSpacing(12)

        lbl = QLabel("SETTINGS")
        lbl.setObjectName("sectionLbl")
        left_lay.addWidget(lbl)
        left_lay.addSpacing(4)

        # Category tabs (vertical)
        self._side_tab_ui = self._mk_side_tab("UI")
        self._side_tab_set_ip = self._mk_side_tab("Set IP")
        self._side_tab_update = self._mk_side_tab("Update")
        self._side_tab_about = self._mk_side_tab("About")

        self._side_tab_ui.clicked.connect(lambda: self._switch_app_settings(0))
        self._side_tab_set_ip.clicked.connect(lambda: self._switch_app_settings(1))
        self._side_tab_update.clicked.connect(lambda: self._switch_app_settings(2))
        self._side_tab_about.clicked.connect(lambda: self._switch_app_settings(3))

        left_lay.addWidget(self._side_tab_ui)
        left_lay.addWidget(self._side_tab_set_ip)
        left_lay.addWidget(self._side_tab_update)
        left_lay.addStretch()
        left_lay.addWidget(self._side_tab_about)

        hlay.addWidget(left)

        # Divider
        divider = QWidget()
        divider.setObjectName("panelDivider")
        hlay.addWidget(divider)

        # ── Right panel: settings pages ──
        right = QWidget()
        right.setObjectName("panelRight")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(32, 24, 32, 24)
        right_lay.setSpacing(0)

        self._subpage_ui = self._build_settings_ui_subpage()
        self._subpage_set_ip = self._build_settings_set_ip_subpage()
        self._subpage_update = self._build_settings_update_subpage()
        self._subpage_about = self._build_settings_about_subpage()

        right_lay.addWidget(self._subpage_ui, 1)
        right_lay.addWidget(self._subpage_set_ip, 1)
        right_lay.addWidget(self._subpage_update, 1)
        right_lay.addWidget(self._subpage_about, 1)

        hlay.addWidget(right, 1)
        return w

    def _mk_side_tab(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("settingsSideTab")
        b.setProperty("active", "false")
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFixedHeight(38)
        return b

    def _switch_app_settings(self, idx: int):
        self._subpage_ui.setVisible(idx == 0)
        self._subpage_set_ip.setVisible(idx == 1)
        self._subpage_update.setVisible(idx == 2)
        self._subpage_about.setVisible(idx == 3)
        for i, b in enumerate([self._side_tab_ui, self._side_tab_set_ip, self._side_tab_update, self._side_tab_about]):
            b.setProperty("active", "true" if i == idx else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        if idx == 1:
            self._refresh_set_ip_info()

    def _build_settings_ui_subpage(self) -> QWidget:
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(18)

        lbl = QLabel("UI SETTINGS")
        lbl.setObjectName("sectionLbl")
        vlay.addWidget(lbl)

        # ── 1. Transparency ──
        trans_box = QWidget()
        tb_lay = QVBoxLayout(trans_box)
        tb_lay.setContentsMargins(0, 0, 0, 0)
        tb_lay.setSpacing(6)

        t_lbl = QLabel("transparency")
        t_lbl.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent;")
        tb_lay.addWidget(t_lbl)

        t_row = QHBoxLayout()
        t_row.setSpacing(14)

        self._slider_transparency = QSlider(Qt.Orientation.Horizontal)
        self._slider_transparency.setRange(30, 100)
        self._slider_transparency.setValue(self._transparency)
        self._slider_transparency.setFixedHeight(22)
        self._slider_transparency.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._slider_transparency.valueChanged.connect(self._on_slider_transparency_changed)

        self._input_transparency = QLineEdit(f"{self._transparency}%")
        self._input_transparency.setFixedWidth(64)
        self._input_transparency.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._input_transparency.editingFinished.connect(self._on_input_transparency_changed)

        t_row.addWidget(self._slider_transparency, 1)
        t_row.addWidget(self._input_transparency)
        tb_lay.addLayout(t_row)
        vlay.addWidget(trans_box)

        # ── 2. Color 1 ──
        c1_box = QWidget()
        c1_lay = QHBoxLayout(c1_box)
        c1_lay.setContentsMargins(0, 0, 0, 0)
        c1_lay.setSpacing(12)

        c1_lbl = QLabel("Color 1")
        c1_lbl.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent; min-width: 85px;")

        self._btn_color1 = QPushButton()
        self._btn_color1.setFixedSize(36, 28)
        self._btn_color1.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_color1.clicked.connect(self._pick_color_1)

        self._lbl_hex_color1 = QLabel(self._color1.upper())
        self._lbl_hex_color1.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; background: transparent; min-width: 75px;")

        c1_desc = QLabel("Primary background color")
        c1_desc.setObjectName("infoLbl")

        c1_lay.addWidget(c1_lbl)
        c1_lay.addWidget(self._btn_color1)
        c1_lay.addWidget(self._lbl_hex_color1)
        c1_lay.addWidget(c1_desc)
        c1_lay.addStretch()
        vlay.addWidget(c1_box)

        # ── 3. Color 2 ──
        c2_box = QWidget()
        c2_lay = QHBoxLayout(c2_box)
        c2_lay.setContentsMargins(0, 0, 0, 0)
        c2_lay.setSpacing(12)

        c2_lbl = QLabel("Color 2")
        c2_lbl.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent; min-width: 85px;")

        self._btn_color2 = QPushButton()
        self._btn_color2.setFixedSize(36, 28)
        self._btn_color2.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_color2.clicked.connect(self._pick_color_2)

        self._lbl_hex_color2 = QLabel(self._color2.upper())
        self._lbl_hex_color2.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; background: transparent; min-width: 75px;")

        c2_desc = QLabel("Secondary accent & highlight color")
        c2_desc.setObjectName("infoLbl")

        c2_lay.addWidget(c2_lbl)
        c2_lay.addWidget(self._btn_color2)
        c2_lay.addWidget(self._lbl_hex_color2)
        c2_lay.addWidget(c2_desc)
        c2_lay.addStretch()
        vlay.addWidget(c2_box)

        # ── 4. Text color ──
        ct_box = QWidget()
        ct_lay = QHBoxLayout(ct_box)
        ct_lay.setContentsMargins(0, 0, 0, 0)
        ct_lay.setSpacing(12)

        ct_lbl = QLabel("Text color")
        ct_lbl.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent; min-width: 85px;")

        self._btn_text_color = QPushButton()
        self._btn_text_color.setFixedSize(36, 28)
        self._btn_text_color.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_text_color.clicked.connect(self._pick_text_color)

        self._lbl_hex_text_color = QLabel(self._text_color.upper())
        self._lbl_hex_text_color.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px; background: transparent; min-width: 75px;")

        ct_desc = QLabel("Application text & labels color")
        ct_desc.setObjectName("infoLbl")

        ct_lay.addWidget(ct_lbl)
        ct_lay.addWidget(self._btn_text_color)
        ct_lay.addWidget(self._lbl_hex_text_color)
        ct_lay.addWidget(ct_desc)
        ct_lay.addStretch()
        vlay.addWidget(ct_box)

        vlay.addSpacing(10)

        # ── Set Default ──
        def_row = QHBoxLayout()
        def_row.setSpacing(12)

        self._btn_set_default = QPushButton("Set Default")
        self._btn_set_default.setObjectName("actionBtn")
        self._btn_set_default.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_set_default.setFixedWidth(120)
        self._btn_set_default.setFixedHeight(34)
        self._btn_set_default.clicked.connect(self._reset_ui_defaults)

        def_lbl = QLabel("Restore default interface style (Minimalist B&W, 100% opacity)")
        def_lbl.setObjectName("infoLbl")

        def_row.addWidget(self._btn_set_default)
        def_row.addWidget(def_lbl)
        def_row.addStretch()
        vlay.addLayout(def_row)

        # ── Set as wallpaper ──
        wall_row = QHBoxLayout()
        wall_row.setSpacing(12)

        self._btn_set_wallpaper = QPushButton("Set as wallpaper")
        self._btn_set_wallpaper.setObjectName("actionBtn")
        self._btn_set_wallpaper.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_set_wallpaper.setFixedWidth(125)
        self._btn_set_wallpaper.setFixedHeight(34)
        self._btn_set_wallpaper.clicked.connect(self._pick_wallpaper)

        self._btn_clear_wallpaper = QPushButton("Clear")
        self._btn_clear_wallpaper.setObjectName("actionBtn")
        self._btn_clear_wallpaper.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_clear_wallpaper.setFixedWidth(70)
        self._btn_clear_wallpaper.setFixedHeight(34)
        self._btn_clear_wallpaper.clicked.connect(self._clear_wallpaper_clicked)
        self._btn_clear_wallpaper.setVisible(bool(self._wallpaper_path and self._wallpaper_path.exists()))

        self._lbl_wallpaper_info = QLabel(f"Add a photo or GIF to the background (recommended: 800x600)")
        self._lbl_wallpaper_info.setObjectName("infoLbl")

        wall_row.addWidget(self._btn_set_wallpaper)
        wall_row.addWidget(self._btn_clear_wallpaper)
        wall_row.addWidget(self._lbl_wallpaper_info)
        wall_row.addStretch()
        vlay.addLayout(wall_row)

        vlay.addStretch()
        self._update_color_previews()
        return w

    def _build_settings_set_ip_subpage(self) -> QWidget:
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(16)

        lbl = QLabel("SET IP")
        lbl.setObjectName("sectionLbl")
        vlay.addWidget(lbl)

        desc = QLabel("Add custom IP addresses or domain names to list-general.txt hostlist.")
        desc.setObjectName("infoLbl")
        vlay.addWidget(desc)

        # ── Input row: QLineEdit + Add button ──
        inp_box = QWidget()
        inp_lay = QHBoxLayout(inp_box)
        inp_lay.setContentsMargins(0, 0, 0, 0)
        inp_lay.setSpacing(10)

        self._inp_custom_ip = QLineEdit()
        self._inp_custom_ip.setPlaceholderText("Enter IP or domain (e.g. soundcloud.com)...")
        self._inp_custom_ip.setFixedHeight(34)
        self._inp_custom_ip.returnPressed.connect(self._add_custom_ip)

        self._btn_add_ip = QPushButton("Add")
        self._btn_add_ip.setObjectName("actionBtn")
        self._btn_add_ip.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_add_ip.setFixedWidth(80)
        self._btn_add_ip.setFixedHeight(34)
        self._btn_add_ip.clicked.connect(self._add_custom_ip)

        inp_lay.addWidget(self._inp_custom_ip, 1)
        inp_lay.addWidget(self._btn_add_ip)
        vlay.addWidget(inp_box)

        # ── SoundCloud Button ──
        sc_box = QWidget()
        sc_lay = QHBoxLayout(sc_box)
        sc_lay.setContentsMargins(0, 0, 0, 0)
        sc_lay.setSpacing(10)

        self._btn_add_soundcloud = QPushButton("Add IP SoundCloud")
        self._btn_add_soundcloud.setObjectName("actionBtn")
        self._btn_add_soundcloud.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_add_soundcloud.setFixedHeight(34)
        self._btn_add_soundcloud.clicked.connect(self._add_soundcloud_ips)

        sc_desc = QLabel("Batch add all required SoundCloud domains to list-general.txt")
        sc_desc.setObjectName("infoLbl")

        sc_lay.addWidget(self._btn_add_soundcloud)
        sc_lay.addWidget(sc_desc)
        sc_lay.addStretch()
        vlay.addWidget(sc_box)

        # ── SpeedTest Button ──
        st_box = QWidget()
        st_lay = QHBoxLayout(st_box)
        st_lay.setContentsMargins(0, 0, 0, 0)
        st_lay.setSpacing(10)

        self._btn_add_speedtest = QPushButton("Add IP SpeedTest")
        self._btn_add_speedtest.setObjectName("actionBtn")
        self._btn_add_speedtest.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_add_speedtest.setFixedHeight(34)
        self._btn_add_speedtest.clicked.connect(self._add_speedtest_ips)

        st_desc = QLabel("Batch add all required SpeedTest domains to list-general.txt")
        st_desc.setObjectName("infoLbl")

        st_lay.addWidget(self._btn_add_speedtest)
        st_lay.addWidget(st_desc)
        st_lay.addStretch()
        vlay.addWidget(st_box)

        # ── Feedback label ──
        self._lbl_set_ip_feedback = QLabel("")
        self._lbl_set_ip_feedback.setStyleSheet("font-size: 12px; background: transparent;")
        vlay.addWidget(self._lbl_set_ip_feedback)

        # ── List info & preview ──
        self._lbl_set_ip_count = QLabel("list-general.txt entries: 0")
        self._lbl_set_ip_count.setStyleSheet("font-size: 12px; font-weight: 600; background: transparent;")
        vlay.addWidget(self._lbl_set_ip_count)

        self._txt_set_ip_preview = QTextEdit()
        self._txt_set_ip_preview.setObjectName("settingText")
        self._txt_set_ip_preview.setReadOnly(True)
        self._txt_set_ip_preview.setFixedHeight(180)
        vlay.addWidget(self._txt_set_ip_preview)

        vlay.addStretch()
        self._refresh_set_ip_info()
        return w

    def _build_settings_update_subpage(self) -> QWidget:
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(18)

        lbl = QLabel("UPDATE SETTINGS")
        lbl.setObjectName("sectionLbl")
        vlay.addWidget(lbl)

        # ── Check-update toggle ──
        sw_box = QWidget()
        sw_lay = QVBoxLayout(sw_box)
        sw_lay.setContentsMargins(0, 0, 0, 0)
        sw_lay.setSpacing(6)

        sw_top = QHBoxLayout()
        sw_top.setSpacing(14)

        sw_title = QLabel("check-update")
        sw_title.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent; min-width: 105px;")

        self._switch_check_update = ToggleSwitch(checked=self._check_update)
        self._switch_check_update.set_colors(self._color2, self._color1)
        self._switch_check_update.toggled.connect(self._on_check_update_toggled)

        self._lbl_check_update_state = QLabel("Enabled" if self._check_update else "Disabled")
        self._lbl_check_update_state.setStyleSheet("font-size: 12px; font-weight: 600; background: transparent;")

        sw_top.addWidget(sw_title)
        sw_top.addWidget(self._switch_check_update)
        sw_top.addWidget(self._lbl_check_update_state)
        sw_top.addStretch()
        sw_lay.addLayout(sw_top)

        sw_desc = QLabel("Check for new releases from https://github.com/bpm500/zapret_pp/releases on app launch.")
        sw_desc.setObjectName("infoLbl")
        sw_lay.addWidget(sw_desc)
        vlay.addWidget(sw_box)

        # ── Auto-download toggle ──
        auto_box = QWidget()
        auto_lay = QVBoxLayout(auto_box)
        auto_lay.setContentsMargins(0, 0, 0, 0)
        auto_lay.setSpacing(6)

        auto_top = QHBoxLayout()
        auto_top.setSpacing(14)

        auto_title = QLabel("auto-download")
        auto_title.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent; min-width: 105px;")

        self._switch_auto_download = ToggleSwitch(checked=self._auto_download)
        self._switch_auto_download.set_colors(self._color2, self._color1)
        self._switch_auto_download.toggled.connect(self._on_auto_download_toggled)

        self._lbl_auto_download_state = QLabel("Enabled" if self._auto_download else "Disabled")
        self._lbl_auto_download_state.setStyleSheet("font-size: 12px; font-weight: 600; background: transparent;")

        auto_top.addWidget(auto_title)
        auto_top.addWidget(self._switch_auto_download)
        auto_top.addWidget(self._lbl_auto_download_state)
        auto_top.addStretch()
        auto_lay.addLayout(auto_top)

        auto_desc = QLabel("Prompt to automatically download and self-replace executable when an update is found.")
        auto_desc.setObjectName("infoLbl")
        auto_lay.addWidget(auto_desc)
        vlay.addWidget(auto_box)

        # ── Version details ──
        info_box = QWidget()
        ib_lay = QVBoxLayout(info_box)
        ib_lay.setContentsMargins(0, 0, 0, 0)
        ib_lay.setSpacing(6)

        v_lbl = QLabel(f"Current version: v{APP_VERSION}")
        v_lbl.setStyleSheet("font-size: 13px; font-weight: 600; background: transparent;")

        repo_lbl = QLabel("Repository: https://github.com/bpm500/zapret_pp/releases")
        repo_lbl.setObjectName("infoLbl")

        ib_lay.addWidget(v_lbl)
        ib_lay.addWidget(repo_lbl)
        vlay.addWidget(info_box)

        vlay.addSpacing(10)

        # ── Manual check button ──
        chk_row = QHBoxLayout()
        chk_row.setSpacing(14)

        self._btn_check_update_now = QPushButton("Check for Updates Now")
        self._btn_check_update_now.setObjectName("actionBtn")
        self._btn_check_update_now.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_check_update_now.setFixedHeight(34)
        self._btn_check_update_now.clicked.connect(self._manual_check_update)

        self._lbl_update_feedback = QLabel("")
        self._lbl_update_feedback.setStyleSheet("font-size: 12px; background: transparent;")

        chk_row.addWidget(self._btn_check_update_now)
        chk_row.addWidget(self._lbl_update_feedback)
        chk_row.addStretch()
        vlay.addLayout(chk_row)

        vlay.addStretch()
        return w

    def _build_settings_about_subpage(self) -> QWidget:
        w = QWidget()
        vlay = QVBoxLayout(w)
        vlay.setContentsMargins(32, 24, 32, 24)
        vlay.setSpacing(8)

        vlay.addStretch(1)

        self._lbl_about_author = QLabel("author @bpm500")
        self._lbl_about_author.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_about_author.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
        self._lbl_about_author.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._lbl_about_github = QLabel(
            f'github: <a href="https://github.com/bpm500/zapret_pp" style="color: {self._text_color}; text-decoration: underline;">https://github.com/bpm500/zapret_pp</a>'
        )
        self._lbl_about_github.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_about_github.setOpenExternalLinks(True)
        self._lbl_about_github.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._lbl_about_github.setStyleSheet("font-size: 13px; background: transparent;")
        self._lbl_about_github.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )

        vlay.addWidget(self._lbl_about_author)
        vlay.addWidget(self._lbl_about_github)

        vlay.addStretch(1)
        return w

    def _on_slider_transparency_changed(self, val: int):
        self._transparency = val
        self._input_transparency.blockSignals(True)
        self._input_transparency.setText(f"{val}%")
        self._input_transparency.blockSignals(False)
        self.setWindowOpacity(val / 100.0)
        self._save_app_settings()

    def _on_input_transparency_changed(self):
        text = self._input_transparency.text()
        nums = re.findall(r"\d+", text)
        if nums:
            val = max(30, min(100, int(nums[0])))
            self._transparency = val
            self._slider_transparency.blockSignals(True)
            self._slider_transparency.setValue(val)
            self._slider_transparency.blockSignals(False)
            self._input_transparency.setText(f"{val}%")
            self.setWindowOpacity(val / 100.0)
            self._save_app_settings()
        else:
            self._input_transparency.setText(f"{self._transparency}%")

    def _pick_color_dialog(self, initial_hex: str, title: str) -> str | None:
        dlg = QColorDialog(QColor(initial_hex), self)
        dlg.setWindowTitle(title)
        dlg.setStyleSheet(self._current_stylesheet)
        try:
            apply_dark_titlebar(int(dlg.winId()), _is_dark_color(self._color1))
        except Exception:
            pass
        if dlg.exec():
            c = dlg.selectedColor()
            if not c.isValid():
                c = dlg.currentColor()
            if c.isValid():
                return c.name().lower()
        return None

    def _pick_color_1(self):
        c = self._pick_color_dialog(self._color1, "Select Color 1 (Background)")
        if c:
            self._color1 = c
            self._update_color_previews()
            self._apply_theme()
            self._save_app_settings()

    def _pick_color_2(self):
        c = self._pick_color_dialog(self._color2, "Select Color 2 (Accent)")
        if c:
            self._color2 = c
            self._update_color_previews()
            self._apply_theme()
            self._save_app_settings()

    def _pick_text_color(self):
        c = self._pick_color_dialog(self._text_color, "Select Text Color")
        if c:
            self._text_color = c
            self._update_color_previews()
            self._apply_theme()
            self._save_app_settings()

    def _reset_ui_defaults(self):
        self._transparency = 100
        self._color1 = "#0a0a0a"
        self._color2 = "#ffffff"
        self._text_color = "#e0e0e0"

        if hasattr(self, "_slider_transparency"):
            self._slider_transparency.blockSignals(True)
            self._slider_transparency.setValue(100)
            self._slider_transparency.blockSignals(False)
        if hasattr(self, "_input_transparency"):
            self._input_transparency.blockSignals(True)
            self._input_transparency.setText("100%")
            self._input_transparency.blockSignals(False)

        self.setWindowOpacity(1.0)
        self._clear_wallpaper()
        self._update_color_previews()
        self._apply_theme()
        self._save_app_settings()

    def _update_color_previews(self):
        if not hasattr(self, "_btn_color1"):
            return
        b1 = "#ffffff" if _is_dark_color(self._color1) else "#000000"
        b2 = "#ffffff" if _is_dark_color(self._color2) else "#000000"
        bt = "#ffffff" if _is_dark_color(self._text_color) else "#000000"

        self._btn_color1.setStyleSheet(
            f"QPushButton {{ background-color: {self._color1}; border: 2px solid {b1}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border-color: {self._color2}; }}"
        )
        self._lbl_hex_color1.setText(self._color1.upper())

        self._btn_color2.setStyleSheet(
            f"QPushButton {{ background-color: {self._color2}; border: 2px solid {b2}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border-color: {self._color2}; }}"
        )
        self._lbl_hex_color2.setText(self._color2.upper())

        self._btn_text_color.setStyleSheet(
            f"QPushButton {{ background-color: {self._text_color}; border: 2px solid {bt}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border-color: {self._color2}; }}"
        )
        self._lbl_hex_text_color.setText(self._text_color.upper())

        if hasattr(self, "_lbl_wallpaper_info"):
            if self._wallpaper_path and self._wallpaper_path.exists():
                self._lbl_wallpaper_info.setText(
                    f"Add a photo or GIF to the background (recommended: {WINDOW_W}x{WINDOW_H}) • Active: {self._wallpaper_path.name}"
                )
                if hasattr(self, "_btn_clear_wallpaper"):
                    self._btn_clear_wallpaper.setVisible(True)
            else:
                self._lbl_wallpaper_info.setText(
                    f"Add a photo or GIF to the background (recommended: {WINDOW_W}x{WINDOW_H})"
                )
                if hasattr(self, "_btn_clear_wallpaper"):
                    self._btn_clear_wallpaper.setVisible(False)

    def _apply_theme(self):
        has_wall = bool(self._wallpaper_path and self._wallpaper_path.exists())
        self._current_stylesheet = build_stylesheet(self._color1, self._color2, self._text_color, has_wallpaper=has_wall)
        self.setStyleSheet(self._current_stylesheet)
        self.setWindowOpacity(self._transparency / 100.0)
        self._update_color_previews()
        if hasattr(self, "_wallpaper_widget"):
            self._wallpaper_widget.set_base_color(self._color1)
        if hasattr(self, "_switch_check_update"):
            self._switch_check_update.set_colors(self._color2, self._color1)
        if hasattr(self, "_switch_auto_download"):
            self._switch_auto_download.set_colors(self._color2, self._color1)
        if hasattr(self, "_power_btn") and hasattr(self._power_btn, "set_theme"):
            self._power_btn.set_theme(self._color1, self._color2)
        if hasattr(self, "_lbl_about_github"):
            self._lbl_about_github.setText(
                f'github: <a href="https://github.com/bpm500/zapret_pp" style="color: {self._text_color}; text-decoration: underline;">https://github.com/bpm500/zapret_pp</a>'
            )
        if hasattr(self, "_refresh_statusbar"):
            self._refresh_statusbar()
        if hasattr(self, "_status_lbl"):
            self._sync_ui()
        try:
            apply_dark_titlebar(int(self.winId()), _is_dark_color(self._color1))
        except Exception:
            pass

    def _on_check_update_toggled(self, checked: bool):
        self._check_update = checked
        if hasattr(self, "_lbl_check_update_state"):
            self._lbl_check_update_state.setText("Enabled" if checked else "Disabled")
        self._save_app_settings()

    def _on_auto_download_toggled(self, checked: bool):
        self._auto_download = checked
        if hasattr(self, "_lbl_auto_download_state"):
            self._lbl_auto_download_state.setText("Enabled" if checked else "Disabled")
        self._save_app_settings()
        self._log(f"Auto-download {'enabled' if checked else 'disabled'}", "dim")

    def _manual_check_update(self):
        self._btn_check_update_now.setEnabled(False)
        self._lbl_update_feedback.setText("Checking GitHub...")
        self._lbl_update_feedback.setStyleSheet("color: #888888; font-size: 12px; background: transparent;")
        self._manual_worker = UpdateCheckWorker(self)
        self._manual_worker.finished.connect(self._on_manual_check_finished)
        self._manual_worker.start()

    def _on_manual_check_finished(self, success: bool, tag: str, download_url: str = ""):
        self._btn_check_update_now.setEnabled(True)
        if success and tag:
            if is_newer_version(tag, APP_VERSION):
                self._lbl_update_feedback.setText(f"New update found: {tag}")
                self._lbl_update_feedback.setStyleSheet("color: #4cd964; font-size: 12px; background: transparent;")
                self._show_update_dialog(tag, download_url=download_url)
            else:
                self._lbl_update_feedback.setText(f"You have the latest version (v{APP_VERSION}).")
                self._lbl_update_feedback.setStyleSheet("color: #888888; font-size: 12px; background: transparent;")
        else:
            self._lbl_update_feedback.setText("Check failed (no connection or rate limit).")
            self._lbl_update_feedback.setStyleSheet("color: #ff6666; font-size: 12px; background: transparent;")

    def _start_startup_update_check(self):
        if not self._check_update:
            return
        self._startup_worker = UpdateCheckWorker(self)
        self._startup_worker.finished.connect(self._on_startup_check_finished)
        self._startup_worker.start()

    def _on_startup_check_finished(self, success: bool, tag: str, download_url: str = ""):
        if success and tag and is_newer_version(tag, APP_VERSION):
            self._show_update_dialog(tag, download_url=download_url)

    def _show_update_dialog(self, new_tag: str, download_url: str = ""):
        dlg = NewUpdateDialog(
            new_tag,
            APP_VERSION,
            self._current_stylesheet,
            self,
            auto_download=self._auto_download,
            download_url=download_url,
        )
        dlg.exec()

    def _load_app_settings(self):
        self._app_settings_file = self._settings_dir / "app_settings.json"
        self._transparency = 100
        self._color1 = "#0a0a0a"
        self._color2 = "#ffffff"
        self._text_color = "#e0e0e0"
        self._check_update = True
        self._auto_download = False
        self._wallpaper_path: Path | None = None

        if self._app_settings_file.exists():
            try:
                data = json.loads(self._app_settings_file.read_text(encoding="utf-8"))
                self._transparency = max(30, min(100, int(data.get("transparency", 100))))
                self._color1 = str(data.get("color1", "#0a0a0a")).strip().lower()
                self._color2 = str(data.get("color2", "#ffffff")).strip().lower()
                self._text_color = str(data.get("text_color", "#e0e0e0")).strip().lower()
                self._check_update = bool(data.get("check_update", True))
                self._auto_download = bool(data.get("auto_download", False))
                wp = data.get("wallpaper")
                if wp:
                    wp_p = self._settings_dir / str(wp)
                    if wp_p.exists():
                        self._wallpaper_path = wp_p
            except Exception:
                pass
        else:
            self._save_app_settings()

    def _save_app_settings(self):
        if not hasattr(self, "_app_settings_file"):
            self._app_settings_file = self._settings_dir / "app_settings.json"
        data = {
            "transparency": self._transparency,
            "color1": self._color1,
            "color2": self._color2,
            "text_color": self._text_color,
            "check_update": self._check_update,
            "auto_download": self._auto_download,
            "wallpaper": self._wallpaper_path.name if (self._wallpaper_path and self._wallpaper_path.exists()) else None,
        }
        try:
            self._app_settings_file.parent.mkdir(parents=True, exist_ok=True)
            self._app_settings_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    # ── Wallpaper actions ──

    def _pick_wallpaper(self):
        file_filter = (
            "All Supported Files (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.mp4 *.avi *.mkv *.webm *.mov);;"
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;"
            "GIF (*.gif);;"
            "Videos (*.mp4 *.mkv *.avi *.webm *.mov);;"
            "All Files (*.*)"
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Wallpaper (Image, GIF, Video)",
            "",
            file_filter
        )
        if not file_path:
            return

        src = Path(file_path)
        if not src.exists():
            return

        try:
            self._settings_dir.mkdir(parents=True, exist_ok=True)
            for old_f in self._settings_dir.glob("wallpaper.*"):
                try:
                    old_f.unlink()
                except Exception:
                    pass

            dest = self._settings_dir / f"wallpaper{src.suffix.lower()}"
            shutil.copy2(src, dest)
            self._wallpaper_path = dest
            self._save_app_settings()
            self._apply_wallpaper()
            self._apply_theme()
        except Exception:
            pass

    def _clear_wallpaper_clicked(self):
        self._clear_wallpaper()
        self._save_app_settings()
        self._apply_theme()

    def _clear_wallpaper(self):
        if hasattr(self, "_settings_dir") and self._settings_dir.exists():
            for old_f in self._settings_dir.glob("wallpaper.*"):
                try:
                    old_f.unlink()
                except Exception:
                    pass
        self._wallpaper_path = None
        if hasattr(self, "_wallpaper_widget"):
            self._wallpaper_widget.clear_wallpaper()

    def _apply_wallpaper(self):
        if hasattr(self, "_wallpaper_widget") and self._wallpaper_path and self._wallpaper_path.exists():
            self._wallpaper_widget.set_wallpaper(self._wallpaper_path)

    # ── Set IP actions ──

    def _get_list_general_paths(self) -> list[Path]:
        paths: list[Path] = []
        if hasattr(self, "_zapret_dir") and self._zapret_dir:
            p1 = self._zapret_dir / "lists" / "list-general.txt"
            if p1.exists() and p1 not in paths:
                paths.append(p1)

        if hasattr(self, "_app_dir") and self._app_dir:
            for p in self._app_dir.rglob("list-general.txt"):
                if p.is_file() and p not in paths:
                    paths.append(p)

        if not paths:
            fallback = self._zapret_dir / "lists" / "list-general.txt"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.touch(exist_ok=True)
            paths.append(fallback)

        return paths

    def _read_list_general_entries(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        except Exception:
            return []

    def _sanitize_ip_or_domain(self, text: str) -> str:
        s = text.strip()
        if not s:
            return ""
        if "://" in s:
            try:
                parsed = urlparse(s)
                s = parsed.netloc or parsed.path
            except Exception:
                pass
        s = s.split("/")[0].strip()
        return s

    def _add_custom_ip(self):
        val = self._sanitize_ip_or_domain(self._inp_custom_ip.text())
        if not val:
            self._lbl_set_ip_feedback.setText("Please enter a valid IP address or domain.")
            self._lbl_set_ip_feedback.setStyleSheet("color: #ffaa00; font-size: 12px; background: transparent;")
            return

        paths = self._get_list_general_paths()
        if not paths:
            self._lbl_set_ip_feedback.setText("Error: list-general.txt not found.")
            self._lbl_set_ip_feedback.setStyleSheet("color: #ff5555; font-size: 12px; background: transparent;")
            return

        existing = [e.lower() for e in self._read_list_general_entries(paths[0])]
        if val.lower() in existing:
            self._lbl_set_ip_feedback.setText(f"Entry '{val}' already exists in list-general.txt.")
            self._lbl_set_ip_feedback.setStyleSheet("color: #ffaa00; font-size: 12px; background: transparent;")
            return

        for p in paths:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if content and not content.endswith("\n"):
                    content += "\n"
                content += val + "\n"
                p.write_text(content, encoding="utf-8")
            except Exception as e:
                self._lbl_set_ip_feedback.setText(f"Error saving to {p.name}: {e}")
                self._lbl_set_ip_feedback.setStyleSheet("color: #ff5555; font-size: 12px; background: transparent;")
                return

        self._lbl_set_ip_feedback.setText(f"Successfully added '{val}' to list-general.txt")
        self._lbl_set_ip_feedback.setStyleSheet("color: #55ff55; font-size: 12px; background: transparent;")
        self._inp_custom_ip.clear()
        self._refresh_set_ip_info()

    def _add_soundcloud_ips(self):
        paths = self._get_list_general_paths()
        if not paths:
            self._lbl_set_ip_feedback.setText("Error: list-general.txt not found.")
            self._lbl_set_ip_feedback.setStyleSheet("color: #ff5555; font-size: 12px; background: transparent;")
            return

        existing = set(e.lower() for e in self._read_list_general_entries(paths[0]))
        to_add = []
        already_count = 0

        for domain in SOUNDCLOUD_DOMAINS:
            d_clean = domain.strip()
            if not d_clean:
                continue
            if d_clean.lower() in existing or d_clean.lower() in [x.lower() for x in to_add]:
                already_count += 1
            else:
                to_add.append(d_clean)
                existing.add(d_clean.lower())

        if not to_add:
            self._lbl_set_ip_feedback.setText(
                f"All SoundCloud entries already exist in list-general.txt ({already_count} entries verified)."
            )
            self._lbl_set_ip_feedback.setStyleSheet("color: #ffaa00; font-size: 12px; background: transparent;")
            return

        for p in paths:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if content and not content.endswith("\n"):
                    content += "\n"
                content += "\n".join(to_add) + "\n"
                p.write_text(content, encoding="utf-8")
            except Exception as e:
                self._lbl_set_ip_feedback.setText(f"Error writing to {p.name}: {e}")
                self._lbl_set_ip_feedback.setStyleSheet("color: #ff5555; font-size: 12px; background: transparent;")
                return

        msg = f"Added {len(to_add)} SoundCloud entries to list-general.txt"
        if already_count > 0:
            msg += f" ({already_count} already existed)"
        self._lbl_set_ip_feedback.setText(msg)
        self._lbl_set_ip_feedback.setStyleSheet("color: #55ff55; font-size: 12px; background: transparent;")
        self._refresh_set_ip_info()

    def _add_speedtest_ips(self):
        paths = self._get_list_general_paths()
        if not paths:
            self._lbl_set_ip_feedback.setText("Error: list-general.txt not found.")
            self._lbl_set_ip_feedback.setStyleSheet("color: #ff5555; font-size: 12px; background: transparent;")
            return

        existing = set(e.lower() for e in self._read_list_general_entries(paths[0]))
        to_add = []
        already_count = 0

        for domain in SPEEDTEST_DOMAINS:
            d_clean = domain.strip()
            if not d_clean:
                continue
            if d_clean.lower() in existing or d_clean.lower() in [x.lower() for x in to_add]:
                already_count += 1
            else:
                to_add.append(d_clean)
                existing.add(d_clean.lower())

        if not to_add:
            self._lbl_set_ip_feedback.setText(
                f"All SpeedTest entries already exist in list-general.txt ({already_count} entries verified)."
            )
            self._lbl_set_ip_feedback.setStyleSheet("color: #ffaa00; font-size: 12px; background: transparent;")
            return

        for p in paths:
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if content and not content.endswith("\n"):
                    content += "\n"
                content += "\n".join(to_add) + "\n"
                p.write_text(content, encoding="utf-8")
            except Exception as e:
                self._lbl_set_ip_feedback.setText(f"Error writing to {p.name}: {e}")
                self._lbl_set_ip_feedback.setStyleSheet("color: #ff5555; font-size: 12px; background: transparent;")
                return

        msg = f"Added {len(to_add)} SpeedTest entries to list-general.txt"
        if already_count > 0:
            msg += f" ({already_count} already existed)"
        self._lbl_set_ip_feedback.setText(msg)
        self._lbl_set_ip_feedback.setStyleSheet("color: #55ff55; font-size: 12px; background: transparent;")
        self._refresh_set_ip_info()

    def _refresh_set_ip_info(self):
        if not hasattr(self, "_txt_set_ip_preview"):
            return
        paths = self._get_list_general_paths()
        if not paths:
            self._lbl_set_ip_count.setText("list-general.txt not found")
            self._txt_set_ip_preview.setPlainText("")
            return
        entries = self._read_list_general_entries(paths[0])
        self._lbl_set_ip_count.setText(f"list-general.txt ({paths[0].name}) — {len(entries)} entries:")
        self._txt_set_ip_preview.setPlainText("\n".join(entries))
        sb = self._txt_set_ip_preview.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    # ── TG WS Proxy Logic ─────────────────────────────────────────

    def _tg_populate_form(self, cfg: dict):
        defaults = default_tg_config()
        self._tg_inp_host.setText(str(cfg.get("host", defaults["host"])))
        self._tg_inp_port.setText(str(cfg.get("port", defaults["port"])))
        self._tg_inp_secret.setText(str(cfg.get("secret", defaults["secret"])))

        dc_list = cfg.get("dc_ip", defaults["dc_ip"])
        if isinstance(dc_list, list):
            self._tg_txt_dc.setPlainText("\n".join(str(x) for x in dc_list))
        else:
            self._tg_txt_dc.setPlainText(str(dc_list))

        self._tg_chk_cfproxy.setChecked(bool(cfg.get("cfproxy", defaults["cfproxy"])))
        self._tg_chk_h2.setChecked(bool(cfg.get("h2", defaults["h2"])))

        user_domains = coerce_domain_list(cfg.get("cfproxy_user_domain", []))
        self._tg_chk_custom_cf.setChecked(bool(cfg.get("cfproxy_user_domain_enabled", bool(user_domains))))
        self._tg_inp_custom_cf.setText(", ".join(user_domains))

        worker_domains = coerce_domain_list(cfg.get("cfproxy_worker_domain", []))
        self._tg_chk_cfworker.setChecked(bool(cfg.get("cfproxy_worker_enabled", bool(worker_domains))))
        self._tg_inp_cfworker.setText(", ".join(worker_domains))

        self._tg_chk_verbose.setChecked(bool(cfg.get("verbose", defaults["verbose"])))
        self._tg_chk_no_secure.setChecked(bool(cfg.get("no_secure", defaults["no_secure"])))

        self._tg_inp_buf.setText(str(cfg.get("buf_kb", defaults["buf_kb"])))
        self._tg_inp_pool.setText(str(cfg.get("pool_size", defaults["pool_size"])))
        self._tg_inp_log_mb.setText(str(cfg.get("log_max_mb", defaults["log_max_mb"])))
        self._chk_tg_autoconnect.setChecked(self._tg_auto_connect)

    def _tg_sync_subcontrols(self):
        cf_enabled = self._tg_chk_cfproxy.isChecked()
        self._tg_chk_h2.setEnabled(cf_enabled)
        self._tg_chk_custom_cf.setEnabled(cf_enabled)
        self._tg_inp_custom_cf.setEnabled(cf_enabled and self._tg_chk_custom_cf.isChecked())
        self._btn_test_cfproxy.setEnabled(cf_enabled)

        cfw_enabled = self._tg_chk_cfworker.isChecked()
        self._tg_inp_cfworker.setEnabled(cfw_enabled)
        self._btn_test_cfworker.setEnabled(cfw_enabled)

    def _tg_refresh_status_ui(self):
        is_run = self._tg_manager.is_running()
        host = self._tg_config.get("host", "127.0.0.1")
        port = self._tg_config.get("port", 1443)
        if is_run:
            self._tg_status_lbl.setText("● ACTIVE")
            self._tg_status_lbl.setStyleSheet(
                "color: #ffffff; font-size: 13px; font-weight: 700; background: transparent; border: none;"
            )
            self._tg_info_lbl.setText(f"{host}:{port}  (running)")
            self._btn_tg_toggle.setText("Stop Proxy")
            self._btn_tg_toggle.setObjectName("stopBtn")
        else:
            self._tg_status_lbl.setText("○ STOPPED")
            self._tg_status_lbl.setStyleSheet(
                "color: #666666; font-size: 13px; font-weight: 700; background: transparent; border: none;"
            )
            self._tg_info_lbl.setText(f"{host}:{port}  (inactive)")
            self._btn_tg_toggle.setText("Start Proxy")
            self._btn_tg_toggle.setObjectName("startBtn")

        self._btn_tg_toggle.style().unpolish(self._btn_tg_toggle)
        self._btn_tg_toggle.style().polish(self._btn_tg_toggle)
        if hasattr(self, "_tray"):
            self._refresh_tray()

    def _tg_toggle_proxy(self):
        if self._tg_manager.is_running():
            self._tg_stop_proxy()
        else:
            self._tg_start_proxy()

    def _tg_start_proxy(self, silent: bool = False):
        if not silent:
            self._tg_log("Starting TG WS Proxy...", "white")
        err_msg: list[str] = []
        ok = self._tg_manager.start(self._tg_config, on_error=lambda msg: err_msg.append(msg))
        self._tg_refresh_status_ui()
        if ok:
            host = self._tg_config.get("host", "127.0.0.1")
            port = self._tg_config.get("port", 1443)
            self._tg_log(f"TG WS Proxy listening on {host}:{port}", "white")
        else:
            reason = err_msg[0] if err_msg else "Could not start proxy (check port or address)"
            self._tg_log(f"ERROR: {reason}", "white")

    def _tg_start_proxy_silent(self):
        self._tg_start_proxy(silent=True)

    def _tg_stop_proxy(self, silent: bool = False):
        self._tg_manager.stop()
        self._tg_refresh_status_ui()
        if not silent:
            self._tg_log("TG WS Proxy stopped.", "dim")

    def _tg_stop_proxy_silent(self):
        self._tg_stop_proxy(silent=True)

    def _tg_restart_proxy(self):
        self._tg_log("Restarting TG WS Proxy...", "white")
        err_msg: list[str] = []
        ok = self._tg_manager.restart(self._tg_config, on_error=lambda msg: err_msg.append(msg))
        self._tg_refresh_status_ui()
        if ok:
            host = self._tg_config.get("host", "127.0.0.1")
            port = self._tg_config.get("port", 1443)
            self._tg_log(f"TG WS Proxy restarted on {host}:{port}", "white")
        else:
            reason = err_msg[0] if err_msg else "Restart failed"
            self._tg_log(f"ERROR: {reason}", "white")

    def _tg_open_telegram(self):
        url = self._tg_manager.get_url(self._tg_config)
        self._tg_log(f"Opening in Telegram: {url}", "dim")
        opened = False
        try:
            if sys.platform == "win32":
                os.startfile(url)
                opened = True
            else:
                import webbrowser
                opened = webbrowser.open(url)
        except Exception as e:
            self._tg_log(f"System open failed: {e}, copying to clipboard instead.", "dim")

        if not opened:
            QApplication.clipboard().setText(url)
            self._tg_log("Link copied to clipboard.", "white")

    def _tg_copy_link(self):
        url = self._tg_manager.get_url(self._tg_config)
        QApplication.clipboard().setText(url)
        self._tg_log(f"Proxy link copied to clipboard: {url}", "white")
        self._btn_tg_copy.setText("✓ Link Copied!")
        QTimer.singleShot(2000, lambda: self._btn_tg_copy.setText("Copy Proxy Link"))

    def _tg_open_log_file(self):
        log_f = self._tg_manager.log_file
        if log_f.exists():
            try:
                os.startfile(str(log_f))
                self._tg_log(f"Opened log file: {log_f}", "dim")
            except Exception as e:
                self._tg_log(f"Error opening log: {e}", "white")
        else:
            self._tg_log(f"Log file not yet created: {log_f}", "dim")

    def _tg_on_autoconnect_toggled(self, checked: bool):
        self._tg_auto_connect = checked
        self._tg_config["auto_connect"] = checked
        self._save_settings()
        self._tg_manager.set_config(self._tg_config)
        self._tg_log(f"Auto-connect with start: {'enabled' if checked else 'disabled'}", "dim")

    def _tg_generate_secret(self):
        new_sec = os.urandom(16).hex()
        self._tg_inp_secret.setText(new_sec)
        self._tg_log("Generated new random secret.", "dim")

    def _tg_save_settings(self):
        values = {
            "host": self._tg_inp_host.text(),
            "port": self._tg_inp_port.text(),
            "secret": self._tg_inp_secret.text(),
            "dc_ip": self._tg_txt_dc.toPlainText(),
            "cfproxy": self._tg_chk_cfproxy.isChecked(),
            "h2": self._tg_chk_h2.isChecked(),
            "cfproxy_user_domain_enabled": self._tg_chk_custom_cf.isChecked(),
            "cfproxy_user_domain": self._tg_inp_custom_cf.text(),
            "cfproxy_worker_enabled": self._tg_chk_cfworker.isChecked(),
            "cfproxy_worker_domain": self._tg_inp_cfworker.text(),
            "verbose": self._tg_chk_verbose.isChecked(),
            "no_secure": self._tg_chk_no_secure.isChecked(),
            "buf_kb": self._tg_inp_buf.text(),
            "pool_size": self._tg_inp_pool.text(),
            "log_max_mb": self._tg_inp_log_mb.text(),
            "auto_connect": self._chk_tg_autoconnect.isChecked(),
        }
        valid_cfg, err = validate_tg_settings(values, default_tg_config())
        if err:
            self._tg_feedback_lbl.setText(f"✗ {err}")
            self._tg_feedback_lbl.setStyleSheet("color: #ff6666; font-size: 12px; font-weight: 600;")
            self._tg_log(f"Settings error: {err}", "white")
            return

        self._tg_config = valid_cfg
        self._tg_auto_connect = valid_cfg.get("auto_connect", False)
        self._save_settings()
        self._tg_manager.set_config(valid_cfg)

        was_running = self._tg_manager.is_running()
        if was_running:
            self._tg_log("Applying settings and restarting proxy...", "dim")
            self._tg_manager.restart(valid_cfg, on_error=lambda msg: self._tg_log(f"Proxy error: {msg}", "white"))
        else:
            self._tg_log("Settings saved successfully.", "dim")

        self._tg_refresh_status_ui()
        self._tg_feedback_lbl.setText("✓ Settings saved and applied!")
        self._tg_feedback_lbl.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600;")
        QTimer.singleShot(3000, lambda: self._tg_feedback_lbl.setText(""))

    def _tg_reset_defaults(self):
        defs = default_tg_config()
        self._tg_populate_form(defs)
        self._tg_log("Reset form fields to default values. Click 'Save Settings' to apply.", "dim")
        self._tg_feedback_lbl.setText("Reset to defaults. Remember to click 'Save Settings'.")
        self._tg_feedback_lbl.setStyleSheet("color: #888888; font-size: 12px; font-weight: 600;")
        QTimer.singleShot(3500, lambda: self._tg_feedback_lbl.setText(""))

    def _tg_start_cfproxy_test(self):
        if self._cfproxy_test_worker and self._cfproxy_test_worker.isRunning():
            return
        custom_domains = (
            coerce_domain_list(self._tg_inp_custom_cf.text())
            if self._tg_chk_custom_cf.isChecked() else []
        )
        secure = not self._tg_chk_no_secure.isChecked()
        self._btn_test_cfproxy.setEnabled(False)
        self._btn_test_cfproxy.setText("Testing...")
        self._cfproxy_test_worker = CfProxyTestWorker(custom_domains, secure=secure)
        self._cfproxy_test_worker.log.connect(self._tg_log)
        self._cfproxy_test_worker.finished_test.connect(self._on_cfproxy_test_finished)
        self._cfproxy_test_worker.start()

    def _on_cfproxy_test_finished(self, ok: bool, summary: str):
        self._btn_test_cfproxy.setEnabled(True)
        self._btn_test_cfproxy.setText("Test CF-Proxy")

    def _tg_start_cfworker_test(self):
        if self._cfworker_test_worker and self._cfworker_test_worker.isRunning():
            return
        worker_domains = coerce_domain_list(self._tg_inp_cfworker.text())
        secure = not self._tg_chk_no_secure.isChecked()
        self._btn_test_cfworker.setEnabled(False)
        self._btn_test_cfworker.setText("Testing...")
        self._cfworker_test_worker = CfWorkerTestWorker(worker_domains, secure=secure)
        self._cfworker_test_worker.log.connect(self._tg_log)
        self._cfworker_test_worker.finished_test.connect(self._on_cfworker_test_finished)
        self._cfworker_test_worker.start()

    def _on_cfworker_test_finished(self, ok: bool, summary: str):
        self._btn_test_cfworker.setEnabled(True)
        self._btn_test_cfworker.setText("Test CF Worker")

    def _tg_log(self, text: str, color: str = "white"):
        COLORS = {
            "white": "#bbb",
            "dim": "#555",
        }
        hx = color if color.startswith("#") else COLORS.get(color, "#bbb")
        ts = time.strftime("%H:%M:%S")
        self._tg_console.append(
            f'<span style="color:#222;">[{ts}]</span> '
            f'<span style="color:{hx};">{text}</span>'
        )
        sb = self._tg_console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── Tray ──────────────────────────────────────────────────────

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip(APP_NAME)
        self._tray.activated.connect(self._on_tray_activated)

        m = QMenu()
        m.setStyleSheet(self._current_stylesheet)
        self._act_open = QAction("Open", self)
        self._act_conn = QAction("Connect", self)
        self._act_disc = QAction("Disconnect", self)
        self._act_tg_on = QAction("on tg-proxy", self)
        self._act_tg_off = QAction("off tg-proxy", self)
        self._act_exit = QAction("Exit", self)
        self._act_open.triggered.connect(self._restore)
        self._act_conn.triggered.connect(self._connect)
        self._act_disc.triggered.connect(self._disconnect)
        self._act_tg_on.triggered.connect(lambda: self._tg_start_proxy())
        self._act_tg_off.triggered.connect(lambda: self._tg_stop_proxy())
        self._act_exit.triggered.connect(self._exit_app)
        m.addAction(self._act_open)
        m.addSeparator()
        m.addAction(self._act_conn)
        m.addAction(self._act_disc)
        m.addSeparator()
        m.addAction(self._act_tg_on)
        m.addAction(self._act_tg_off)
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
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.stop()
        if self._test_selected_worker and self._test_selected_worker.isRunning():
            self._test_selected_worker.stop()
        if self._create_worker and self._create_worker.isRunning():
            self._create_worker.stop()
        if hasattr(self, "_cfproxy_test_worker") and self._cfproxy_test_worker and self._cfproxy_test_worker.isRunning():
            self._cfproxy_test_worker.stop()
        if hasattr(self, "_cfworker_test_worker") and self._cfworker_test_worker and self._cfworker_test_worker.isRunning():
            self._cfworker_test_worker.stop()
        if hasattr(self, "_tg_manager"):
            self._tg_manager.stop()
        self._disconnect()
        self._tray.hide()
        QApplication.quit()

    def _refresh_tray(self):
        self._act_conn.setVisible(not self._connected)
        self._act_disc.setVisible(self._connected)
        self._tray.setIcon(_make_tray_icon(self._connected))
        if hasattr(self, "_act_tg_on") and hasattr(self, "_act_tg_off") and hasattr(self, "_tg_manager"):
            is_tg = self._tg_manager.is_running()
            self._act_tg_on.setVisible(not is_tg)
            self._act_tg_off.setVisible(is_tg)

    # ── Window events ─────────────────────────────────────────────

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_wallpaper_widget"):
            self._wallpaper_widget.setGeometry(0, 0, self.width(), self.height())
            self._wallpaper_widget.lower()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_autostart_ui()
        if not self._dark_applied:
            self._dark_applied = True
            try:
                apply_dark_titlebar(int(self.winId()), _is_dark_color(self._color1))
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
        files_found = []
        if self._zapret_dir.exists():
            for f in sorted(self._zapret_dir.glob("*.bat")):
                name_lower = f.name.lower()
                # Skip service.bat and temp test files
                if name_lower == "service.bat" or name_lower.startswith("_test_custom_"):
                    continue
                files_found.append(f.name)

        # Preserve ranking order if available
        if hasattr(self, "_bat_files") and self._bat_files:
            ordered = [f for f in self._bat_files if f in files_found]
            for f in files_found:
                if f not in ordered:
                    ordered.append(f)
            self._bat_files = ordered
        else:
            self._bat_files = files_found

        self._config_list.blockSignals(True)
        self._config_list.clear()

        medals = {1: "🥇 ", 2: "🥈 ", 3: "🥉 "}
        for fname in self._bat_files:
            rank = self._bat_ranks.get(fname)
            prefix = medals.get(rank, "")
            item = QListWidgetItem(f"{prefix}{fname}")
            if rank:
                item.setToolTip(f"Top {rank} configuration")
            item.setData(Qt.ItemDataRole.UserRole, fname)
            self._config_list.addItem(item)

        # Restore selection
        if self._current_bat:
            found = False
            for i in range(self._config_list.count()):
                item = self._config_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_bat:
                    self._config_list.setCurrentRow(i)
                    found = True
                    break
            if not found and self._bat_files:
                self._current_bat = self._bat_files[0]
                self._config_list.setCurrentRow(0)
        elif self._bat_files:
            self._current_bat = self._bat_files[0]
            self._config_list.setCurrentRow(0)

        self._config_list.blockSignals(False)
        self._update_selected_label()

    def _on_list_changed(self, current, previous):
        if current:
            text = current.data(Qt.ItemDataRole.UserRole) or current.text()
            for m in ["🥇 ", "🥈 ", "🥉 "]:
                if text.startswith(m):
                    text = text[len(m):]
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
            name = self._current_bat.replace(".bat", "")
            rank = self._bat_ranks.get(self._current_bat)
            medals = {1: "🥇 ", 2: "🥈 ", 3: "🥉 "}
            prefix = medals.get(rank, "")
            self._selected_lbl.setText(f"{prefix}{name}")
        else:
            self._selected_lbl.setText("No config selected")

    def _on_config_context_menu(self, pos):
        """Show context menu on right-click in config list."""
        item = self._config_list.itemAt(pos)
        if not item:
            return
        self._config_list.setCurrentItem(item)
        fname = item.data(Qt.ItemDataRole.UserRole) or item.text()
        for m in ["🥇 ", "🥈 ", "🥉 "]:
            if fname.startswith(m):
                fname = fname[len(m):]

        menu = QMenu(self)
        menu.setStyleSheet(self._current_stylesheet)
        clean_name = fname.replace(".bat", "")
        delete_action = QAction(f'Delete "{clean_name}"', self)
        delete_action.triggered.connect(lambda: self._delete_config(fname))
        menu.addAction(delete_action)
        menu.exec(self._config_list.mapToGlobal(pos))

    def _delete_config(self, fname: str):
        """Delete a .bat config file and reload list."""
        bat_path = self._zapret_dir / fname
        was_current = (self._current_bat == fname)
        if was_current and self._connected:
            self._disconnect()

        try:
            if bat_path.exists():
                bat_path.unlink()
        except Exception as e:
            self._log(f"Error deleting {fname}: {e}", "white")
            return

        if fname in self._bat_files:
            self._bat_files.remove(fname)
        self._bat_ranks.pop(fname, None)

        if was_current:
            self._current_bat = self._bat_files[0] if self._bat_files else None
            self._save_settings()

        self._load_bat_files()
        self._log(f"Deleted config: {fname}", "dim")

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
        c_conn = self._color2 if hasattr(self, "_color2") else "#ffffff"
        c_disc = _blend_color(self._text_color, self._color1, 0.45) if hasattr(self, "_text_color") and hasattr(self, "_color1") else "#777777"
        self._set_status(
            "Connected" if self._connected else "Disconnected",
            c_conn if self._connected else c_disc
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
        admin = "Admin ✓" if is_admin() else "No admin"
        self._status_bar.setText(f"  {dot} {state}   ·   {admin}   ·   {APP_NAME} v{APP_VERSION}   ·   @bpm500")
        if hasattr(self, "_color1") and hasattr(self, "_text_color"):
            dark = _is_dark_color(self._color1)
            bg_bar = _blend_color(self._color1, "#000000" if dark else "#ffffff", 0.04)
            border_bar = _blend_color(self._color1, "#ffffff" if dark else "#000000", 0.12)
            txt_bar = _blend_color(self._text_color, self._color1, 0.35 if self._connected else 0.65)
            self._status_bar.setStyleSheet(
                f"background: {bg_bar}; color: {txt_bar}; font-size: 11px; "
                f"border-top: 1px solid {border_bar}; padding: 0 14px;"
            )
        else:
            col = "#888" if self._connected else "#333"
            self._status_bar.setStyleSheet(
                f"background: #060606; color: {col}; font-size: 11px; "
                f"border-top: 1px solid #111; padding: 0 14px;"
            )

    # ── Settings actions ──────────────────────────────────────────

    def _on_autostart_changed(self, v: bool):
        if v:
            success = enable_autostart(elevate=True)
            if not success:
                self._chk_autostart.blockSignals(True)
                self._chk_autostart.setChecked(False)
                self._chk_autostart.blockSignals(False)
                self._auto_start = False
                self._save_settings()
                self._log("Failed to enable autostart (admin rights required)", "white")
                return
            self._auto_start = True
            self._save_settings()
            self._log("Autostart enabled via Task Scheduler", "dim")
        else:
            success = disable_autostart(elevate=True)
            if not success:
                self._chk_autostart.blockSignals(True)
                self._chk_autostart.setChecked(True)
                self._chk_autostart.blockSignals(False)
                self._auto_start = True
                self._save_settings()
                self._log("Failed to disable autostart (admin rights required)", "white")
                return
            self._auto_start = False
            self._save_settings()
            self._log("Autostart disabled via Task Scheduler", "dim")

    def _on_autoconnect_changed(self, v: bool):
        self._auto_connect = v
        self._save_settings()
        self._log(f"Auto-connect {'enabled' if v else 'disabled'}", "dim")

    def _on_multi_ping_toggled(self, checked: bool):
        self._multi_ping = checked
        self._save_settings()
        self._log(f"Multi-ping {'enabled (3 configs)' if checked else 'disabled (sequential)'}", "dim")

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
            self._log("No .bat files found to test.", "white")
            return
        if self._test_selected_worker and self._test_selected_worker.isRunning():
            self._log("Selected config test is already running. Please wait or stop it.", "dim")
            return

        was_connected = self._connected
        if self._connected:
            self._disconnect()

        self._results.clear()
        self._btn_test.setText("⛔  Stop Test All")
        self._btn_test.setProperty("testing", "true")
        self._btn_test.style().unpolish(self._btn_test)
        self._btn_test.style().polish(self._btn_test)
        self._btn_test_selected.setEnabled(False)

        self._test_worker = TestWorker(self._bat_files, self._zapret_dir, was_connected, multi_ping=self._multi_ping)
        self._test_worker.log.connect(self._log)
        self._test_worker.result.connect(self._results.setPlainText)
        self._test_worker.ranked.connect(self._on_test_all_ranked)
        self._test_worker.finished.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_all_ranked(self, ranked_json: str):
        try:
            data = json.loads(ranked_json)
            self._bat_files = data.get("sorted", self._bat_files)
            self._bat_ranks = data.get("ranks", {})

            # Select top working config if available
            top_working = next((f for f, r in self._bat_ranks.items() if r == 1), None)
            if top_working:
                self._current_bat = top_working
            elif self._bat_files:
                self._current_bat = self._bat_files[0]
            self._save_settings()
            self._load_bat_files()
        except Exception as e:
            self._log(f"Error updating config rankings: {e}", "white")

    def _on_test_done(self):
        self._btn_test.setText("Test All Configs")
        self._btn_test.setEnabled(True)
        self._btn_test.setProperty("testing", "false")
        self._btn_test.style().unpolish(self._btn_test)
        self._btn_test.style().polish(self._btn_test)
        self._btn_test_selected.setEnabled(True)

    def _toggle_test_selected(self):
        if self._test_selected_worker and self._test_selected_worker.isRunning():
            self._test_selected_worker.stop()
            self._btn_test_selected.setEnabled(False)
            self._btn_test_selected.setText("Stopping...")
        else:
            self._start_test_selected()

    def _start_test_selected(self):
        if not self._current_bat:
            self._log("No config selected to test.", "white")
            return
        if self._test_worker and self._test_worker.isRunning():
            self._log("All configs test is already running. Please wait or stop it.", "dim")
            return

        was_connected = self._connected
        self._results.clear()
        self._btn_test_selected.setText("⛔  Stop Test")
        self._btn_test_selected.setProperty("testing", "true")
        self._btn_test_selected.style().unpolish(self._btn_test_selected)
        self._btn_test_selected.style().polish(self._btn_test_selected)
        self._btn_test.setEnabled(False)

        self._test_selected_worker = TestSelectedWorker(
            self._zapret_dir, self._current_bat, was_connected
        )
        self._test_selected_worker.log.connect(self._log)
        self._test_selected_worker.result.connect(self._results.setPlainText)
        self._test_selected_worker.finished.connect(self._on_test_selected_done)
        self._test_selected_worker.start()

    def _on_test_selected_done(self):
        self._btn_test_selected.setText("Test Selected Config")
        self._btn_test_selected.setEnabled(True)
        self._btn_test_selected.setProperty("testing", "false")
        self._btn_test_selected.style().unpolish(self._btn_test_selected)
        self._btn_test_selected.style().polish(self._btn_test_selected)
        self._btn_test.setEnabled(True)

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

        target_discord = self._chk_target_discord.isChecked()
        target_youtube = self._chk_target_youtube.isChecked()
        if not target_discord and not target_youtube:
            self._create_log("Select at least one target: Discord or YouTube!", "white")
            return

        num_configs = self._slider_num_configs.value()

        self._btn_create_route.setEnabled(False)
        self._btn_create_stop.setVisible(True)
        self._chk_target_discord.setEnabled(False)
        self._chk_target_youtube.setEnabled(False)
        self._slider_num_configs.setEnabled(False)

        self._create_worker = CreateWorker(self._zapret_dir, target_discord, target_youtube, num_configs, multi_ping=self._multi_ping)
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
        self._chk_target_discord.setEnabled(True)
        self._chk_target_youtube.setEnabled(True)
        self._slider_num_configs.setEnabled(True)

    def _create_log(self, text: str, color: str = "white"):
        COLORS = {
            "white": "#bbb",
            "dim": "#555",
        }
        hx = color if color.startswith("#") else COLORS.get(color, "#bbb")
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
        hx = color if color.startswith("#") else COLORS.get(color, "#bbb")
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
    try:
        app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        if app_dir:
            os.chdir(app_dir)
    except Exception:
        pass

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
