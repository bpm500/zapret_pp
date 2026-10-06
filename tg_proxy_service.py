"""
tg_proxy_service.py — Embedded Telegram WebSocket Bridge Proxy Service for zapret++
Integrates tg-ws-proxy directly into zapret++ with native PyQt6 threading and config management.
"""
from __future__ import annotations

import asyncio
import base64
import errno
import json
import logging
import logging.handlers
import math
import os
import socket as _socket
import sys
import threading
import time
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

# Import core proxy engine from embedded proxy package
from proxy import coerce_domain_list, get_link_host, parse_dc_ip_list
from proxy.balancer import balancer
from proxy.config import (
    CFPROXY_DEFAULT_DOMAINS,
    proxy_config,
    start_cfproxy_domain_refresh,
)
from proxy.tg_ws_proxy import _run
from proxy.utils import DomainCensorFilter, create_ssl_context

log = logging.getLogger("tg-ws-proxy")

# Windows WinSock error codes
_WSA_EACCES = 10013
_WSA_EFAULT = 10014
_WSA_EADDRINUSE = 10048
_WSA_EADDRNOTAVAIL = 10049

_CFPROXY_TEST_DCS = [1, 2, 3, 4, 5, 203]
_CFWORKER_TEST_DST = {
    1: "149.154.175.50",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "149.154.171.5",
    203: "91.105.192.100",
}


def diagnose_listen_error(exc: BaseException) -> str:
    """Map listen-socket bind failure to user-friendly message."""
    if not isinstance(exc, OSError):
        return str(exc)
    err = exc.errno
    winerror = getattr(exc, "winerror", None)

    if err == errno.EADDRINUSE or winerror == _WSA_EADDRINUSE:
        return "Port is already in use by another application"
    if err == errno.EACCES or winerror == _WSA_EACCES:
        return "Permission denied to bind to port. Try port >= 1024 or Administrator rights"
    if (winerror in (_WSA_EFAULT, _WSA_EADDRNOTAVAIL)
            or err in (errno.EADDRNOTAVAIL, errno.EFAULT)):
        return "Specified IP address is not available on this machine"
    return str(exc)


def build_log_handler(path: str, log_max_mb: float = 5, backups: int = 1) -> logging.handlers.RotatingFileHandler:
    max_bytes = max(32 * 1024, int(log_max_mb * 1024 * 1024))
    backup_count = max(1, int(backups))
    return logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )


# ══════════════════════════════════════════════════════════════════
#  DEFAULT CONFIGURATION & VALIDATION
# ══════════════════════════════════════════════════════════════════

def default_tg_config() -> Dict[str, Any]:
    return {
        "port": 1443,
        "host": "127.0.0.1",
        "secret": os.urandom(16).hex(),
        "dc_ip": ["2:149.154.167.220", "4:149.154.167.220"],
        "verbose": False,
        "log_max_mb": 5,
        "buf_kb": 256,
        "pool_size": 4,
        "cfproxy": True,
        "h2": True,
        "cfproxy_user_domain_enabled": False,
        "cfproxy_user_domain": [],
        "cfproxy_worker_enabled": False,
        "cfproxy_worker_domain": [],
        "force_test_dc": False,
        "no_secure": False,
        "auto_connect": False,
    }


