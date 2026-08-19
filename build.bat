@echo off
setlocal enabledelayedexpansion
title zapret++ Build

echo ============================================================
echo   zapret++  -  Build Standalone EXE
echo ============================================================
echo.

:: Detect Python launcher (python or py)
set "PYCMD="
where python >nul 2>&1
if not errorlevel 1 (
    set "PYCMD=python"
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PYCMD=py"
    )
)

if "%PYCMD%"=="" (
    echo ERROR: Python not found!
    echo Install Python from https://python.org and add to PATH.
    echo.
    pause
    exit /b 1
)

echo [OK] Python found:
%PYCMD% --version
echo.

:: Install dependencies
echo [1/3] Installing dependencies...
echo.
%PYCMD% -m pip install --upgrade pip
%PYCMD% -m pip install PyQt6 pyinstaller psutil requests ping3
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies!
    pause
    exit /b 1
)
echo.

:: Check required files
echo [2/3] Checking files...
if not exist "zapret_pp.py" (
    echo ERROR: zapret_pp.py not found!
    echo Make sure you run this bat from the same folder as zapret_pp.py
    pause
    exit /b 1
)
if not exist "zapret_pp.spec" (
    echo ERROR: zapret_pp.spec not found!
    pause
    exit /b 1
)
if not exist "icons\ico.ico"     echo WARNING: icons\ico.ico not found
if not exist "icons\on.png"      echo WARNING: icons\on.png not found
if not exist "icons\off.png"     echo WARNING: icons\off.png not found
if not exist "icons\pending.png" echo WARNING: icons\pending.png not found
echo.

:: Build
echo [3/3] Building EXE...
echo.
%PYCMD% -m PyInstaller zapret_pp.spec --clean --noconfirm
echo.

:: Result
if exist "dist\zapret++.exe" (
    echo ============================================================
    echo   SUCCESS: dist\zapret++.exe
    echo.
    echo   Copy zapret++.exe somewhere and place any folder next to
    echo   it containing bat files and bin\winws.exe.
    echo ============================================================
) else (
    echo ============================================================
    echo   BUILD FAILED - see errors above
    echo ============================================================
)
echo.
pause