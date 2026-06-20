@echo off
REM ============================================================
REM  PostgreSQL Manager + MCP Server — Installation Script
REM  Run this once on a fresh machine to set up everything.
REM ============================================================

echo.
echo ============================================================
echo  PostgreSQL Manager + MCP Server — Installer
echo ============================================================
echo.

REM ── Check Python ─────────────────────────────────────────────
echo [1/4] Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo    Found Python %PYVER%

REM ── Check pip ────────────────────────────────────────────────
echo [2/4] Checking pip...
pip --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    pip not found. Installing pip...
    python -m ensurepip --upgrade
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: Could not install pip. Please install manually.
        pause
        exit /b 1
    )
)
echo    pip is available.

REM ── Upgrade pip ──────────────────────────────────────────────
echo [3/4] Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1
echo    pip upgraded.

REM ── Install dependencies ────────────────────────────────────
echo [4/4] Installing Python dependencies...
echo.
pip install -r "%~dp0requirements.txt"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Dependency installation failed. See errors above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Installation complete!
echo ============================================================
echo.
echo  To run the Desktop GUI:
echo    run.bat
echo.
echo  To run the MCP Server (for Claude Desktop):
echo    python mcp_server.py
echo.
echo  Edit config.ini to add your PostgreSQL connection profiles.
echo ============================================================
echo.
pause
