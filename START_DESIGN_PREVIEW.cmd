@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH="
set "PYTHONHOME="
python -E -B "%~dp0tools\design_preview.py" %*
if errorlevel 1 pause
