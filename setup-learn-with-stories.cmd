@echo off
setlocal
set "LEARN_ROOT=%~dp0"
pushd "%LEARN_ROOT%"
where python.exe >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python 3.11 or newer was not found. 1>&2
  popd
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" python.exe -S -m venv .venv
if errorlevel 1 (
  echo ERROR: The private Python environment could not be created. 1>&2
  popd
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo ERROR: PDF support could not be installed. Check the internet connection and try again. 1>&2
  popd
  exit /b 1
)
echo.
echo Setup complete. Run start-learn-with-stories.cmd to open the application.
popd
