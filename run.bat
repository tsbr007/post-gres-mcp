@echo off
REM ============================================================
REM  PostgreSQL Manager — Run Desktop GUI
REM ============================================================

echo.
echo  Starting PostgreSQL Manager...
echo.

cd /d "%~dp0"

REM ── Check dependencies installed ─────────────────────────────
python -c "import psycopg2; import sqlparse; import faker" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  Dependencies not installed. Running installer first...
    echo.
    call "%~dp0install.bat"
)

REM ── Launch the application ───────────────────────────────────
python main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  Application exited with an error. See above for details.
    pause
)
