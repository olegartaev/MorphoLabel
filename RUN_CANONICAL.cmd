@echo off
setlocal
set "SIMM_ROOT=%~dp0"
cd /d "%SIMM_ROOT%"
set "PYTHONPATH="
set "PYTHONHOME="
python -E -B "%SIMM_ROOT%tools\canonical_exec.py" %*
exit /b %ERRORLEVEL%
