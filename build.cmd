@echo off
rem Builds NDPT's Windows programs into dist\, runnable on a PC with no Python:
rem   build              ndpt-tui.exe (terminal UI) and ndpt-gui.exe (desktop)
rem   build gui          just one of them: tui or gui
rem   build --onedir     a folder per program instead of one file (starts faster)
rem For an icon, save a square PNG as ndpt\gui\icon.png first.
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo There's no Python at "%PY%".
    echo Set the project up first: see README.md.
    pause
    exit /b 1
)
"%PY%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller isn't in .venv yet. Install the build tools, then run this again:
    echo   .venv\Scripts\python -m pip install -e ".[build]"
    pause
    exit /b 1
)
"%PY%" "%~dp0packaging\build.py" %*
set CODE=%errorlevel%
rem Keep a double-clicked window open long enough to read the result.
pause
exit /b %CODE%