def validate_tg_settings(values: dict, defaults: dict) -> Tuple[Optional[dict], Optional[str]]:
    """Validate settings form values. Returns (config_dict, None) or (None, error_str)."""
    config = deepcopy(defaults)
    config.update(deepcopy(values))

    host = str(values.get("host", "")).strip()
    try:
        _socket.inet_aton(host)
    except OSError:
        return None, f"Invalid IP address: '{host}'"

    try:
        port = int(str(values.get("port", "")).strip())
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        return None, "Port must be an integer between 1 and 65535"

    secret = str(values.get("secret", "")).strip().lower()
    if len(secret) != 32:
        return None, f"Secret must be exactly 32 hex characters (got {len(secret)})"
    if any(c not in "0123456789abcdef" for c in secret):
        return None, "Secret must contain only hexadecimal digits (0-9, a-f)"

    dc_raw = values.get("dc_ip", [])
    if isinstance(dc_raw, str):
        dc_lines = [line.strip() for line in dc_raw.splitlines() if line.strip()]
    elif isinstance(dc_raw, list):
        dc_lines = [str(x).strip() for x in dc_raw if str(x).strip()]
    else:
        dc_lines = []

    try:
        parse_dc_ip_list(dc_lines)
    except ValueError as exc:
        return None, f"Invalid DC:IP rule: {exc}"

    config["host"] = host
    config["port"] = port
    config["secret"] = secret
    config["dc_ip"] = dc_lines

    for key in ("buf_kb", "pool_size", "log_max_mb"):
        try:
            val = float(str(values.get(key, defaults[key])).strip())
            if not math.isfinite(val) or val < 0:
                raise ValueError
            config[key] = int(val) if key != "log_max_mb" else val
        except (ValueError, OverflowError):
            config[key] = defaults[key]

    for key in ("cfproxy", "h2", "cfproxy_user_domain_enabled", "cfproxy_worker_enabled", "verbose", "no_secure", "auto_connect"):
        config[key] = bool(values.get(key, defaults.get(key, False)))

    for key in ("cfproxy_user_domain", "cfproxy_worker_domain"):
        config[key] = coerce_domain_list(values.get(key, defaults.get(key, [])))

    return config, None


def get_tg_settings_dir(app_dir: Optional[Path] = None) -> Path:
    if app_dir is None:
        if hasattr(sys, 'frozen'):
            app_dir = Path(sys.executable).parent
        else:
            app_dir = Path.cwd()
    s_dir = app_dir / "settings"
    s_dir.mkdir(parents=True, exist_ok=True)
    return s_dir


