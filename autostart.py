"""
Autostart service using Windows Task Scheduler (schtasks.exe) and Registry Run keys.
Supports highest privileges (/rl highest) on user logon (/sc onlogon),
robust multi-method deletion with UAC fallback on user toggle,
and full cleanup of Task Scheduler and Registry Run entries.
"""
import os
import sys
import subprocess
import winreg
import ctypes
from ctypes import wintypes
from pathlib import Path

TASK_NAME = "zapret++"
LEGACY_TASK_NAMES = ["zapret++", "zapret_pp", "ZapretTester", "zapret"]


class _SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def _run_elevated_wait(file_path: str, params: str, timeout_ms: int = 5000) -> bool:
    """Run an executable with UAC elevation (runas) and wait for completion."""
    try:
        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0
        sei = _SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(sei)
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        sei.hwnd = None
        sei.lpVerb = "runas"
        sei.lpFile = file_path
        sei.lpParameters = params
        sei.lpDirectory = None
        sei.nShow = SW_HIDE

        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
            return False

        h_proc = sei.hProcess
        if h_proc:
            ctypes.windll.kernel32.WaitForSingleObject(h_proc, timeout_ms)
            exit_code = wintypes.DWORD()
            ctypes.windll.kernel32.GetExitCodeProcess(h_proc, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(h_proc)
            return exit_code.value == 0
        return True
    except Exception:
        return False


def get_executable_path() -> str:
    """
    Get the path to the binary or script:
    - If frozen (.exe): sys.executable
    - If script (.py): sys.argv[0]
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def clean_registry_run(names: list[str] | None = None) -> None:
    """Clean legacy and current autostart entries from HKCU and HKLM Run keys."""
    if names is None:
        names = LEGACY_TASK_NAMES

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key = winreg.OpenKey(
                root,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ,
            )
            for name in names:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass


def is_autostart_enabled(task_name: str = TASK_NAME) -> bool:
    """
    Check if the task is present and enabled in Windows Task Scheduler or Registry.
    Checks task_name as well as legacy aliases.
    """
    names_to_check = [task_name]
    if task_name == TASK_NAME:
        names_to_check = list(dict.fromkeys([TASK_NAME] + LEGACY_TASK_NAMES))

    for name in names_to_check:
        # 1. Check via schtasks /query
        try:
            res = subprocess.run(
                ["schtasks", "/query", "/tn", name],
                capture_output=True,
                encoding="cp866",
                errors="replace",
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                out = (res.stdout or "").lower()
                if "disabled" not in out and "отключено" not in out:
                    return True
        except Exception:
            pass

        # 2. Check registry Run keys (HKCU & HKLM)
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(
                    root,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_READ,
                )
                try:
                    val, _ = winreg.QueryValueEx(key, name)
                    if val:
                        winreg.CloseKey(key)
                        return True
                except FileNotFoundError:
                    pass
                winreg.CloseKey(key)
            except Exception:
                pass

    return False


def enable_autostart(task_name: str = TASK_NAME, elevate: bool = False) -> bool:
    """
    Create a scheduled task with highest privileges on user logon.
    Runs: schtasks /create /tn <task_name> /tr "<path>" /sc onlogon /rl highest /f
    Falls back to elevated UAC prompt if elevate is True and direct call fails.
    """
    exe_path = get_executable_path()

    # If running from python script (not frozen exe), wrap with python.exe
    if not getattr(sys, "frozen", False) and exe_path.lower().endswith(".py"):
        target_cmd = f'"{sys.executable}" "{exe_path}"'
    else:
        target_cmd = f'"{exe_path}"'

    # 1. Direct schtasks create
    cmd = [
        "schtasks",
        "/create",
        "/tn", task_name,
        "/tr", target_cmd,
        "/sc", "onlogon",
        "/rl", "highest",
        "/f",
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            encoding="cp866",
            errors="replace",
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if res.returncode == 0:
            return True
    except Exception:
        pass

    # 2. If direct call failed and elevate requested, try elevated execution via UAC runas
    if elevate:
        try:
            params = f'/create /tn "{task_name}" /tr "{target_cmd}" /sc onlogon /rl highest /f'
            if _run_elevated_wait("schtasks.exe", params, timeout_ms=5000):
                return is_autostart_enabled(task_name)
        except Exception:
            pass

    return False


def disable_autostart(task_name: str = TASK_NAME, elevate: bool = False) -> bool:
    """
    Delete the scheduled task from Windows Task Scheduler and clean registry Run keys.
    Tries direct schtasks first. If elevate is True and access is denied, prompts UAC.
    Returns True if the task and registry keys are successfully deleted/absent.
    """
    names_to_delete = list(dict.fromkeys([task_name] + LEGACY_TASK_NAMES))

    # 1. Clean registry Run keys
    clean_registry_run(names_to_delete)

    # 2. Delete from Task Scheduler
    for name in names_to_delete:
        deleted = False

        # A. Direct schtasks delete
        try:
            res = subprocess.run(
                ["schtasks", "/delete", "/tn", name, "/f"],
                capture_output=True,
                encoding="cp866",
                errors="replace",
                timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                deleted = True
            else:
                err = (res.stderr or "").lower()
                # If task wasn't found, it is already absent
                if "cannot find" in err or "не удается найти" in err or "не существует" in err:
                    deleted = True
        except Exception:
            pass

        if deleted:
            continue

        # B. If elevate requested and direct delete failed (e.g. Access Denied), try elevated UAC
        if elevate:
            try:
                if _run_elevated_wait("schtasks.exe", f'/delete /tn "{name}" /f', timeout_ms=5000):
                    deleted = True
            except Exception:
                pass

    # 3. Final verification: is any task still present?
    return not is_autostart_enabled(task_name)


class AutostartService:
    """Service class for managing Windows Task Scheduler autostart."""

    def __init__(self, task_name: str = TASK_NAME):
        self.task_name = task_name

    def is_autostart_enabled(self) -> bool:
        return is_autostart_enabled(self.task_name)

    def enable_autostart(self, elevate: bool = False) -> bool:
        return enable_autostart(self.task_name, elevate=elevate)

    def disable_autostart(self, elevate: bool = False) -> bool:
        return disable_autostart(self.task_name, elevate=elevate)

    def get_executable_path(self) -> str:
        return get_executable_path()
