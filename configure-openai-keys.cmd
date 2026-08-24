@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configure-openai-keys.ps1"
if errorlevel 1 pause
