@echo off
setlocal
set "LEARN_ROOT=%~dp0"
set "PYTHONPATH=%LEARN_ROOT%src"
rem Discard stale terminal keys and load only the key explicitly saved by the configurator.
set "OPENAI_API_KEY="
for /f "usebackq delims=" %%K in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User')"`) do set "OPENAI_API_KEY=%%K"
set "OPENAI_API_KEYS="
for /f "usebackq delims=" %%K in (`powershell.exe -NoProfile -Command "[Environment]::GetEnvironmentVariable('OPENAI_API_KEYS','User')"`) do set "OPENAI_API_KEYS=%%K"
pushd "%LEARN_ROOT%"
echo Starting Learn With Stories...
echo Open http://127.0.0.1:8766 in your browser.
if not defined OPENAI_API_KEY if not defined OPENAI_API_KEYS echo NOTE: OpenAI is selected but no saved API key was found. Run configure-openai-keys.cmd.
if exist "%LEARN_ROOT%.venv\Scripts\python.exe" (
  "%LEARN_ROOT%.venv\Scripts\python.exe" -m story_tutor.web_server --config "%LEARN_ROOT%config\settings.json" --static "%LEARN_ROOT%web" --host 127.0.0.1 --port 8766
) else (
  echo NOTE: PDF uploads need the one-time setup-learn-with-stories.cmd step.
  python.exe -S -m story_tutor.web_server --config "%LEARN_ROOT%config\settings.json" --static "%LEARN_ROOT%web" --host 127.0.0.1 --port 8766
)
set "LEARN_EXIT=%ERRORLEVEL%"
popd
exit /b %LEARN_EXIT%
