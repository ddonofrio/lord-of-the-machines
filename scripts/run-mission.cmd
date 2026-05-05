@echo off
setlocal

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%" >nul

set "RESET_FLAG="
if /I "%~1"=="--fresh" (
  set "RESET_FLAG=--reset-state"
)
if /I "%LOTM_RESET_STATE%"=="1" (
  set "RESET_FLAG=--reset-state"
)

if "%OPENAI_API_KEY%"=="" (
  echo [ERROR] OPENAI_API_KEY is not set.
  echo Set it first, for example:
  echo   setx OPENAI_API_KEY "your_key_here"
  popd >nul
  exit /b 2
)

set "PYTHONPATH=src"

echo [1/2] Bootstrapping missions...
python -m lord_of_the_machines.mission --bootstrap-only %RESET_FLAG% --json
if errorlevel 1 (
  popd >nul
  exit /b %errorlevel%
)

echo [2/2] Running mission loop...
python -m lord_of_the_machines.mission --json --max-follow-up-rounds 6 --require-all-completed
set "EXIT_CODE=%errorlevel%"

popd >nul
exit /b %EXIT_CODE%