def load_tg_config(app_dir: Path) -> dict:
    s_dir = get_tg_settings_dir(app_dir)
    cfg_file = s_dir / "tg_proxy_settings.json"
    legacy_file = app_dir / "tg_proxy_settings.json"
    defaults = default_tg_config()

    target_file = None
    if cfg_file.exists():
        target_file = cfg_file
    elif legacy_file.exists():
        target_file = legacy_file

    if target_file and target_file.exists():
        try:
            data = json.loads(target_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Ensure secret is preserved or generated
                if not data.get("secret"):
                    data["secret"] = defaults["secret"]
                for k, v in defaults.items():
                    data.setdefault(k, v)
                if target_file == legacy_file:
                    save_tg_config(app_dir, data)
                    try:
                        legacy_file.unlink()
                    except Exception:
                        pass
                return data
        except Exception as e:
            log.warning("Failed to read %s: %s", target_file, e)
    return defaults


def save_tg_config(app_dir: Path, cfg: dict) -> None:
    s_dir = get_tg_settings_dir(app_dir)
    cfg_file = s_dir / "tg_proxy_settings.json"
    try:
        cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log.error("Failed to save %s: %s", cfg_file, e)


# ══════════════════════════════════════════════════════════════════
#  PROXY MANAGER
# ══════════════════════════════════════════════════════════════════

class TgProxyManager:
    _instance: Optional[TgProxyManager] = None

    @classmethod
    def get(cls, app_dir: Optional[Path] = None) -> TgProxyManager:
        if cls._instance is None:
            if app_dir is None:
                app_dir = Path.cwd()
            cls._instance = TgProxyManager(app_dir)
        return cls._instance

    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.log_file = app_dir / "proxy.log"
        self._thread: Optional[threading.Thread] = None
        self._async_stop: Optional[Tuple[asyncio.AbstractEventLoop, asyncio.Event]] = None
        self._lock = threading.Lock()
        self._last_error: Optional[str] = None
        self._config: dict = load_tg_config(app_dir)
        self._log_handler_installed = False

    @property
    def config(self) -> dict:
        return self._config

    def set_config(self, cfg: dict):
        self._config = cfg
        save_tg_config(self.app_dir, cfg)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_url(self, cfg: Optional[dict] = None) -> str:
        c = cfg or self._config
        host = c.get("host", "127.0.0.1")
        port = c.get("port", 1443)
        secret = c.get("secret", "")
        link_host = get_link_host(host)
        return f"tg://proxy?server={link_host}&port={port}&secret=dd{secret}"

    def setup_logging(self, verbose: bool = False, log_max_mb: float = 5):
        if self._log_handler_installed:
            return
        try:
            root = logging.getLogger()
            root.setLevel(logging.DEBUG if verbose else logging.INFO)
            logging.getLogger("asyncio").setLevel(logging.WARNING)

            fh = build_log_handler(str(self.log_file), log_max_mb=log_max_mb, backups=1)
            fh.setLevel(logging.DEBUG if verbose else logging.INFO)
            fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(name)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            fh.setFormatter(fmt)
            fh.addFilter(DomainCensorFilter())
            root.addHandler(fh)
            self._log_handler_installed = True
        except Exception as e:
            log.warning("Could not set up proxy file logging: %s", e)

    def apply_config_to_engine(self, cfg: dict) -> bool:
        defaults = default_tg_config()
        dc_ip_list = cfg.get("dc_ip", defaults["dc_ip"])
        try:
            dc_redirects = parse_dc_ip_list(dc_ip_list)
        except ValueError as e:
            log.error("Bad config dc_ip: %s", e)
            self._last_error = f"Invalid DC:IP: {e}"
            return False

        pc = proxy_config
        pc.port = int(cfg.get("port", defaults["port"]))
        pc.host = str(cfg.get("host", defaults["host"]))
        pc.secret = str(cfg.get("secret", defaults["secret"]))
        pc.dc_redirects = dc_redirects
        pc.buffer_size = max(4, int(cfg.get("buf_kb", defaults["buf_kb"]))) * 1024
        pc.pool_size = max(0, int(cfg.get("pool_size", defaults["pool_size"])))
        pc.fallback_cfproxy = bool(cfg.get("cfproxy", defaults["cfproxy"]))
        pc.cfproxy_h2_media = bool(cfg.get("h2", defaults["h2"]))

        cfproxy_user_domains = coerce_domain_list(cfg.get("cfproxy_user_domain", []))
        cfproxy_worker_domains = coerce_domain_list(cfg.get("cfproxy_worker_domain", []))

        pc.cfproxy_user_domains = (
            cfproxy_user_domains if cfg.get("cfproxy_user_domain_enabled", False) else []
        )
        pc.cfproxy_worker_domains = (
            cfproxy_worker_domains if cfg.get("cfproxy_worker_enabled", False) else []
        )
        pc.force_test_dc = bool(cfg.get("force_test_dc", defaults["force_test_dc"]))
        pc.disable_secure = bool(cfg.get("no_secure", defaults["no_secure"]))
        return True

    def start(self, cfg: Optional[dict] = None, on_error: Optional[Callable[[str], None]] = None) -> bool:
        with self._lock:
            if self.is_running():
                return True

            c = cfg or self._config
            self._last_error = None

            if not self.apply_config_to_engine(c):
                if on_error:
                    on_error(self._last_error or "Configuration error")
                return False

            self.setup_logging(
                verbose=c.get("verbose", False),
                log_max_mb=c.get("log_max_mb", 5),
            )

            # Start domain refresher if CF proxy is enabled
            if c.get("cfproxy", True):
                try:
                    start_cfproxy_domain_refresh()
                except Exception as e:
                    log.warning("Could not start CF domain refresh: %s", e)

            startup_error: list[Optional[str]] = [None]
            ready_ev = threading.Event()

            def _thread_target():
                nonlocal ready_ev, startup_error
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                stop_ev = asyncio.Event()
                self._async_stop = (loop, stop_ev)

                ready_ev.set()

                try:
                    loop.run_until_complete(_run(stop_event=stop_ev))
                except Exception as exc:
                    diag = diagnose_listen_error(exc)
                    log.error("Proxy crashed or failed to bind: %s (%s)", exc, diag)
                    self._last_error = diag
                    startup_error[0] = diag
                    if on_error:
                        try:
                            on_error(diag)
                        except Exception:
                            pass
                finally:
                    try:
                        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                        for t in pending:
                            t.cancel()
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        loop.run_until_complete(loop.shutdown_asyncgens())
                    except Exception:
                        pass
                    try:
                        loop.close()
                    except Exception:
                        pass
                    self._async_stop = None

            self._thread = threading.Thread(target=_thread_target, daemon=True, name="tg-ws-proxy")
            self._thread.start()

            ready_ev.wait(timeout=2.0)
            # Give it a fraction of a second to detect any immediate bind crashes
            time.sleep(0.3)

            if startup_error[0]:
                return False
            return self.is_running()

    def stop(self) -> None:
        with self._lock:
            if self._async_stop:
                loop, stop_ev = self._async_stop
                try:
                    loop.call_soon_threadsafe(stop_ev.set)
                except Exception:
                    pass
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=3.0)
            self._thread = None
            self._async_stop = None
            log.info("TG WS Proxy stopped")

    def restart(self, cfg: Optional[dict] = None, on_error: Optional[Callable[[str], None]] = None) -> bool:
        self.stop()
        time.sleep(0.5)
        return self.start(cfg, on_error)


