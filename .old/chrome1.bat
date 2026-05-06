@echo off
REM Chrome 원격 디버깅 모드 실행

set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
set USER_DATA_DIR="C:\chrome_debug"

%CHROME_PATH% --remote-debugging-port=9222 --user-data-dir=%USER_DATA_DIR%