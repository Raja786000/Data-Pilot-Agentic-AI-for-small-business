@echo off
setlocal
title DataPilot
cd /d "%~dp0"

where python >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add Python to PATH". & pause & exit /b 1)
where npm >nul 2>nul || (echo Node.js is not installed. Get the LTS version from https://nodejs.org/ & pause & exit /b 1)

if not exist backend\.venv (
  echo [1/4] Creating Python environment...
  python -m venv backend\.venv || (pause & exit /b 1)
)
echo [2/4] Installing Python packages (first time takes a minute)...
call backend\.venv\Scripts\activate.bat
python -m pip install -q -r backend\requirements.txt || (pause & exit /b 1)

if not exist frontend\node_modules (
  echo [3/4] Installing interface packages (first time only)...
  pushd frontend & call npm install || (popd & pause & exit /b 1)
  popd
)
if not exist frontend\dist (
  echo [4/4] Building the interface...
  pushd frontend & call npm run build || (popd & pause & exit /b 1)
  popd
)

echo.
echo DataPilot is starting at http://localhost:8000   (close this window to stop it)
start "" http://localhost:8000
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
