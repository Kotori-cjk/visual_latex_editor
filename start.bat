@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if exist "%~dp0tools\tectonic\tectonic.exe" set "VISUAL_LATEX_TECTONIC=%~dp0tools\tectonic\tectonic.exe"
if exist "%~dp0tools\poppler\pdftoppm.exe" set "VISUAL_LATEX_PDFTOPPM=%~dp0tools\poppler\pdftoppm.exe"
if exist "%~dp0tools\tectonic-cache" set "TECTONIC_CACHE_DIR=%~dp0tools\tectonic-cache"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\launch.py" %*
) else (
  python "%~dp0scripts\launch.py" %*
)
if errorlevel 1 pause
