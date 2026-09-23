"""
Autostart service using Windows Task Scheduler (schtasks.exe).
Runs with highest privileges (/rl highest) on user logon (/sc onlogon).
"""
import os
import subprocess
import sys
from pathlib import Path

TASK_NAME = "zapret++"


def get_executable_path() -> str:
    """
    Get the path to the binary or script:
    - If frozen (.exe): sys.executable
    - If script (.py): sys.argv[0]
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def is_autostart_enabled(task_name: str = TASK_NAME) -> bool:
    """
    Check if the task is present in Windows Task Scheduler.
    Runs: schtasks /query /tn <task_name>
    """
    cmd = ["schtasks", "/query", "/tn", task_name]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            encoding="cp866",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return res.returncode == 0
    except Exception:
        return False


def enable_autostart(task_name: str = TASK_NAME) -> bool:
    """
    Create a scheduled task with highest privileges on user logon.
    Runs: schtasks /create /tn <task_name> /tr "<path>" /sc onlogon /rl highest /f
    """
    exe_path = get_executable_path()
    cmd = [
        "schtasks",
        "/create",
        "/tn", task_name,
        "/tr", f'"{exe_path}"',
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
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return res.returncode == 0
    except Exception:
        return False


def disable_autostart(task_name: str = TASK_NAME) -> bool:
    """
    Delete the scheduled task from Windows Task Scheduler.
    Runs: schtasks /delete /tn <task_name> /f
    """
    if not is_autostart_enabled(task_name):
        return True

    cmd = ["schtasks", "/delete", "/tn", task_name, "/f"]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            encoding="cp866",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return res.returncode == 0
    except Exception:
        return False


class AutostartService:
    """Service class for managing Windows Task Scheduler autostart."""

    def __init__(self, task_name: str = TASK_NAME):
        self.task_name = task_name

    def is_autostart_enabled(self) -> bool:
        return is_autostart_enabled(self.task_name)

    def enable_autostart(self) -> bool:
        return enable_autostart(self.task_name)

    def disable_autostart(self) -> bool:
        return disable_autostart(self.task_name)

    def get_executable_path(self) -> str:
        return get_executable_path()