# ══════════════════════════════════════════════════════════════════
#  CONNECTIVITY TESTS & BACKGROUND WORKERS
# ══════════════════════════════════════════════════════════════════

def _run_connectivity_cases(cases: list, secure: bool = True, timeout: float = 5.0) -> dict:
    ctx = create_ssl_context() if secure else None
    port = 443 if secure else 80
    results = {}
    for dc, connect_host, sni_host, req_host, path in cases:
        try:
            with _socket.create_connection((connect_host, port), timeout=timeout) as raw:
                connection = (ctx.wrap_socket(raw, server_hostname=sni_host)
                              if secure else nullcontext(raw))
                with connection as ssock:
                    ws_key = base64.b64encode(os.urandom(16)).decode()
                    req = (
                        f"GET {path} HTTP/1.1\r\n"
                        f"Host: {req_host}\r\n"
                        f"Upgrade: websocket\r\n"
                        f"Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {ws_key}\r\n"
                        f"Sec-WebSocket-Version: 13\r\n"
                        f"Sec-WebSocket-Protocol: binary\r\n"
                        f"\r\n"
                    ).encode()
                    ssock.sendall(req)
                    ssock.settimeout(timeout)
                    buf = b""
                    while b"\r\n\r\n" not in buf:
                        chunk = ssock.recv(512)
                        if not chunk:
                            break
                        buf += chunk
                    first = buf.decode("utf-8", errors="replace").split("\r\n")[0]
                    if "101" in first:
                        results[dc] = True
                    else:
                        results[dc] = first or "no response"
                    ssock.close()
                raw.close()
        except _socket.timeout:
            results[dc] = "timeout"
        except OSError as exc:
            msg = str(exc)
            results[dc] = msg[:60] if len(msg) > 60 else msg
    return results


def run_single_cfproxy_test(domain: str, secure: bool = True) -> dict:
    cases = []
    for dc in _CFPROXY_TEST_DCS:
        host = f"kws{dc}.{domain}"
        cases.append((dc, host, host, host, "/apiws"))
    return _run_connectivity_cases(cases, secure=secure)


def run_single_cfworker_test(domain: str, secure: bool = True) -> dict:
    cases = []
    for dc in _CFPROXY_TEST_DCS:
        dst = _CFWORKER_TEST_DST[dc]
        path = f"/apiws?dst={dst}&dc={dc}&media=0"
        cases.append((dc, domain, domain, domain, path))
    return _run_connectivity_cases(cases, secure=secure)


