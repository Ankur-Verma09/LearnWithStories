@echo off
setlocal
set "STORY_TUTOR_ROOT=%~dp0"
set "PYTHONPATH=%STORY_TUTOR_ROOT%src"

where python.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found. Install Python 3.11 or newer and add python.exe to PATH. 1>&2
  exit /b 1
)

pushd "%STORY_TUTOR_ROOT%"
if exist "%STORY_TUTOR_ROOT%.venv\Scripts\python.exe" (
  "%STORY_TUTOR_ROOT%.venv\Scripts\python.exe" -m story_tutor --config "%STORY_TUTOR_ROOT%config\settings.json" %*
) else (
  python.exe -S -m story_tutor --config "%STORY_TUTOR_ROOT%config\settings.json" %*
)
set "STORY_TUTOR_EXIT=%ERRORLEVEL%"
popd
exit /b %STORY_TUTOR_EXIT%
