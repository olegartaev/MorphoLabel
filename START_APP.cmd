@echo off
rem START_APP.vbs calls "RUN_CANONICAL.cmd" shell in a hidden console.
start "" "%SystemRoot%\System32\wscript.exe" "%~dp0START_APP.vbs"
exit /b
