@echo off
cd /d "%~dp0"

REM --- Check Python availability ---
where python >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not on PATH.
    echo Install Python 3.11+ and retry.
    pause
    exit /b 1
)

REM --- Create venv if missing ---
if not exist "%~dp0env\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%~dp0env"
    if errorlevel 1 (
        echo Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM --- Activate venv ---
call "%~dp0env\Scripts\activate.bat"
if errorlevel 1 (
    echo Failed to activate virtual environment.
    pause
    exit /b 1
)

REM --- Install dependencies ---
echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

echo Starting application...
python main.py
pause
