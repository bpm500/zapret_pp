# -*- mode: python ; coding: utf-8 -*-
import os

a = Analysis(
    ['zapret_pp.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icons/ico.ico',     'icons'),
        ('icons/ico.png',     'icons'),
        ('icons/on.png',      'icons'),
        ('icons/off.png',     'icons'),
        ('icons/pending.png', 'icons'),
    ],
    hiddenimports=[
        # PyQt6
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        # Network / ping
        'ping3',
        'ping3.errors',
        'requests',
        'urllib3',
        'urllib3.util',
        'certifi',
        'charset_normalizer',
        'idna',
        # Process
        'psutil',
        'psutil._psutil_windows',
        'psutil._pswindows',
        # Stdlib
        'json',
        'winreg',
        'ctypes',
        'ctypes.wintypes',
        'subprocess',
        'threading',
        'pathlib',
        'time',
        'os',
        'sys',
        'socket',
        'random',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'PIL',
        'pystray',
        'matplotlib',
        'numpy',
        'scipy',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='zapret++',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons/ico.ico',
    uac_admin=True,
)
