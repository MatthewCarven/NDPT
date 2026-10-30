@echo off
rem NDPT's terminal UI, run with the project's own Python: no venv to activate.
rem Double-click it, or give it what "ndpt tui" takes:
rem   starttui 1.1.1.1 example.com
rem   starttui --trace 1.1.1.1
rem   starttui --demo
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo There's no Python at "%PY%".
    echo Set the project up first: see README.md.
    pause
    exit /b 1
)
"%PY%" -m ndpt tui %*
set CODE=%errorlevel%
rem Keep a double-clicked window open long enough to read an error.
if %CODE% neq 0 pause
exit /b %CODE%
