@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m visual_latex_editor --open %*
) else (
  python -m visual_latex_editor --open %*
)
if errorlevel 1 pause
