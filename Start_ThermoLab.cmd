@echo off
cd /d "%~dp0"
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -B website\serve.py --port 0 --open
) else (
  python -B website\serve.py --port 0 --open
)
if errorlevel 1 pause
