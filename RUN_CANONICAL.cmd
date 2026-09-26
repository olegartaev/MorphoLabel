@echo off
setlocal
set "MORPHOLABEL_ROOT=%~dp0"
cd /d "%MORPHOLABEL_ROOT%"
set "PYTHONPATH="
set "PYTHONHOME="
python -E -B "%MORPHOLABEL_ROOT%tools\canonical_exec.py" %*
exit /b %ERRORLEVEL%