class CfProxyTestWorker(QThread):
    log = pyqtSignal(str, str)         # (line, color_style)
    finished_test = pyqtSignal(bool, str)

    def __init__(self, user_domains: List[str], secure: bool = True):
        super().__init__()
        self.user_domains = [d.strip() for d in user_domains if d.strip()]
        self.secure = secure
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        self.log.emit("━" * 45, "dim")
        self.log.emit("▶ Starting Cloudflare Proxy connectivity test...", "white")
        self.log.emit(f"  Security: {'TLS / HTTPS (Port 443)' if self.secure else 'Plain HTTP (Port 80)'}", "dim")

        domains_to_test = self.user_domains
        if not domains_to_test:
            # Test auto domains from balancer
            domains_to_test = list(balancer.domains) or CFPROXY_DEFAULT_DOMAINS[:4]
            self.log.emit(f"  Mode: Auto domains ({len(domains_to_test)} available)", "dim")
        else:
            self.log.emit(f"  Mode: Custom domains: {', '.join(domains_to_test)}", "dim")

        overall_ok = False
        summary = ""

        for domain in domains_to_test:
            if self._stop:
                break
            self.log.emit(f"\nTesting domain: {domain}...", "white")
            results = run_single_cfproxy_test(domain, secure=self.secure)
            ok_dcs = [dc for dc, v in results.items() if v is True]
            fail_dcs = [(dc, v) for dc, v in results.items() if v is not True]

            for dc in _CFPROXY_TEST_DCS:
                status = results.get(dc, "unknown")
                if status is True:
                    self.log.emit(f"  ✓ DC{dc}: Available (101 Switching Protocols)", "white")
                else:
                    self.log.emit(f"  ✗ DC{dc}: {status}", "dim")

            if len(ok_dcs) == len(_CFPROXY_TEST_DCS):
                self.log.emit(f"  ★ Domain {domain} is fully functional! ({len(ok_dcs)}/{len(_CFPROXY_TEST_DCS)} DCs ok)", "white")
                overall_ok = True
                summary = f"Domain {domain} fully accessible"
                # If custom domain, continue testing all; if auto, one fully working is enough
                if not self.user_domains:
                    break
            elif ok_dcs:
                self.log.emit(f"  ~ Domain {domain} partially functional ({len(ok_dcs)}/{len(_CFPROXY_TEST_DCS)} DCs ok)", "white")
                overall_ok = True
                summary = f"Domain {domain} partially accessible"
            else:
                self.log.emit(f"  ✗ Domain {domain} unreachable", "dim")

        self.log.emit("━" * 45, "dim")
        if overall_ok:
            self.log.emit(f"✓ CF-Proxy test completed: {summary or 'Success'}", "white")
            self.finished_test.emit(True, summary or "Success")
        else:
            self.log.emit("✗ CF-Proxy test failed: No working servers found", "dim")
            self.finished_test.emit(False, "No working servers found")


class CfWorkerTestWorker(QThread):
    log = pyqtSignal(str, str)
    finished_test = pyqtSignal(bool, str)

    def __init__(self, worker_domains: List[str], secure: bool = True):
        super().__init__()
        self.worker_domains = [d.strip() for d in worker_domains if d.strip()]
        self.secure = secure
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        self.log.emit("━" * 45, "dim")
        self.log.emit("▶ Starting Cloudflare Worker connectivity test...", "white")
        self.log.emit(f"  Security: {'TLS / HTTPS (Port 443)' if self.secure else 'Plain HTTP (Port 80)'}", "dim")

        if not self.worker_domains:
            self.log.emit("  ERROR: No Cloudflare Worker domains specified!", "white")
            self.finished_test.emit(False, "No domains specified")
            return

        overall_ok = False
        summary = ""

        for domain in self.worker_domains:
            if self._stop:
                break
            self.log.emit(f"\nTesting worker domain: {domain}...", "white")
            results = run_single_cfworker_test(domain, secure=self.secure)
            ok_dcs = [dc for dc, v in results.items() if v is True]

            for dc in _CFPROXY_TEST_DCS:
                status = results.get(dc, "unknown")
                if status is True:
                    self.log.emit(f"  ✓ DC{dc}: Available via Worker", "white")
                else:
                    self.log.emit(f"  ✗ DC{dc}: {status}", "dim")

            if len(ok_dcs) == len(_CFPROXY_TEST_DCS):
                self.log.emit(f"  ★ Worker {domain} fully accessible ({len(ok_dcs)}/{len(_CFPROXY_TEST_DCS)} DCs ok)", "white")
                overall_ok = True
                summary = f"Worker {domain} fully functional"
            elif ok_dcs:
                self.log.emit(f"  ~ Worker {domain} partially accessible ({len(ok_dcs)}/{len(_CFPROXY_TEST_DCS)} DCs ok)", "white")
                overall_ok = True
                summary = f"Worker {domain} partially functional"
            else:
                self.log.emit(f"  ✗ Worker {domain} unreachable", "dim")

        self.log.emit("━" * 45, "dim")
        if overall_ok:
            self.log.emit(f"✓ CF Worker test completed: {summary or 'Success'}", "white")
            self.finished_test.emit(True, summary or "Success")
        else:
            self.log.emit("✗ CF Worker test failed: No working servers found", "dim")
            self.finished_test.emit(False, "No working servers found")
